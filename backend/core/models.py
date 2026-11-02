from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower


class User(AbstractUser):
    class Role(models.TextChoices):
        COLLABORATOR = "collaborator", "Colaborador"
        TECHNICIAN = "technician", "Técnico"
        MANAGER = "manager", "Gestor de TI"
        ADMIN = "admin", "Administrador"
        PRIVACY = "privacy", "Responsável por privacidade"

    role = models.CharField(max_length=20, choices=Role, default=Role.COLLABORATOR)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    session_version = models.PositiveIntegerField(default=1)
    department = models.ForeignKey("Department", null=True, blank=True, on_delete=models.PROTECT)
    mfa_secret = models.TextField(blank=True)
    mfa_enabled = models.BooleanField(default=False)
    mfa_last_counter = models.BigIntegerField(default=-1)
    recovery_hashes = models.JSONField(default=list)
    avatar = models.TextField(blank=True)
    # In-app bell: events up to this instant are cleared; muted hides the unread badge.
    notifications_cleared_at = models.DateTimeField(null=True, blank=True)
    notifications_muted = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("email"), condition=~models.Q(email=""), name="user_email_ci_unique"
            ),
        ]

    @property
    def privileged(self):
        return self.role != self.Role.COLLABORATOR


class Department(models.Model):
    name = models.CharField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True)


class SupportGroup(models.Model):
    name = models.CharField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True)


class Membership(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    group = models.ForeignKey(SupportGroup, on_delete=models.PROTECT)
    can_view_restricted = models.BooleanField(default=False)
    can_transfer = models.BooleanField(default=False)
    can_cancel = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "group"], name="membership_unique")]


class AllowedDomain(models.Model):
    domain = models.CharField(max_length=253, unique=True)
    is_active = models.BooleanField(default=True)


class IdentityEvent(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(
        User, null=True, on_delete=models.PROTECT, related_name="identity_actions"
    )
    action = models.CharField(max_length=80)
    subject_id = models.CharField(max_length=80)
    changes = models.JSONField(default=dict)


class IdentityToken(models.Model):
    digest = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    purpose = models.CharField(max_length=20)
    email = models.EmailField()
    version = models.PositiveIntegerField()
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True)


class IdentityMail(models.Model):
    token = models.OneToOneField(IdentityToken, on_delete=models.CASCADE)
    encrypted_body = models.TextField()
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField()
    sent_at = models.DateTimeField(null=True)


class AuthRateBucket(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    window = models.BigIntegerField()
    count = models.PositiveIntegerField(default=0)


class TrustedDevice(models.Model):
    digest = models.CharField(max_length=64, primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    version = models.PositiveIntegerField()
    credential_stamp = models.CharField(max_length=64)
    created_at = models.DateTimeField()
    expires_at = models.DateTimeField(db_index=True)


class SmtpConfiguration(models.Model):
    """Single configuration, with credentials encrypted by the external identity key."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    enabled = models.BooleanField(default=False)
    host = models.CharField(max_length=253, blank=True)
    port = models.PositiveIntegerField(default=587)
    security = models.CharField(
        max_length=8, choices=[("starttls", "STARTTLS"), ("ssl", "TLS")], default="starttls"
    )
    username = models.CharField(max_length=254, blank=True)
    encrypted_password = models.TextField(blank=True)
    from_email = models.EmailField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name="smtp_singleton")]


class ChatConfiguration(models.Model):
    """Single Google Chat space webhook; the URL is always encrypted at rest."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    enabled = models.BooleanField(default=False)
    encrypted_webhook = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name="chat_singleton")]
