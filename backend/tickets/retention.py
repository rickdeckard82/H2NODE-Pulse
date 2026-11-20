"""Irreversible data disposal, run only by the isolated retention service (ADR 0007)."""

from datetime import timedelta

from django.db import transaction
from django.db.models import ProtectedError, Q
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.authentication import IsIdentityAdmin
from core.identity import audit, identity_lock
from core.identity_views import NoStoreMixin, locked_actor
from core.models import Department, IdentityEvent, Membership, SupportGroup, User
from core.serializers import StrictSerializer
from tickets.attachments import path_for
from tickets.models import (
    Attachment,
    AttachmentScan,
    AuditEvent,
    Category,
    Comment,
    HiddenSecret,
    IdempotencyRecord,
    IntegrationCheck,
    NotificationAttempt,
    NotificationDelivery,
    NotificationOutbox,
    NotificationRead,
    ReadGrant,
    RetentionPolicy,
    Ticket,
    TicketEvent,
)

MINIMUM_DAYS = 30
GRACE = timedelta(hours=24)
INTERVAL = timedelta(hours=24)
CONFIRMATION = "REMOVER"
PERIODS = [
    "tickets_days",
    "users_days",
    "groups_days",
    "categories_days",
    "departments_days",
    "logs_days",
]


def cutoff(days, now):
    return now - timedelta(days=days)


def candidates(policy, now):
    """Records past their period; a period of zero disposes of nothing in that class."""
    closed = Q(state=Ticket.State.CLOSED, closed_at__lte=cutoff(policy.tickets_days, now))
    cancelled = Q(state=Ticket.State.CANCELLED, updated_at__lte=cutoff(policy.tickets_days, now))

    def inactive(model, days):
        if not days:
            return model.objects.none()
        return model.objects.filter(is_active=False, deactivated_at__lte=cutoff(days, now))

    return {
        "tickets": Ticket.objects.filter(closed | cancelled)
        if policy.tickets_days
        else Ticket.objects.none(),
        # Service accounts such as system:sla are inactive by design and sign history.
        "users": inactive(User, policy.users_days).exclude(username__startswith="system:"),
        "categories": inactive(Category, policy.categories_days),
        "groups": inactive(SupportGroup, policy.groups_days),
        "departments": inactive(Department, policy.departments_days),
    }


def log_queries(policy, now):
    if not policy.logs_days:
        return []
    limit = cutoff(policy.logs_days, now)
    return [
        IdentityEvent.objects.filter(created_at__lte=limit),
        AuditEvent.objects.filter(created_at__lte=limit),
        IntegrationCheck.objects.filter(created_at__lte=limit),
    ]


def preview(policy, now):
    counts = {name: query.count() for name, query in candidates(policy, now).items()}
    counts["logs"] = sum(query.count() for query in log_queries(policy, now))
    return counts


def wipe(queryset):
    # Every relation here is PROTECT, which blocks the ORM even for rows deleted together.
    return queryset._raw_delete(queryset.db)


def purge_ticket(ticket):
    if Ticket.objects.filter(related_ticket=ticket).exists():
        return False  # A newer ticket still points here; disposed of after that one.
    with transaction.atomic():
        attachments = Attachment.objects.filter(comment__ticket=ticket)
        paths = [path_for(key) for key in attachments.values_list("storage_key", flat=True)]
        wipe(AttachmentScan.objects.filter(attachment__comment__ticket=ticket))
        wipe(attachments)
        wipe(NotificationAttempt.objects.filter(delivery__outbox__event__ticket=ticket))
        wipe(NotificationDelivery.objects.filter(outbox__event__ticket=ticket))
        wipe(NotificationOutbox.objects.filter(event__ticket=ticket))
        wipe(IdempotencyRecord.objects.filter(event__ticket=ticket))
        wipe(AuditEvent.objects.filter(event__ticket=ticket))
        wipe(NotificationRead.objects.filter(event__ticket=ticket))
        wipe(TicketEvent.objects.filter(ticket=ticket))
        wipe(HiddenSecret.objects.filter(ticket=ticket))
        wipe(Comment.objects.filter(ticket=ticket))
        wipe(Ticket.participants.through.objects.filter(ticket=ticket))
        wipe(Ticket.objects.filter(pk=ticket.pk))
        # After the commit: a rollback must never leave rows pointing to erased files.
        transaction.on_commit(lambda: [path.unlink(missing_ok=True) for path in paths])
    return True


def purge_record(record):
    """Records still referenced stay until what references them expires."""
    try:
        with transaction.atomic():
            if isinstance(record, User):
                wipe(ReadGrant.objects.filter(user=record))
            if isinstance(record, SupportGroup):
                wipe(ReadGrant.objects.filter(group=record))
                wipe(Membership.objects.filter(group=record))
            record.delete()
    except ProtectedError:
        return False
    return True


def next_run(policy):
    if not policy.enabled:
        return None
    grace_over = policy.updated_at + GRACE
    if policy.last_run_at:
        return max(grace_over, policy.last_run_at + INTERVAL)
    return grace_over


def run_retention(now=None):
    now = now or timezone.now()
    policy = RetentionPolicy.objects.first()
    scheduled = next_run(policy) if policy else None
    if not scheduled or now < scheduled:
        return None
    removed, waiting = {}, {}
    logs = sum(wipe(query) for query in log_queries(policy, now))
    # Logs and tickets go first because they are what keeps accounts and groups referenced.
    found = candidates(policy, now)
    for name in ["tickets", "users", "categories", "groups", "departments"]:
        purge = purge_ticket if name == "tickets" else purge_record
        results = [purge(record) for record in found[name]]
        removed[name], waiting[name] = sum(results), len(results) - sum(results)
    removed["logs"] = logs
    result = {"removed": removed, "waiting": waiting}
    # Counts only: the record of a disposal must not keep what was disposed of.
    IdentityEvent.objects.create(action="retention.purged", subject_id="policy", changes=result)
    RetentionPolicy.objects.filter(pk=policy.pk).update(last_run_at=now, last_result=result)
    return result


class RetentionInput(StrictSerializer):
    enabled = serializers.BooleanField()
    tickets_days = serializers.IntegerField(min_value=0, max_value=36500)
    users_days = serializers.IntegerField(min_value=0, max_value=36500)
    groups_days = serializers.IntegerField(min_value=0, max_value=36500)
    categories_days = serializers.IntegerField(min_value=0, max_value=36500)
    departments_days = serializers.IntegerField(min_value=0, max_value=36500)
    logs_days = serializers.IntegerField(min_value=0, max_value=36500)
    confirmation = serializers.CharField(max_length=20, required=False, allow_blank=True)
    reason = serializers.CharField(max_length=300)

    def validate(self, attrs):
        for name in PERIODS:
            if 0 < attrs[name] < MINIMUM_DAYS:
                raise ValidationError({name: f"Use 0 ou pelo menos {MINIMUM_DAYS} dias."})
        if attrs["enabled"] and attrs.get("confirmation") != CONFIRMATION:
            raise ValidationError({"confirmation": f"Digite {CONFIRMATION} para confirmar."})
        return attrs


class PreviewOutput(serializers.Serializer):
    tickets = serializers.IntegerField()
    users = serializers.IntegerField()
    categories = serializers.IntegerField()
    groups = serializers.IntegerField()
    departments = serializers.IntegerField()
    logs = serializers.IntegerField()


class RetentionOutput(serializers.ModelSerializer):
    preview = serializers.SerializerMethodField()
    next_run_at = serializers.SerializerMethodField()

    @extend_schema(responses=PreviewOutput)
    def get_preview(self, obj) -> PreviewOutput:
        return preview(obj, timezone.now())

    def get_next_run_at(self, obj) -> str | None:
        scheduled = next_run(obj) if obj.pk and obj.updated_at else None
        return scheduled.isoformat() if scheduled else None

    class Meta:
        model = RetentionPolicy
        fields = [
            "enabled",
            *PERIODS,
            "updated_at",
            "last_run_at",
            "last_result",
            "preview",
            "next_run_at",
        ]


class RetentionSettingsView(NoStoreMixin, APIView):
    permission_classes = [IsIdentityAdmin]

    @extend_schema(responses=RetentionOutput)
    def get(self, request):
        policy = RetentionPolicy.objects.first() or RetentionPolicy()
        return Response(RetentionOutput(policy).data)

    @extend_schema(request=RetentionInput, responses=RetentionOutput)
    @transaction.atomic
    def patch(self, request):
        identity_lock()
        actor = locked_actor(request, admin=True)
        serializer = RetentionInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data.pop("confirmation", None)
        reason = data.pop("reason")
        policy = RetentionPolicy.objects.select_for_update().first() or RetentionPolicy()
        for field, value in data.items():
            setattr(policy, field, value)
        policy.save()  # auto_now restarts the grace period on every change.
        audit(actor, "retention.updated", policy.pk, {"reason": reason, **data})
        return Response(RetentionOutput(policy).data)
