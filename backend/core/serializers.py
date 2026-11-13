import base64
import binascii

from rest_framework import serializers

from core.identity import normalize_email
from core.models import AllowedDomain, Department, Membership, SupportGroup, User

AVATAR_MAX_BYTES = 100 * 1024


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise serializers.ValidationError({"non_field_errors": ["Campos não permitidos."]})
        return super().to_internal_value(data)


class EmailInput(StrictSerializer):
    email = serializers.EmailField(max_length=254)

    def validate_email(self, value):
        return normalize_email(value)


class LoginInput(EmailInput):
    password = serializers.CharField(max_length=256, trim_whitespace=False, write_only=True)


class RegisterInput(EmailInput):
    name = serializers.CharField(max_length=150)


class TokenInput(StrictSerializer):
    token = serializers.CharField(max_length=128, write_only=True)


class ResetInput(TokenInput):
    password = serializers.CharField(max_length=256, trim_whitespace=False, write_only=True)


class CodeInput(StrictSerializer):
    code = serializers.CharField(max_length=64, write_only=True)


class MfaVerifyInput(CodeInput):
    remember_device = serializers.BooleanField(required=False, default=False)


class PasswordInput(StrictSerializer):
    password = serializers.CharField(max_length=256, trim_whitespace=False, write_only=True)


class MfaDisableInput(PasswordInput, CodeInput):
    pass


class PasswordChangeInput(StrictSerializer):
    current_password = serializers.CharField(max_length=256, trim_whitespace=False, write_only=True)
    new_password = serializers.CharField(max_length=256, trim_whitespace=False, write_only=True)


class IdentityResult(serializers.Serializer):
    status = serializers.CharField(required=False)
    detail = serializers.CharField(required=False)
    errors = serializers.JSONField(required=False)
    csrfToken = serializers.CharField(required=False)
    secret = serializers.CharField(required=False)
    uri = serializers.CharField(required=False)
    recovery_codes = serializers.ListField(child=serializers.CharField(), required=False)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "first_name", "role", "department", "is_active", "mfa_enabled"]
        read_only_fields = fields


class ProfileSerializer(UserSerializer):
    class Meta(UserSerializer.Meta):
        fields = [*UserSerializer.Meta.fields, "avatar"]
        read_only_fields = fields


class ProfileInput(StrictSerializer):
    """E-mail is deliberately absent: it identifies the corporate account and cannot change."""

    first_name = serializers.CharField(max_length=150, required=False)
    avatar = serializers.CharField(
        max_length=AVATAR_MAX_BYTES * 4 // 3 + 64, required=False, allow_blank=True
    )

    def validate_avatar(self, value):
        if not value:
            return value
        prefix = "data:image/jpeg;base64,"
        try:
            raw = base64.b64decode(value.removeprefix(prefix), validate=True)
        except binascii.Error:
            raw = b""
        # The browser re-encodes the photo to JPEG, which also drops EXIF metadata.
        if (
            not value.startswith(prefix)
            or not raw.startswith(b"\xff\xd8\xff")
            or len(raw) > AVATAR_MAX_BYTES
        ):
            raise serializers.ValidationError("Envie uma imagem JPEG de até 100 KB.")
        return value


class ReasonInput(StrictSerializer):
    reason = serializers.CharField(max_length=300)


class UserCreateInput(EmailInput):
    first_name = serializers.CharField(max_length=150)
    department = serializers.PrimaryKeyRelatedField(
        queryset=Department.objects.filter(is_active=True), allow_null=True, required=False
    )
    reason = serializers.CharField(max_length=300)


class UserUpdateInput(StrictSerializer):
    role = serializers.ChoiceField(choices=User.Role, required=False)
    is_active = serializers.BooleanField(required=False)
    department = serializers.PrimaryKeyRelatedField(
        queryset=Department.objects.filter(is_active=True),
        allow_null=True,
        required=False,
    )
    reason = serializers.CharField(max_length=300)


class OrganizationSerializer(serializers.ModelSerializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) - {"name", "is_active"}:
            raise serializers.ValidationError({"non_field_errors": ["Campos não permitidos."]})
        return super().to_internal_value(data)

    class Meta:
        model = Department
        fields = ["id", "name", "is_active"]
        read_only_fields = ["id"]


class GroupSerializer(OrganizationSerializer):
    class Meta(OrganizationSerializer.Meta):
        model = SupportGroup


class DomainSerializer(serializers.ModelSerializer):
    reason = serializers.CharField(write_only=True, max_length=300)

    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) - {"domain", "is_active", "reason"}:
            raise serializers.ValidationError({"non_field_errors": ["Campos não permitidos."]})
        return super().to_internal_value(data)

    def validate_domain(self, value):
        value = value.strip().lower()
        # Domain fields accept exact ASCII/IDNA names, never wildcards, URLs or suffix matching.
        import re

        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", value) or "." not in value:
            raise serializers.ValidationError("Informe um domínio exato.")
        if any(
            not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
            for label in value.split(".")
        ):
            raise serializers.ValidationError("Domínio inválido.")
        if self.instance and value != self.instance.domain:
            raise serializers.ValidationError("Desative o domínio antigo e cadastre o novo.")
        return value

    class Meta:
        model = AllowedDomain
        fields = ["id", "domain", "is_active", "reason"]
        read_only_fields = ["id"]


class MembershipSerializer(serializers.ModelSerializer):
    class Meta:
        model = Membership
        fields = ["id", "user", "group", "can_view_restricted", "can_transfer", "can_cancel"]
        read_only_fields = ["id"]

    def validate(self, attrs):
        current = self.instance
        user = attrs.get("user", current.user if current else None)
        group = attrs.get("group", current.group if current else None)
        if user is None or group is None:
            raise serializers.ValidationError("Usuário e grupo são obrigatórios.")
        if "can_cancel" not in attrs and current:
            attrs_can_cancel = current.can_cancel
        else:
            attrs_can_cancel = attrs.get("can_cancel")
        if attrs_can_cancel and user.role != User.Role.MANAGER:
            raise serializers.ValidationError("Cancelamento de gestão exige papel de gestor.")
        if (
            user.role not in {User.Role.TECHNICIAN, User.Role.MANAGER}
            or not user.is_active
            or not user.email_verified_at
            or not group.is_active
        ):
            raise serializers.ValidationError(
                "Grupo ativo e técnico/gestor confirmado são obrigatórios."
            )
        return attrs
