import uuid
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import connection, models
from django.db.models import Max
from django.utils import timezone


class Category(models.Model):
    name = models.CharField(max_length=120, unique=True)
    group = models.ForeignKey("core.SupportGroup", on_delete=models.PROTECT)
    restricted = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    deactivated_at = models.DateTimeField(null=True, editable=False)
    # Suggested at ticket opening; the requester may choose another level.
    priority = models.PositiveSmallIntegerField(default=3)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(priority__range=(1, 4)), name="category_valid_priority"
            )
        ]


class RetentionPolicy(models.Model):
    """Single policy; a period of zero keeps that class of data indefinitely."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    enabled = models.BooleanField(default=False)
    tickets_days = models.PositiveIntegerField(default=0)
    users_days = models.PositiveIntegerField(default=0)
    groups_days = models.PositiveIntegerField(default=0)
    categories_days = models.PositiveIntegerField(default=0)
    departments_days = models.PositiveIntegerField(default=0)
    logs_days = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)
    last_run_at = models.DateTimeField(null=True)
    last_result = models.JSONField(default=dict)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name="retention_singleton")]


class ReadGrant(models.Model):
    """Retired by ADR 0005: administrators see everything. Table kept, no longer read."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    group = models.ForeignKey("core.SupportGroup", on_delete=models.PROTECT)
    internal = models.BooleanField(default=False)
    restricted = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "group"], name="ticket_read_grant_unique")
        ]


class ReopenPolicy(models.Model):
    hours = models.PositiveIntegerField()
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.CharField(max_length=300)


class SlaPolicy(models.Model):
    """Append-only version; each ticket freezes the version in force when it was opened."""

    created_at = models.DateTimeField(default=timezone.now, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.CharField(max_length=300)
    timezone = models.CharField(max_length=64, default="America/Sao_Paulo")
    # Monday is 0, as in date.weekday().
    weekdays = models.CharField(max_length=13, default="0,1,2,3,4")
    start_time = models.TimeField()
    end_time = models.TimeField()
    holidays = models.TextField(blank=True)
    p1_response = models.PositiveIntegerField()
    p1_resolution = models.PositiveIntegerField()
    p2_response = models.PositiveIntegerField()
    p2_resolution = models.PositiveIntegerField()
    p3_response = models.PositiveIntegerField()
    p3_resolution = models.PositiveIntegerField()
    p4_response = models.PositiveIntegerField()
    p4_resolution = models.PositiveIntegerField()


class ReportExport(models.Model):
    """Short-lived CSV kept only until its download link expires."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    expires_at = models.DateTimeField(db_index=True)
    start = models.DateField()
    end = models.DateField()
    rows = models.PositiveIntegerField()
    content = models.TextField()


def next_number():
    """YYYYMM followed by a six-digit monthly sequence, e.g. 202611000001."""
    period = int(timezone.localtime(timezone=ZoneInfo("America/Sao_Paulo")).strftime("%Y%m"))
    with connection.cursor() as cursor:
        # Serializes numbering per month until the caller's transaction ends.
        cursor.execute("SELECT pg_advisory_xact_lock(7219840, %s)", [period])
    base = period * 1_000_000
    last = Ticket.objects.filter(number__gt=base, number__lt=base + 1_000_000).aggregate(
        last=Max("number")
    )["last"]
    if last == base + 999_999:
        raise RuntimeError("Sequência mensal de chamados esgotada.")
    return (last or base) + 1


class Ticket(models.Model):
    class State(models.TextChoices):
        NEW = "new", "Novo"
        ACTIVE = "in_progress", "Em atendimento"
        INFORMATION = "waiting_information", "Aguardando informações"
        TEST = "waiting_test", "Aguardando teste"
        RESOLVED = "resolved", "Resolvido"
        CLOSED = "closed", "Fechado"
        CANCELLED = "cancelled", "Cancelado"

    # Neither this number nor the UUID grants access.
    number = models.BigIntegerField(primary_key=True, default=next_number, editable=False)
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="requested_tickets"
    )
    department = models.ForeignKey("core.Department", null=True, on_delete=models.PROTECT)
    department_name = models.CharField(max_length=120, blank=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT)
    subject = models.CharField(max_length=200)
    description = models.TextField()
    # Historical only: tickets opened before priority came from the category (ADR 0004).
    impact = models.PositiveSmallIntegerField(null=True)
    urgency = models.PositiveSmallIntegerField(null=True)
    priority = models.PositiveSmallIntegerField()
    group = models.ForeignKey("core.SupportGroup", on_delete=models.PROTECT)
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.PROTECT,
        related_name="assigned_tickets",
    )
    # Other technicians working alongside the assignee; they may act as the assignee does.
    participants = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="participating_tickets"
    )
    state = models.CharField(max_length=24, choices=State, default=State.NEW)
    restricted = models.BooleanField(default=False)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(default=timezone.now, editable=False)
    resolved_at = models.DateTimeField(null=True)
    closed_at = models.DateTimeField(null=True)
    resolution_class = models.CharField(max_length=80, blank=True)
    reopen_policy = models.ForeignKey(ReopenPolicy, null=True, on_delete=models.PROTECT)
    sla_policy = models.ForeignKey(SlaPolicy, null=True, on_delete=models.PROTECT)
    related_ticket = models.ForeignKey("self", null=True, on_delete=models.PROTECT)
    # Stored only when the requester consents at opening time.
    client_ip = models.GenericIPAddressField(null=True, blank=True)
    client_os = models.CharField(max_length=120, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["requester", "-created_at", "-number"]),
            models.Index(fields=["group", "state", "priority", "number"]),
            models.Index(fields=["assignee", "state", "number"]),
            models.Index(fields=["state", "created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    state__in=[
                        "new",
                        "in_progress",
                        "waiting_information",
                        "waiting_test",
                        "resolved",
                        "closed",
                        "cancelled",
                    ]
                ),
                name="ticket_valid_state",
            ),
            models.CheckConstraint(
                condition=~models.Q(state="new") | models.Q(assignee=None),
                name="ticket_new_unassigned",
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=["new", "cancelled"])
                | models.Q(assignee__isnull=False),
                name="ticket_active_assigned",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    impact__range=(1, 3),
                    urgency__range=(1, 3),
                    priority__range=(1, 4),
                    version__gte=1,
                ),
                name="ticket_valid_levels",
            ),
        ]


class Comment(models.Model):
    class Visibility(models.TextChoices):
        PUBLIC = "public", "Resposta pública"
        INTERNAL = "internal", "Nota interna"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(Ticket, on_delete=models.PROTECT, related_name="comments")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    body = models.TextField()
    visibility = models.CharField(max_length=8, choices=Visibility)
    corrects = models.ForeignKey("self", null=True, on_delete=models.PROTECT)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(visibility__in=["public", "internal"]),
                name="comment_valid_visibility",
            )
        ]


class TicketEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(Ticket, on_delete=models.PROTECT, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    correlation_id = models.UUIDField(default=uuid.uuid4, editable=False)
    action = models.CharField(max_length=40)
    visibility = models.CharField(max_length=8, choices=Comment.Visibility)
    version = models.PositiveIntegerField()
    from_state = models.CharField(max_length=24, blank=True)
    to_state = models.CharField(max_length=24)
    comment = models.OneToOneField(Comment, null=True, on_delete=models.PROTECT)
    changes = models.JSONField(default=dict)

    class Meta:
        ordering = ["version"]
        constraints = [
            models.UniqueConstraint(
                fields=["ticket", "version"], name="event_ticket_version_unique"
            )
        ]


class AuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.OneToOneField(TicketEvent, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    correlation_id = models.UUIDField(editable=False)
    action = models.CharField(max_length=40)
    # No free text/body duplicated into the operational audit trail.
    changes = models.JSONField(default=dict)


class NotificationOutbox(models.Model):
    event = models.OneToOneField(TicketEvent, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    audience = models.CharField(max_length=24)
    payload = models.JSONField()
    status = models.CharField(max_length=16, default="pending")
    available_at = models.DateTimeField(default=timezone.now, db_index=True)
    lease_token = models.UUIDField(null=True, editable=False)
    lease_until = models.DateTimeField(null=True, db_index=True)
    completed_at = models.DateTimeField(null=True)


class NotificationDelivery(models.Model):
    class Channel(models.TextChoices):
        EMAIL = "email", "E-mail"
        CHAT = "chat", "Google Chat"
        CHAT_DM = "chat_dm", "Google Chat individual"

    outbox = models.ForeignKey(
        NotificationOutbox, on_delete=models.PROTECT, related_name="deliveries"
    )
    channel = models.CharField(max_length=8, choices=Channel)
    recipient_key = models.CharField(max_length=320)
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    status = models.CharField(max_length=16, default="pending")
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_attempt_at = models.DateTimeField(null=True)
    sent_at = models.DateTimeField(null=True)
    provider_id = models.CharField(max_length=200, blank=True)
    last_error_code = models.CharField(max_length=80, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["outbox", "channel", "recipient_key"],
                name="notification_delivery_unique",
            )
        ]
        indexes = [models.Index(fields=["status", "next_attempt_at"])]


class NotificationAttempt(models.Model):
    delivery = models.ForeignKey(
        NotificationDelivery, on_delete=models.PROTECT, related_name="history"
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    outcome = models.CharField(max_length=16)
    error_code = models.CharField(max_length=80, blank=True)
    provider_id = models.CharField(max_length=200, blank=True)


class IntegrationCheck(models.Model):
    """Controlled test queued by the API; only the worker has network egress."""

    channel = models.CharField(max_length=8, choices=NotificationDelivery.Channel)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    status = models.CharField(max_length=16, default="pending")
    completed_at = models.DateTimeField(null=True)
    error_code = models.CharField(max_length=80, blank=True)


class IdempotencyRecord(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    operation = models.CharField(max_length=100)
    key = models.UUIDField()
    payload_hash = models.CharField(max_length=64)
    event = models.OneToOneField(TicketEvent, on_delete=models.PROTECT)
    response = models.JSONField()
    status_code = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "operation", "key"], name="ticket_idempotency_unique"
            )
        ]


class Attachment(models.Model):
    """Private blob; visibility is always derived from its immutable comment."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    comment = models.ForeignKey("Comment", on_delete=models.PROTECT, related_name="attachments")
    storage_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=120)
    media_type = models.CharField(max_length=80)
    size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16,
        default="quarantine",
        choices=[("quarantine", "Quarentena"), ("clean", "Liberado"), ("blocked", "Bloqueado")],
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    scanned_at = models.DateTimeField(null=True)
    next_attempt = models.DateTimeField(default=timezone.now)
    attempts = models.PositiveIntegerField(default=0)


class AttachmentScan(models.Model):
    attachment = models.ForeignKey(Attachment, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    result = models.CharField(max_length=16)
    actor = models.CharField(max_length=32, default="system:antimalware", editable=False)
