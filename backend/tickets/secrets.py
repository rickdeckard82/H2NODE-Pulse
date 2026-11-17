"""Passwords typed into tickets are stored encrypted, apart from the visible text.

The text keeps a placeholder (`[[oculta:<id>]]`); the value is only returned by `RevealView`
after the viewer confirms their own account password. Notifications, exports and search
only ever see the placeholder.
"""

import re
import uuid

from django.contrib.auth.hashers import check_password
from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core import identity
from core.identity_views import NoStoreMixin
from core.serializers import StrictSerializer
from tickets.models import HiddenSecret
from tickets.permissions import can_read_internal, visible_tickets

TOKEN = re.compile(r"\[\[oculta:([0-9a-f-]{36})\]\]")
# "senha: valor", "senha=valor", "password: valor". The value is the next word.
PATTERN = re.compile(r"(?i)\b(senha|password|passwd)(\s*[:=]\s*)(\S+)")


def redact(text):
    """Return (text with placeholders, [(secret id, plaintext)])."""
    found = []
    # A user cannot forge placeholders that point to someone else's secret.
    text = text.replace("[[oculta:", "[ oculta:")

    def hide(match):
        secret_id = uuid.uuid4()
        found.append((secret_id, match.group(3)))
        return f"{match.group(1)}{match.group(2)}[[oculta:{secret_id}]]"

    return PATTERN.sub(hide, text), found


def store(ticket, found, comment=None):
    cipher = identity.cipher()
    HiddenSecret.objects.bulk_create(
        HiddenSecret(
            id=secret_id,
            ticket=ticket,
            comment=comment,
            ciphertext=cipher.encrypt(value.encode()).decode(),
        )
        for secret_id, value in found
    )


class RevealInput(StrictSerializer):
    password = serializers.CharField(max_length=256, trim_whitespace=False, write_only=True)


class RevealOutput(serializers.Serializer):
    value = serializers.CharField()


class RevealView(NoStoreMixin, APIView):
    @extend_schema(request=RevealInput, responses=RevealOutput)
    def post(self, request, ticket_id, secret_id):
        serializer = RevealInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket = get_object_or_404(visible_tickets(request.user), uuid=ticket_id)
        secret = get_object_or_404(
            HiddenSecret.objects.select_related("comment"), pk=secret_id, ticket=ticket
        )
        if (
            secret.comment_id
            and secret.comment.visibility == "internal"
            and not can_read_internal(request.user, ticket)
        ):
            get_object_or_404(HiddenSecret.objects.none())
        identity.rate_limit("secret-reveal", request.user.pk, limit=20)
        if not check_password(serializer.validated_data["password"], request.user.password):
            raise ValidationError("Senha incorreta.")
        with transaction.atomic():
            identity.audit(
                request.user, "ticket.secret_revealed", ticket.uuid, {"secret": str(secret.pk)}
            )
        value = identity.cipher().decrypt(secret.ciphertext.encode()).decode()
        return Response({"value": value})
