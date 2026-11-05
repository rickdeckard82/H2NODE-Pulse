"""Company using this installation: identification for administrators, name and logo for all."""

import base64
import binascii
import re

from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.authentication import IsIdentityAdmin
from core.identity import audit, identity_lock
from core.identity_views import NoStoreMixin, locked_actor
from core.models import CompanyProfile, User
from core.serializers import StrictSerializer

LOGO_MAX_BYTES = 256 * 1024
LOGO_PREFIX = "data:image/png;base64,"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def valid_cnpj(value):
    """Check digits of numeric and alphanumeric CNPJ: each character counts as ASCII minus 48."""
    if not re.fullmatch(r"[0-9A-Z]{12}[0-9]{2}", value) or len(set(value)) == 1:
        return False
    numbers = [ord(character) - 48 for character in value]
    for size in (12, 13):
        weights = [*range(size - 7, 1, -1), *range(9, 1, -1)]
        remainder = sum(n * w for n, w in zip(numbers[:size], weights, strict=True)) % 11
        if numbers[size] != (0 if remainder < 2 else 11 - remainder):
            return False
    return True


class CompanyInput(StrictSerializer):
    name = serializers.CharField(max_length=120)
    cnpj = serializers.CharField(max_length=18)
    responsible = serializers.CharField(max_length=120)
    logo = serializers.CharField(
        max_length=LOGO_MAX_BYTES * 2, required=False, allow_blank=True, trim_whitespace=False
    )
    reason = serializers.CharField(max_length=300)

    def validate_cnpj(self, value):
        cnpj = re.sub(r"[./\-\s]", "", value).upper()
        if not valid_cnpj(cnpj):
            raise serializers.ValidationError("Informe um CNPJ válido.")
        return cnpj

    def validate_logo(self, value):
        if not value:
            return value
        try:
            raw = base64.b64decode(value.removeprefix(LOGO_PREFIX), validate=True)
        except binascii.Error:
            raw = b""
        # The signature keeps SVG, which can carry scripts, out of a value rendered to every user.
        if (
            not value.startswith(LOGO_PREFIX)
            or not raw.startswith(PNG_SIGNATURE)
            or len(raw) > LOGO_MAX_BYTES
        ):
            raise serializers.ValidationError("Envie uma imagem PNG de até 256 KB.")
        return value


class CompanyOutput(serializers.ModelSerializer):
    class Meta:
        model = CompanyProfile
        fields = ["name", "cnpj", "responsible", "logo", "updated_at"]


class CompanySettingsView(NoStoreMixin, APIView):
    def get_permissions(self):
        return [IsIdentityAdmin() if self.request.method == "PATCH" else IsAuthenticated()]

    @extend_schema(responses=CompanyOutput)
    def get(self, request):
        data = CompanyOutput(CompanyProfile.objects.first() or CompanyProfile()).data
        # Everyone sees the top bar; the identification stays with administrators.
        if request.user.role != User.Role.ADMIN:
            data["cnpj"] = data["responsible"] = ""
        return Response(data)

    @extend_schema(request=CompanyInput, responses=CompanyOutput)
    @transaction.atomic
    def patch(self, request):
        identity_lock()
        actor = locked_actor(request, admin=True)
        serializer = CompanyInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        reason = data.pop("reason")
        obj = CompanyProfile.objects.select_for_update().first() or CompanyProfile()
        logo_changed = "logo" in data and data["logo"] != obj.logo
        for field, value in data.items():
            setattr(obj, field, value)
        obj.save()
        audit(
            actor,
            "company.updated",
            obj.pk,
            {
                "reason": reason,
                "name": obj.name,
                "cnpj": obj.cnpj,
                "responsible": obj.responsible,
                "logo_changed": logo_changed,
            },
        )
        return Response(CompanyOutput(obj).data)
