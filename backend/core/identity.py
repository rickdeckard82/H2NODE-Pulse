"""Identity operations. All state-changing account operations share a PostgreSQL lock.

This deliberately coarse lock serializes rare administrative writes and token redemption.
Login/MFA additionally lock the user row. No secrets enter audit records.
"""

import hashlib
import hmac
import secrets
import time
import uuid
from datetime import timedelta
from functools import cache

import pyotp
from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection, transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, Throttled, ValidationError

from core.models import (
    AllowedDomain,
    AuthRateBucket,
    IdentityEvent,
    IdentityMail,
    IdentityToken,
    TrustedDevice,
    User,
)


def cipher():
    return Fernet(settings.IDENTITY_KEY.encode())


@cache
def dummy_password_hash():
    return make_password(secrets.token_urlsafe(32))


def digest(value):
    return hmac.new(settings.SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()


def identity_lock():
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(721984021)")


def normalize_email(value):
    return value.strip().lower()


def domain_allowed(email):
    return AllowedDomain.objects.filter(domain=email.rsplit("@", 1)[-1], is_active=True).exists()


def eligible(user):
    return bool(user and user.is_active and user.email_verified_at and domain_allowed(user.email))


def audit(actor, action, subject, changes=None):
    IdentityEvent.objects.create(
        actor=actor, action=action, subject_id=str(subject), changes=changes or {}
    )


def password_hash(password, user=None):
    try:
        validate_password(password, user)
    except DjangoValidationError as exc:
        raise ValidationError({"password": exc.messages}) from None
    return make_password(password)


def rate_limit(scope, identity, limit=10):
    # Keys are HMACs; raw e-mail/IP never enters this short-lived table.
    key = digest(f"{scope}:{identity}")
    window = int(time.time()) // 900
    with transaction.atomic():
        bucket, _ = AuthRateBucket.objects.get_or_create(key=key, defaults={"window": window})
        bucket = AuthRateBucket.objects.select_for_update().get(pk=bucket.pk)
        if bucket.window != window:
            bucket.window, bucket.count = window, 0
        if bucket.count >= limit:
            raise Throttled(wait=900 - int(time.time()) % 900)
        bucket.count += 1
        bucket.save()


INVITE_VALIDITY = timedelta(hours=72)


def issue_token(user, purpose, email=None):
    raw = secrets.token_urlsafe(32)
    now = timezone.now()
    IdentityToken.objects.filter(user=user, purpose=purpose, used_at=None).update(used_at=now)
    token = IdentityToken.objects.create(
        digest=digest(raw),
        user=user,
        purpose=purpose,
        email=email or user.email,
        version=user.session_version,
        expires_at=now + INVITE_VALIDITY if purpose == "invite" else now + timedelta(minutes=30),
    )
    # Asynchronous delivery avoids disclosing mailbox existence through SMTP latency.
    # Only this encrypted, expiring queue can recover the token for delivery.
    IdentityMail.objects.create(
        token=token,
        encrypted_body=cipher().encrypt(raw.encode()).decode(),
        next_attempt_at=now,
    )


@transaction.atomic
def register(data):
    identity_lock()
    email = normalize_email(data["email"])
    hashed = password_hash(data["password"], User(email=email, first_name=data["name"]))
    existing = User.objects.filter(email__iexact=email).first()
    if not domain_allowed(email) or existing:
        # Same generic answer either way; repeating sign-up only resends a pending confirmation.
        if (
            existing
            and domain_allowed(email)
            and existing.is_active
            and not existing.email_verified_at
        ):
            issue_token(existing, "verify")
        return
    user = User.objects.create(
        username=uuid.uuid4().hex,
        email=email,
        first_name=data["name"],
        password=hashed,
    )
    issue_token(user, "verify")
    audit(user, "account.registered", user.pk)


@transaction.atomic
def request_token(email, purpose):
    identity_lock()
    user = User.objects.filter(email=normalize_email(email), is_active=True).first()
    if user and domain_allowed(user.email):
        if purpose == "verify" and not user.email_verified_at:
            issue_token(user, purpose)
        elif purpose == "reset" and user.email_verified_at:
            issue_token(user, purpose)
        elif purpose == "reset" and not user.has_usable_password():
            # Account created by an administrator that never set a password: resend the invite.
            issue_token(user, "invite")


@transaction.atomic
def redeem_token(raw, purpose, password=None):
    identity_lock()
    token = (
        IdentityToken.objects.select_for_update()
        .filter(
            digest=digest(raw), purpose__in=["reset", "invite"] if purpose == "reset" else [purpose]
        )
        .first()
    )
    now = timezone.now()
    if not token or token.used_at or token.expires_at <= now:
        raise ValidationError("Código inválido ou expirado. Solicite um novo código.")
    user = User.objects.select_for_update().get(pk=token.user_id)
    if (
        not user.is_active
        or token.version != user.session_version
        or not domain_allowed(token.email)
        or not domain_allowed(user.email)
    ):
        raise ValidationError("Código inválido ou expirado. Solicite um novo código.")
    if purpose == "reset":
        user.password = password_hash(password, user)
        if token.purpose == "invite":
            # Redeeming the mailed invite proves possession of the address.
            user.email_verified_at = now
    else:
        user.email_verified_at = now
    user.session_version += 1
    user.save()
    token.used_at = now
    token.save(update_fields=["used_at"])
    audit(user, f"account.{token.purpose}", user.pk)


def start_session(request, user, fresh_mfa=True):
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.session["identity_version"] = user.session_version
    request.session["mfa_verified"] = user.mfa_enabled
    if user.mfa_enabled:
        request.session["mfa_at"] = time.time() if fresh_mfa else 0
    request.session.set_expiry(8 * 60 * 60)


@transaction.atomic
def password_login(request, email, password):
    dummy = dummy_password_hash()
    user = User.objects.select_for_update().filter(email=normalize_email(email)).first()
    # Perform the same password hashing work for unknown and known accounts.
    valid = check_password(password, user.password) if user else check_password(password, dummy)
    if not valid or not eligible(user):
        raise PermissionDenied("Credenciais inválidas ou conta indisponível.")
    request.session.flush()
    if user.mfa_enabled:
        from core.trusted_devices import consume

        expiry = consume(request, user)
        if expiry:
            start_session(request, user, fresh_mfa=False)
            request.session.set_expiry(
                min(8 * 60 * 60, max(1, int((expiry - timezone.now()).total_seconds())))
            )
            audit(user, "session.login_trusted_device", user.pk)
            return {"status": "authenticated"}
        request.session["pending_identity"] = {
            "id": user.pk,
            "version": user.session_version,
            "at": time.time(),
        }
        request.session.set_expiry(300)
        return {"status": "mfa_required"}
    start_session(request, user)
    audit(user, "session.login", user.pk)
    return {"status": "authenticated"}


def login_failed(email=None, user_id=None):
    """Called outside the login transaction, whose rollback would erase this record."""
    lookup = {"pk": user_id} if user_id else {"email": normalize_email(email)}
    user = User.objects.filter(**lookup).first()
    # An unknown address is not stored: people sometimes type a password in that field.
    audit(user, "session.login_failed", user.pk if user else "unknown")


def pending_user(request):
    pending = request.session.get("pending_identity", {})
    user = User.objects.select_for_update().filter(pk=pending.get("id")).first()
    if (
        not eligible(user)
        or pending.get("version") != user.session_version
        or time.time() - pending.get("at", 0) > 300
    ):
        raise PermissionDenied("Reinicie o login.")
    return user


def check_factor(user, code):
    """Accepts a fresh TOTP or spends a recovery code; the caller saves the user."""
    totp = pyotp.TOTP(cipher().decrypt(user.mfa_secret.encode()).decode())
    counter = int(time.time()) // 30
    matched = next(
        (
            n
            for n in range(counter - 1, counter + 2)
            if n > user.mfa_last_counter and totp.verify(code, for_time=n * 30)
        ),
        None,
    )
    recovery = digest(code)
    if matched is not None:
        user.mfa_last_counter = matched
    elif recovery in user.recovery_hashes:
        user.recovery_hashes.remove(recovery)
        audit(user, "mfa.recovery_used", user.pk)
    else:
        raise PermissionDenied("Código inválido ou já utilizado.")


@transaction.atomic
def verify_mfa(request, code, remember_device=False):
    user = pending_user(request)
    check_factor(user, code)
    user.save()
    request.session.flush()
    start_session(request, user)
    if remember_device:
        from core.trusted_devices import issue

        issue(request, user)
        audit(user, "device.remembered", user.pk, {"days": 30})
    audit(user, "session.login_mfa", user.pk)
    return {"status": "authenticated"}


def clear_mfa(user):
    """Caller holds the user lock. Ends every session, as other MFA changes do."""
    user.mfa_enabled, user.mfa_secret = False, ""
    user.mfa_last_counter, user.recovery_hashes = -1, []
    user.session_version += 1
    user.save(
        update_fields=[
            "mfa_enabled",
            "mfa_secret",
            "mfa_last_counter",
            "recovery_hashes",
            "session_version",
        ]
    )
    TrustedDevice.objects.filter(user=user).delete()


def recovery_codes(user):
    codes = [secrets.token_hex(10) for _ in range(8)]
    user.recovery_hashes = [digest(value) for value in codes]
    return codes
