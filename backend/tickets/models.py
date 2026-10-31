import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Category(models.Model):
    name = models.CharField(max_length=120, unique=True)
    group = models.ForeignKey("core.SupportGroup", on_delete=models.PROTECT)
    restricted = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)


class ReadGrant(models.Model):
    """Explicit read-only access for administrators/privacy, never implied by role."""

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


class Ticket(models.Model):
    class State(models.TextChoices):
        NEW = "new", "Novo"
        ACTIVE = "in_progress", "Em atendimento"
        INFORMATION = "waiting_information", "Aguardando informações"
        TEST = "waiting_test", "Aguardando teste"
        RESOLVED = "resolved", "Resolvido"
        CLOSED = "closed", "Fechado"
        CANCELLED = "cancelled", "Cancelado"

    # The sequence can have gaps. Neither this number nor the UUID grants access.
    number = models.BigAutoField(primary_key=True)
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="requested_tickets"
    )
    department = models.ForeignKey("core.Department", null=True, on_delete=models.PROTECT)
    department_name = models.CharField(max_length=120, blank=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT)
    subject = models.CharField(max_length=200)
    description = models.TextField()
    impact = models.PositiveSmallIntegerField()
    urgency = models.PositiveSmallIntegerField()
    priority = models.PositiveSmallIntegerField()
    group = models.ForeignKey("core.SupportGroup", on_delete=models.PROTECT)
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.PROTECT,
        related_name="assigned_tickets",
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
    related_ticket = models.ForeignKey("self", null=True, on_delete=models.PROTECT)

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
