"""Cloudflare Turnstile server-side verification (fail closed when enabled)."""

import json
import logging
import urllib.parse
import urllib.request

from django.conf import settings
from rest_framework.exceptions import ValidationError

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
logger = logging.getLogger(__name__)


def verify(token, remote_ip=None):
    if not settings.TURNSTILE_ENABLED:
        return
    error = ValidationError({"detail": "Verificação de segurança inválida. Tente novamente."})
    if not isinstance(token, str) or not token or len(token) > 2048:
        raise error
    payload = {"secret": settings.TURNSTILE_SECRET_KEY, "response": token}
    if remote_ip:
        payload["remoteip"] = remote_ip
    request = urllib.request.Request(
        VERIFY_URL, urllib.parse.urlencode(payload).encode(), method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
            ok = json.load(response).get("success") is True
    except Exception:  # network/parse failure must not let requests through
        logger.warning("Turnstile verification unavailable")
        ok = False
    if not ok:
        raise error
