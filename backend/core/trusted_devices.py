"""Opt-in browser trust after MFA; password is still required on every login."""

import secrets
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from core.models import TrustedDevice

COOKIE = "pulse_trusted_device"
COOKIE_PATH = "/api/v1/auth/"
DAYS = 30


def token_digest(request):
    from core.identity import digest

    raw = request.COOKIES.get(COOKIE, "")
    return digest(raw) if 32 <= len(raw) <= 128 else ""


def credential_stamp(user):
    from core.identity import digest

    return digest(f"device:{user.password}:{user.mfa_secret}:{user.role}")


def issue(request, user, expires_at=None, created_at=None):
    """Caller holds the user lock and transaction. Never return the raw token as JSON."""
    from core.identity import digest

    TrustedDevice.objects.filter(digest=token_digest(request), user=user).delete()
    raw = secrets.token_urlsafe(32)
    now = timezone.now()
    expires_at = expires_at or now + timedelta(days=DAYS)
    TrustedDevice.objects.create(
        digest=digest(raw),
        user=user,
        version=user.session_version,
        credential_stamp=credential_stamp(user),
        created_at=created_at or now,
        expires_at=expires_at,
    )
    request._trusted_device_cookie = (raw, expires_at)


def consume(request, user):
    row = TrustedDevice.objects.filter(
        digest=token_digest(request),
        user=user,
        version=user.session_version,
        credential_stamp=credential_stamp(user),
        expires_at__gt=timezone.now(),
    ).first()
    if row is None or not user.mfa_enabled:
        if request.COOKIES.get(COOKIE):
            request._forget_device_cookie = True
        return None
    expiry = row.expires_at
    # Rotate on use, preserving the original 30-day deadline (not a sliding window).
    issue(request, user, expiry, row.created_at)
    return expiry


def forget(request, user):
    TrustedDevice.objects.filter(digest=token_digest(request), user=user).delete()
    request._forget_device_cookie = True


def apply_cookie(request, response):
    if getattr(request, "_forget_device_cookie", False):
        response.delete_cookie(COOKIE, path=COOKIE_PATH, samesite="Strict")
    value = getattr(request, "_trusted_device_cookie", None)
    if value:
        raw, expires_at = value
        response.set_cookie(
            COOKIE,
            raw,
            max_age=max(1, int((expires_at - timezone.now()).total_seconds())),
            httponly=True,
            secure=settings.SESSION_COOKIE_SECURE,
            samesite="Strict",
            path=COOKIE_PATH,
        )
    return response
