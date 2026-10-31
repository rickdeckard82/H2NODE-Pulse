from rest_framework import serializers

from core.identity import normalize_email
from core.models import AllowedDomain, Department, Membership, SupportGroup, User


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


class RegisterInput(LoginInput):
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
        user, group = attrs["user"], attrs["group"]
        if attrs.get("can_cancel") and user.role != User.Role.MANAGER:
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
