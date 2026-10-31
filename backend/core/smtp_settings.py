"""Administrator-only SMTP configuration. Never serialize credentials or SMTP errors."""

import ipaddress
import re
import socket

from django.conf import settings
from django.core.mail import get_connection
from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.authentication import IsIdentityAdmin
from core.identity import audit, cipher, identity_lock
from core.identity_views import NoStoreMixin, locked_actor
from core.models import SmtpConfiguration
from core.serializers import StrictSerializer


def validate_host(host):
    if not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?", host):
        raise ValidationError({"host": "Informe somente o nome DNS do servidor SMTP."})
    host = host.lower()
    if any(
        not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
        for label in host.split(".")
    ):
        raise ValidationError({"host": "Nome DNS inválido."})
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValidationError({"host": "Destino SMTP não permitido."})
    allowed = settings.SMTP_ALLOWED_HOSTS
    if allowed and host not in allowed:
        raise ValidationError({"host": "Servidor fora da lista SMTP permitida pelo operador."})
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host
    if not address.is_global:
        raise ValidationError({"host": "Use o nome DNS do servidor SMTP autorizado."})
    return host


def check_destination(host, port):
    """Recheck DNS on delivery; block local/metadata/multicast destinations."""
    validate_host(host)
    if port not in {25, 465, 587, 2525}:
        raise OSError("Disallowed SMTP port")
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    for row in addresses:
        address = ipaddress.ip_address(row[4][0])
        if (
            address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_unspecified
            or address.is_reserved
        ):
            raise OSError("Disallowed SMTP destination")


class SmtpInput(StrictSerializer):
    enabled = serializers.BooleanField(required=False)
    host = serializers.CharField(max_length=253, required=False, allow_blank=True)
    port = serializers.ChoiceField(choices=[25, 465, 587, 2525], required=False)
    security = serializers.ChoiceField(choices=["starttls", "ssl"], required=False)
    username = serializers.CharField(max_length=254, required=False, allow_blank=True)
    password = serializers.CharField(
        max_length=1024, required=False, allow_blank=True, trim_whitespace=False, write_only=True
    )
    clear_password = serializers.BooleanField(required=False, default=False, write_only=True)
    from_email = serializers.EmailField(required=False, allow_blank=True)
    reason = serializers.CharField(max_length=300)


class SmtpOutput(serializers.ModelSerializer):
    updated_at = serializers.DateTimeField(read_only=True, allow_null=True)
    password_configured = serializers.SerializerMethodField()
    source = serializers.SerializerMethodField()

    def get_password_configured(self, obj) -> bool:
        return bool(obj.encrypted_password)

    def get_source(self, obj) -> str:
        return "database" if obj.updated_at else "environment"

    class Meta:
        model = SmtpConfiguration
        fields = [
            "enabled",
            "host",
            "port",
            "security",
            "username",
            "from_email",
            "password_configured",
            "updated_at",
            "source",
        ]


class SmtpSettingsView(NoStoreMixin, APIView):
    permission_classes = [IsIdentityAdmin]

    @extend_schema(responses=SmtpOutput)
    def get(self, request):
        obj = SmtpConfiguration.objects.first() or SmtpConfiguration()
        return Response(SmtpOutput(obj).data)

    @extend_schema(request=SmtpInput, responses=SmtpOutput)
    @transaction.atomic
    def patch(self, request):
        identity_lock()
        actor = locked_actor(request, admin=True)
        serializer = SmtpInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        reason = data.pop("reason")
        password = data.pop("password", "")
        clear = data.pop("clear_password", False)
        if password and clear:
            raise ValidationError("Não combine troca e remoção da senha.")
        obj = SmtpConfiguration.objects.select_for_update().first() or SmtpConfiguration()
        for field, value in data.items():
            setattr(obj, field, value)
        if obj.host:
            obj.host = validate_host(obj.host.strip())
        if password:
            obj.encrypted_password = cipher().encrypt(password.encode()).decode()
        elif clear:
            obj.encrypted_password = ""
        if obj.enabled and (not obj.host or not obj.from_email):
            raise ValidationError("Servidor e remetente são obrigatórios para ativar envios.")
        if obj.enabled and bool(obj.username) != bool(obj.encrypted_password):
            raise ValidationError(
                "Informe usuário e senha juntos, ou deixe ambos vazios para relay autorizado."
            )
        obj.save()
        audit(
            actor,
            "smtp.updated",
            obj.pk,
            {
                "reason": reason,
                "fields": sorted(data),
                "password_changed": bool(password or clear),
                "enabled": obj.enabled,
            },
        )
        return Response(SmtpOutput(obj).data)


def delivery_configuration():
    obj = SmtpConfiguration.objects.first()
    if obj is None:
        # Preserve the existing, operator-controlled environment adapter and its tests.
        if not settings.EMAIL_HOST or not settings.DEFAULT_FROM_EMAIL:
            return None
        return settings.DEFAULT_FROM_EMAIL, None
    if not obj.enabled:
        return None
    check_destination(obj.host, obj.port)
    return obj.from_email, get_connection(
        backend="django.core.mail.backends.smtp.EmailBackend",
        host=obj.host,
        port=obj.port,
        username=obj.username,
        password=cipher().decrypt(obj.encrypted_password.encode()).decode()
        if obj.encrypted_password
        else "",
        use_tls=obj.security == "starttls",
        use_ssl=obj.security == "ssl",
        timeout=10,
    )
