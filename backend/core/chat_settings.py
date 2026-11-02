"""Administrator-only Google Chat space webhook configuration."""

import re
from urllib.parse import parse_qs, urlsplit

from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.authentication import IsIdentityAdmin
from core.identity import audit, cipher, identity_lock
from core.identity_views import NoStoreMixin, locked_actor
from core.models import ChatConfiguration
from core.serializers import StrictSerializer


def validate_webhook(value):
    parsed = urlsplit(value)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "chat.googleapis.com"
        or parsed.port not in {None, 443}
        or parsed.username
        or parsed.password
        or not re.fullmatch(r"/v1/spaces/[A-Za-z0-9_-]+/messages", parsed.path)
        or set(query) != {"key", "token"}
        or any(len(values) != 1 or not values[0] for values in query.values())
        or parsed.fragment
    ):
        raise ValidationError({"webhook": "Informe um webhook válido de espaço do Google Chat."})
    return value


class ChatInput(StrictSerializer):
    enabled = serializers.BooleanField(required=False)
    webhook = serializers.CharField(
        max_length=2048, required=False, allow_blank=True, trim_whitespace=False, write_only=True
    )
    clear_webhook = serializers.BooleanField(required=False, default=False, write_only=True)
    reason = serializers.CharField(max_length=300)


class ChatOutput(serializers.ModelSerializer):
    webhook_configured = serializers.SerializerMethodField()

    def get_webhook_configured(self, obj) -> bool:
        return bool(obj.encrypted_webhook)

    class Meta:
        model = ChatConfiguration
        fields = ["enabled", "webhook_configured", "updated_at"]


class ChatSettingsView(NoStoreMixin, APIView):
    permission_classes = [IsIdentityAdmin]

    @extend_schema(responses=ChatOutput)
    def get(self, request):
        return Response(ChatOutput(ChatConfiguration.objects.first() or ChatConfiguration()).data)

    @extend_schema(request=ChatInput, responses=ChatOutput)
    @transaction.atomic
    def patch(self, request):
        identity_lock()
        actor = locked_actor(request, admin=True)
        serializer = ChatInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        obj = ChatConfiguration.objects.select_for_update().first() or ChatConfiguration()
        webhook = data.get("webhook", "")
        clear = data.get("clear_webhook", False)
        if webhook and clear:
            raise ValidationError("Não combine troca e remoção do webhook.")
        if webhook:
            obj.encrypted_webhook = cipher().encrypt(validate_webhook(webhook).encode()).decode()
        elif clear:
            obj.encrypted_webhook = ""
        if "enabled" in data:
            obj.enabled = data["enabled"]
        if obj.enabled and not obj.encrypted_webhook:
            raise ValidationError("Cadastre o webhook antes de ativar o Google Chat.")
        obj.save()
        audit(
            actor,
            "chat.updated",
            obj.pk,
            {
                "reason": data["reason"],
                "enabled": obj.enabled,
                "webhook_changed": bool(webhook or clear),
            },
        )
        return Response(ChatOutput(obj).data)


def active_webhook():
    obj = ChatConfiguration.objects.filter(enabled=True).first()
    if not obj or not obj.encrypted_webhook:
        return None
    return validate_webhook(cipher().decrypt(obj.encrypted_webhook.encode()).decode())
