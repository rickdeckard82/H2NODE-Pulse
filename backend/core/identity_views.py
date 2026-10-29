import time

import pyotp
from django.conf import settings
from django.contrib.auth import logout
from django.db import transaction
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import extend_schema
from rest_framework import generics, mixins, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from core import identity
from core.authentication import IsIdentityAdmin
from core.models import AllowedDomain, Department, Membership, SupportGroup, User
from core.serializers import (
    CodeInput,
    DomainSerializer,
    EmailInput,
    GroupSerializer,
    IdentityResult,
    LoginInput,
    MembershipSerializer,
    OrganizationSerializer,
    PasswordInput,
    RegisterInput,
    ResetInput,
    StrictSerializer,
    TokenInput,
    UserSerializer,
    UserUpdateInput,
)


class NoStoreMixin:
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response


class CsrfView(NoStoreMixin, generics.GenericAPIView):
    permission_classes = [AllowAny]
    serializer_class = IdentityResult

    @extend_schema(responses=IdentityResult, auth=[])
    def get(self, request):
        return Response({"csrfToken": get_token(request)})


@method_decorator(csrf_protect, name="dispatch")
class AuthActionView(NoStoreMixin, generics.GenericAPIView):
    permission_classes = [AllowAny]
    serializer_class = StrictSerializer
    action = ""

    @extend_schema(
        responses={
            200: IdentityResult,
            400: IdentityResult,
            403: IdentityResult,
            429: IdentityResult,
        }
    )
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        # REMOTE_ADDR is deliberately used until the trusted proxy chain is homologated.
        identity.rate_limit("source", request.META.get("REMOTE_ADDR", "unknown"), 500)
        key = data.get("email") or str(request.session.get("pending_identity", {}).get("id", ""))
        if not key:
            key = request.session.session_key or request.META.get("REMOTE_ADDR", "unknown")
        identity.rate_limit(self.action, key, settings.IDENTITY_RATE_LIMIT)
        result = {"detail": "Se os dados forem elegíveis, enviaremos um código por e-mail."}
        if self.action == "register":
            identity.register(data)
        elif self.action in {"resend", "forgot"}:
            identity.request_token(data["email"], "verify" if self.action == "resend" else "reset")
        elif self.action in {"confirm", "reset", "confirm_email"}:
            purpose = {"confirm": "verify", "reset": "reset", "confirm_email": "email"}[self.action]
            identity.redeem_token(data["token"], purpose, data.get("password"))
            result = {"status": "completed"}
        elif self.action == "login":
            result = identity.password_login(request, **data)
        elif self.action == "mfa_setup":
            result = identity.setup_mfa(request)
        elif self.action == "mfa_verify":
            result = identity.verify_mfa(request, data["code"])
        return Response(result)


class RegisterView(AuthActionView):
    action, serializer_class = "register", RegisterInput


class ResendView(AuthActionView):
    action, serializer_class = "resend", EmailInput


class ForgotView(AuthActionView):
    action, serializer_class = "forgot", EmailInput


class ConfirmView(AuthActionView):
    action, serializer_class = "confirm", TokenInput


class ResetView(AuthActionView):
    action, serializer_class = "reset", ResetInput


class ConfirmEmailView(AuthActionView):
    action, serializer_class = "confirm_email", TokenInput


class LoginView(AuthActionView):
    action, serializer_class = "login", LoginInput


class MfaSetupView(AuthActionView):
    action = "mfa_setup"


class MfaVerifyView(AuthActionView):
    action, serializer_class = "mfa_verify", CodeInput


class MeView(NoStoreMixin, generics.RetrieveAPIView):
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


class SessionActionView(NoStoreMixin, generics.GenericAPIView):
    serializer_class = StrictSerializer
    action = "logout"

    @extend_schema(responses={200: IdentityResult})
    @transaction.atomic
    def post(self, request):
        identity.identity_lock()
        user = locked_actor(request)
        if self.action == "revoke":
            user.session_version += 1
            user.save(update_fields=["session_version"])
        identity.audit(user, f"session.{self.action}", user.pk)
        logout(request)
        return Response({"status": "completed"})


class EmailChangeView(NoStoreMixin, generics.GenericAPIView):
    serializer_class = LoginInput

    @extend_schema(responses={200: IdentityResult})
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        identity.rate_limit("email_change", str(request.user.pk), settings.IDENTITY_RATE_LIMIT)
        return self.change_email(request, data)

    @transaction.atomic
    def change_email(self, request, data):
        identity.identity_lock()
        user = locked_actor(request)
        if not user.check_password(data["password"]):
            raise PermissionDenied("Credenciais inválidas.")
        if (
            identity.domain_allowed(data["email"])
            and not User.objects.filter(email=data["email"]).exists()
        ):
            identity.issue_token(user, "email", data["email"])
            identity.audit(user, "account.email_change_requested", user.pk)
        return Response({"detail": "Se o endereço for elegível, enviaremos um código por e-mail."})


def locked_actor(request, admin=False):
    user = User.objects.select_for_update().get(pk=request.user.pk)
    if (
        not identity.eligible(user)
        or request.session.get("identity_version") != user.session_version
        or (admin and user.role != User.Role.ADMIN)
    ):
        raise PermissionDenied("Sessão revogada ou permissão insuficiente.")
    return user


class MfaReplaceView(NoStoreMixin, generics.GenericAPIView):
    """Replace a lost authenticator after login with a single-use recovery code."""

    serializer_class = PasswordInput

    @extend_schema(responses={200: IdentityResult})
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identity.rate_limit("mfa_replace", str(request.user.pk), settings.IDENTITY_RATE_LIMIT)
        return self.replace(request, serializer.validated_data)

    @transaction.atomic
    def replace(self, request, data):
        identity.identity_lock()
        user = locked_actor(request)
        if (
            not user.mfa_enabled
            or not request.session.get("mfa_verified")
            or time.time() - request.session.get("mfa_at", 0) > 300
        ):
            raise PermissionDenied("Faça login novamente com MFA ou código de recuperação.")
        if "password" in data:
            if not user.check_password(data["password"]):
                raise PermissionDenied("Credenciais inválidas.")
            raw = pyotp.random_base32()
            request.session["replacement_secret"] = identity.cipher().encrypt(raw.encode()).decode()
            return Response(
                {
                    "secret": raw,
                    "uri": pyotp.TOTP(raw).provisioning_uri(
                        user.email, issuer_name="Pulse Services"
                    ),
                }
            )
        encrypted = request.session.get("replacement_secret")
        if not encrypted:
            raise ValidationError("Inicie a substituição do autenticador.")
        raw = identity.cipher().decrypt(encrypted.encode()).decode()
        totp = pyotp.TOTP(raw)
        counter = int(time.time()) // 30
        matched = next(
            (
                n
                for n in range(counter - 1, counter + 2)
                if totp.verify(data["code"], for_time=n * 30)
            ),
            None,
        )
        if matched is None:
            raise PermissionDenied("Código inválido.")
        user.mfa_secret, user.mfa_last_counter = encrypted, matched
        codes = identity.recovery_codes(user)
        user.session_version += 1
        user.save()
        identity.audit(user, "mfa.replaced", user.pk)
        request.session.flush()
        identity.start_session(request, user)
        return Response({"status": "completed", "recovery_codes": codes})


class MfaReplaceConfirmView(MfaReplaceView):
    serializer_class = CodeInput


class UserViewSet(
    NoStoreMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    serializer_class = UserSerializer

    def get_queryset(self):
        users = User.objects.order_by("id")
        if getattr(self, "swagger_fake_view", False):
            return users.none()
        return (
            users
            if self.request.user.role == User.Role.ADMIN
            else users.filter(pk=self.request.user.pk)
        )

    @extend_schema(request=UserUpdateInput, responses=UserSerializer)
    @transaction.atomic
    def partial_update(self, request, pk=None):
        identity.identity_lock()
        actor = locked_actor(request, admin=True)
        user = self.get_object()
        user = User.objects.select_for_update().get(pk=user.pk)
        serializer = UserUpdateInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        role, active = data.get("role", user.role), data.get("is_active", user.is_active)
        if active and not identity.domain_allowed(user.email):
            raise ValidationError("O domínio deve estar autorizado para ativar a conta.")
        if role != user.role and role != User.Role.COLLABORATOR and not user.email_verified_at:
            raise ValidationError("Confirme o e-mail antes de conceder privilégios.")
        if (
            user.role == User.Role.ADMIN
            and user.is_active
            and (role != User.Role.ADMIN or not active)
            and not User.objects.filter(role=User.Role.ADMIN, is_active=True)
            .exclude(pk=user.pk)
            .exists()
        ):
            raise ValidationError("Não é permitido remover o último administrador ativo.")
        changes = {"reason": data.pop("reason")}
        for field, value in data.items():
            previous = getattr(user, f"{field}_id" if field == "department" else field)
            changes[field] = {
                "from": previous,
                "to": value.pk if field == "department" and value else value,
            }
            setattr(user, field, value)
        user.session_version += 1
        user.save()
        if role not in {User.Role.TECHNICIAN, User.Role.MANAGER} or not active:
            Membership.objects.filter(user=user).delete()
        identity.audit(actor, "account.updated", user.pk, changes)
        return Response(UserSerializer(user).data)


class AdminWriteViewSet(
    NoStoreMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_permissions(self):
        cls = (
            IsAuthenticated
            if self.request.method in {"GET", "HEAD", "OPTIONS"}
            else IsIdentityAdmin
        )
        return [cls()]

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        identity.identity_lock()
        locked_actor(request, admin=True)
        return super().create(request, *args, **kwargs)

    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        identity.identity_lock()
        locked_actor(request, admin=True)
        return super().partial_update(request, *args, **kwargs)

    def perform_create(self, serializer):
        obj = serializer.save()
        identity.audit(
            self.request.user,
            f"{obj._meta.model_name}.created",
            obj.pk,
            dict(serializer.validated_data),
        )

    def perform_update(self, serializer):
        changes = {
            field: {"from": getattr(serializer.instance, field), "to": value}
            for field, value in serializer.validated_data.items()
        }
        obj = serializer.save()
        identity.audit(self.request.user, f"{obj._meta.model_name}.updated", obj.pk, changes)


class DepartmentViewSet(AdminWriteViewSet):
    serializer_class = OrganizationSerializer
    queryset = Department.objects.order_by("id")


class GroupViewSet(AdminWriteViewSet):
    serializer_class = GroupSerializer

    def get_queryset(self):
        groups = SupportGroup.objects.order_by("id")
        if getattr(self, "swagger_fake_view", False):
            return groups.none()
        if self.request.user.role == User.Role.ADMIN:
            return groups
        return groups.filter(is_active=True, membership__user=self.request.user)


class DomainViewSet(AdminWriteViewSet):
    serializer_class = DomainSerializer
    queryset = AllowedDomain.objects.order_by("id")

    def get_permissions(self):
        return [IsIdentityAdmin()]

    def perform_create(self, serializer):
        reason = serializer.validated_data.pop("reason")
        obj = serializer.save()
        identity.audit(self.request.user, "domain.created", obj.pk, {"reason": reason})

    def perform_update(self, serializer):
        reason = serializer.validated_data.pop("reason", "")
        if not reason:
            raise ValidationError({"reason": "Informe o motivo."})
        domain = serializer.instance
        affected = User.objects.filter(email__endswith="@" + domain.domain, is_active=True)
        if domain.is_active and serializer.validated_data.get("is_active") is False:
            if (
                affected.filter(role=User.Role.ADMIN).exists()
                and not User.objects.filter(role=User.Role.ADMIN, is_active=True)
                .exclude(pk__in=affected.values("pk"))
                .exists()
            ):
                raise ValidationError("A remoção bloquearia o último administrador ativo.")
            for user in affected:
                user.is_active = False
                user.session_version += 1
                user.save(update_fields=["is_active", "session_version"])
                Membership.objects.filter(user=user).delete()
                identity.audit(
                    self.request.user, "account.domain_disabled", user.pk, {"reason": reason}
                )
        obj = serializer.save()
        identity.audit(self.request.user, "domain.updated", obj.pk, {"reason": reason})


class MembershipViewSet(
    NoStoreMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsIdentityAdmin]
    serializer_class = MembershipSerializer
    queryset = Membership.objects.order_by("id")

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        identity.identity_lock()
        locked_actor(request, admin=True)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        obj = serializer.save()
        identity.audit(
            request.user, "membership.created", obj.pk, {"user": obj.user_id, "group": obj.group_id}
        )
        return Response(serializer.data, status=201)

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        identity.identity_lock()
        locked_actor(request, admin=True)
        obj = self.get_object()
        identity.audit(
            request.user, "membership.deleted", obj.pk, {"user": obj.user_id, "group": obj.group_id}
        )
        obj.delete()
        return Response(status=204)
