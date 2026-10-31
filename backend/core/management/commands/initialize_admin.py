"""Opt-in operator provisioning, serialized and idempotent across container starts."""

import os
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.identity import audit, identity_lock, issue_token, normalize_email, password_hash
from core.models import AllowedDomain, IdentityEvent, IdentityToken, User
from core.serializers import DomainSerializer, EmailInput


class Command(BaseCommand):
    help = "Provisiona o administrador inicial a partir de BOOTSTRAP_ADMIN_* (opt-in)."

    @transaction.atomic
    def handle(self, *args, **options):
        if os.environ.get("BOOTSTRAP_ADMIN_ENABLED", "false").lower() != "true":
            self.stdout.write("Automatic administrator bootstrap disabled.")
            return
        email = normalize_email(os.environ.get("BOOTSTRAP_ADMIN_EMAIL", ""))
        trust = os.environ.get("BOOTSTRAP_ADMIN_TRUST_EMAIL", "false").lower() == "true"
        email_input = EmailInput(data={"email": email})
        if not email_input.is_valid():
            raise CommandError("Set a valid BOOTSTRAP_ADMIN_EMAIL.")
        domain = email.rsplit("@", 1)[1]
        domain_input = DomainSerializer(data={"domain": domain, "reason": "Operator bootstrap"})
        if not domain_input.is_valid():
            # Existing exact domains are validated below without inserting duplicates.
            if not AllowedDomain.objects.filter(domain=domain).exists():
                raise CommandError("Invalid bootstrap domain.")
        identity_lock()
        admins = User.objects.filter(role=User.Role.ADMIN)
        if admins.exists():
            user = admins.filter(email__iexact=email).first()
            if user is None:
                self.stdout.write("Administrator already exists; no account changed.")
                return
            if not user.is_active:
                raise CommandError("Bootstrap will not reactivate a disabled administrator.")
            if trust and user.email_verified_at is None:
                # Only an operator-created, never-activated initial administrator qualifies.
                if (
                    user.mfa_enabled
                    or not IdentityEvent.objects.filter(
                        action="bootstrap.admin_created", subject_id=str(user.pk)
                    ).exists()
                ):
                    raise CommandError("Existing account requires authenticated verification.")
                if not AllowedDomain.objects.filter(domain=domain, is_active=True).exists():
                    raise CommandError("Bootstrap will not reactivate a disabled domain.")
                user.email_verified_at = timezone.now()
                user.session_version += 1
                user.save(update_fields=["email_verified_at", "session_version"])
                IdentityToken.objects.filter(user=user, used_at=None).update(used_at=timezone.now())
                audit(
                    None,
                    "bootstrap.email_trusted",
                    user.pk,
                    {"actor": "operator", "source": "environment"},
                )
            self.stdout.write("Administrator retained; password and MFA unchanged.")
            return
        if User.objects.filter(email__iexact=email).exists():
            raise CommandError("Bootstrap will not promote an existing account.")
        password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "")
        if not password:
            raise CommandError("Set BOOTSTRAP_ADMIN_PASSWORD for the first creation.")
        user = User(
            username=uuid.uuid4().hex,
            email=email,
            role=User.Role.ADMIN,
            first_name=os.environ.get("BOOTSTRAP_ADMIN_NAME", "Administrador")[:150],
        )
        try:
            user.password = password_hash(password, user)
        except Exception as exc:
            from rest_framework.exceptions import ValidationError

            if isinstance(exc, ValidationError):
                raise CommandError("Bootstrap password does not meet password policy.") from None
            raise
        allowed, _ = AllowedDomain.objects.get_or_create(domain=domain)
        if not allowed.is_active:
            raise CommandError("Bootstrap will not reactivate a disabled domain.")
        if trust:
            user.email_verified_at = timezone.now()
        user.save()
        audit(
            None,
            "bootstrap.admin_created",
            user.pk,
            {"actor": "operator", "source": "environment", "trusted_email": trust},
        )
        if not trust:
            issue_token(user, "verify")
        self.stdout.write("Initial administrator provisioned. MFA remains required.")
