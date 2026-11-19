import time
import uuid

import pyotp
from django.conf import settings
from django.contrib.auth import logout
from django.db import transaction
from django.db.models import ProtectedError
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import extend_schema
from rest_framework import generics, mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from core import identity, turnstile
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
    MfaDisableInput,
    MfaVerifyInput,
    OrganizationSerializer,
    PasswordChangeInput,
    PasswordInput,
    ProfileInput,
    ProfileSerializer,
    ReasonInput,
    RegisterInput,
    ResetInput,
    StrictSerializer,
    UserCreateInput,
    UserSerializer,
    UserUpdateInput,
)

MAIL_RESPONSE_SECONDS = 0.25
TURNSTILE_ACTIONS = {"login", "register", "forgot"}


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
        return Response(
            {
                "csrfToken": get_token(request),
                "turnstileSiteKey": settings.TURNSTILE_SITE_KEY if settings.TURNSTILE_ENABLED else "",
            }
        )


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
        raw = request.data
        token = None
        if self.action in TURNSTILE_ACTIONS and isinstance(raw, dict):
            raw = {k: v for k, v in raw.items() if k != "turnstile_token"}
            token = request.data.get("turnstile_token")
        serializer = self.get_serializer(data=raw)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if self.action in TURNSTILE_ACTIONS:
            turnstile.verify(token, request.META.get("REMOTE_ADDR"))
        # REMOTE_ADDR is deliberately used until the trusted proxy chain is homologated.
        identity.rate_limit("source", request.META.get("REMOTE_ADDR", "unknown"), 500)
        key = data.get("email") or str(request.session.get("pending_identity", {}).get("id", ""))
        if not key:
            key = request.session.session_key or request.META.get("REMOTE_ADDR", "unknown")
        identity.rate_limit(self.action, key, settings.IDENTITY_RATE_LIMIT)
        result = {"detail": "Se os dados forem elegíveis, enviaremos um código por e-mail."}
        if self.action in {"register", "resend", "forgot"}:
            started = time.monotonic()
            if self.action == "register":
                identity.register(data)
            else:
                purpose = "verify" if self.action == "resend" else "reset"
                identity.request_token(data["email"], purpose)
            # Fixed minimum duration: database work for existing accounts must not reveal them.
            time.sleep(max(0, MAIL_RESPONSE_SECONDS - (time.monotonic() - started)))
        elif self.action in {"confirm", "reset"}:
            purpose = {"confirm": "verify", "reset": "reset"}[self.action]
            identity.redeem_token(data["token"], purpose, data.get("password"))
            result = {"status": "completed"}
        elif self.action == "login":
            try:
                result = identity.password_login(request, **data)
            except PermissionDenied:
                identity.login_failed(email=data["email"])
                raise
        elif self.action == "mfa_verify":
            pending = request.session.get("pending_identity", {}).get("id")
            try:
                result = identity.verify_mfa(request, **data)
            except PermissionDenied:
                if pending:
                    identity.login_failed(user_id=pending)
                raise
        from core.trusted_devices import apply_cookie

        return apply_cookie(request, Response(result))


class RegisterView(AuthActionView):
    action, serializer_class = "register", RegisterInput


class ResendView(AuthActionView):
    action, serializer_class = "resend", EmailInput


class ForgotView(AuthActionView):
    action, serializer_class = "forgot", EmailInput


class ConfirmView(AuthActionView):
    action, serializer_class = "confirm", ResetInput


class ResetView(AuthActionView):
    action, serializer_class = "reset", ResetInput


class LoginView(AuthActionView):
    action, serializer_class = "login", LoginInput


class MfaVerifyView(AuthActionView):
    action, serializer_class = "mfa_verify", MfaVerifyInput


class MeView(NoStoreMixin, generics.RetrieveAPIView):
    serializer_class = ProfileSerializer

    def get_object(self):
        return self.request.user

    @extend_schema(request=ProfileInput, responses={200: ProfileSerializer})
    @transaction.atomic
    def patch(self, request):
        serializer = ProfileInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = locked_actor(request)
        for field, value in data.items():
            setattr(user, field, value)
        user.save(update_fields=list(data))
        identity.audit(user, "account.profile_updated", user.pk, {"fields": sorted(data)})
        return Response(ProfileSerializer(user).data)


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
            from core.models import TrustedDevice

            TrustedDevice.objects.filter(user=user).delete()
        if self.action in {"forget_device", "revoke"}:
            from core.trusted_devices import forget

            forget(request, user)
        identity.audit(user, f"session.{self.action}", user.pk)
        logout(request)
        from core.trusted_devices import apply_cookie

        return apply_cookie(request, Response({"status": "completed"}))


class PasswordChangeView(NoStoreMixin, generics.GenericAPIView):
    serializer_class = PasswordChangeInput

    @extend_schema(responses={200: IdentityResult})
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identity.rate_limit("password_change", str(request.user.pk), settings.IDENTITY_RATE_LIMIT)
        return self.change_password(request, serializer.validated_data)

    @transaction.atomic
    def change_password(self, request, data):
        identity.identity_lock()
        user = locked_actor(request)
        if not user.check_password(data["current_password"]):
            raise PermissionDenied("Credenciais inválidas.")
        if user.check_password(data["new_password"]):
            raise ValidationError({"new_password": ["A nova senha deve ser diferente da atual."]})
        user.password = identity.password_hash(data["new_password"], user)
        user.session_version += 1
        user.save(update_fields=["password", "session_version"])
        from core.models import TrustedDevice
        from core.trusted_devices import apply_cookie, forget

        TrustedDevice.objects.filter(user=user).delete()
        forget(request, user)
        identity.audit(user, "account.password_changed", user.pk)
        logout(request)
        return apply_cookie(request, Response({"status": "completed"}))


def locked_actor(request, admin=False, no_key=False):
    user = User.objects.select_for_update(no_key=no_key).get(pk=request.user.pk)
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
    enabling = False

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
        if self.enabling:
            if user.mfa_enabled:
                raise PermissionDenied("MFA já configurado.")
        elif (
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
        user.mfa_secret, user.mfa_last_counter, user.mfa_enabled = encrypted, matched, True
        codes = identity.recovery_codes(user)
        user.session_version += 1
        user.save()
        identity.audit(user, "mfa.enrolled" if self.enabling else "mfa.replaced", user.pk)
        request.session.flush()
        identity.start_session(request, user)
        return Response({"status": "completed", "recovery_codes": codes})


class MfaReplaceConfirmView(MfaReplaceView):
    serializer_class = CodeInput


class MfaEnableView(MfaReplaceView):
    """Opt in from the profile: password first, then a code from the new authenticator."""

    enabling = True


class MfaEnableConfirmView(MfaEnableView):
    serializer_class = CodeInput


class MfaDisableView(NoStoreMixin, generics.GenericAPIView):
    """Both factors are required, so a stolen open session cannot remove the protection."""

    serializer_class = MfaDisableInput

    @extend_schema(responses={200: IdentityResult})
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identity.rate_limit("mfa_disable", str(request.user.pk), settings.IDENTITY_RATE_LIMIT)
        return self.disable(request, serializer.validated_data)

    @transaction.atomic
    def disable(self, request, data):
        identity.identity_lock()
        user = locked_actor(request)
        if not user.mfa_enabled or not user.check_password(data["password"]):
            raise PermissionDenied("Credenciais inválidas.")
        identity.check_factor(user, data["code"])
        identity.clear_mfa(user)
        identity.audit(user, "mfa.disabled", user.pk)
        from core.trusted_devices import apply_cookie, forget

        forget(request, user)
        request.session.flush()
        identity.start_session(request, user)
        return apply_cookie(request, Response({"status": "completed"}))


class UserViewSet(
    NoStoreMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    serializer_class = UserSerializer

    @extend_schema(request=UserCreateInput, responses={201: UserSerializer})
    @transaction.atomic
    def create(self, request):
        identity.identity_lock()
        actor = locked_actor(request, admin=True)
        serializer = UserCreateInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if not identity.domain_allowed(data["email"]):
            raise ValidationError({"email": ["Domínio não autorizado."]})
        if User.objects.filter(email__iexact=data["email"]).exists():
            raise ValidationError({"email": ["Já existe uma conta com este e-mail."]})
        # Always a collaborator without password: privileges only after the invite proves the
        # mailbox. Self-registration, by contrast, starts as the wiki-only "Usuário".
        user = User(
            role=User.Role.COLLABORATOR,
            username=uuid.uuid4().hex,
            email=data["email"],
            first_name=data["first_name"],
            department=data.get("department"),
        )
        user.set_unusable_password()
        user.save()
        identity.issue_token(user, "invite")
        identity.audit(actor, "account.created", user.pk, {"reason": data["reason"]})
        return Response(UserSerializer(user).data, status=201)

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
        if (
            role != user.role
            and role not in {User.Role.USER, User.Role.COLLABORATOR}
            and not user.email_verified_at
        ):
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
        # Only privilege or activation changes revoke sessions and pending codes; the area is a
        # label that grants no access, so it must not invalidate an unconfirmed sign-up.
        revoke = role != user.role or active != user.is_active
        for field, value in data.items():
            previous = getattr(user, f"{field}_id" if field == "department" else field)
            changes[field] = {
                "from": previous,
                "to": value.pk if field == "department" and value else value,
            }
            setattr(user, field, value)
        if revoke:
            user.session_version += 1
        user.save()
        if role not in {User.Role.TECHNICIAN, User.Role.MANAGER} or not active:
            Membership.objects.filter(user=user).delete()
        identity.audit(actor, "account.updated", user.pk, changes)
        return Response(UserSerializer(user).data)

    @extend_schema(request=ReasonInput, responses=UserSerializer)
    @action(detail=True, methods=["post"], url_path="disable-mfa")
    @transaction.atomic
    def disable_mfa(self, request, pk=None):
        identity.identity_lock()
        actor = locked_actor(request, admin=True)
        serializer = ReasonInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.select_for_update().get(pk=self.get_object().pk)
        # The profile asks for password and code; this route must not bypass them.
        if user.pk == actor.pk:
            raise ValidationError("Desative a sua verificação em Perfil.")
        if not user.mfa_enabled:
            raise ValidationError("A verificação em duas etapas já está desativada.")
        identity.clear_mfa(user)
        identity.audit(actor, "mfa.disabled_by_admin", user.pk, serializer.validated_data)
        return Response(UserSerializer(user).data)


class AdminWriteViewSet(
    NoStoreMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

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

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        identity.identity_lock()
        locked_actor(request, admin=True)
        obj = self.get_object()
        name = obj._meta.model_name
        try:
            # Every reference (accounts, tickets, categories, memberships) is PROTECT.
            with transaction.atomic():
                obj.delete()
        except ProtectedError:
            raise ValidationError("Registro em uso; desative-o em vez de remover.") from None
        identity.audit(request.user, f"{name}.deleted", kwargs["pk"])
        return Response(status=204)


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

    http_method_names = [*AdminWriteViewSet.http_method_names, "delete"]

    def disable_accounts(self, domain, reason):
        affected = User.objects.filter(email__endswith="@" + domain.domain, is_active=True)
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

    def perform_update(self, serializer):
        reason = serializer.validated_data.pop("reason", "")
        if not reason:
            raise ValidationError({"reason": "Informe o motivo."})
        domain = serializer.instance
        if domain.is_active and serializer.validated_data.get("is_active") is False:
            self.disable_accounts(domain, reason)
        obj = serializer.save()
        identity.audit(self.request.user, "domain.updated", obj.pk, {"reason": reason})

    @extend_schema(request=ReasonInput, responses={204: None})
    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        identity.identity_lock()
        locked_actor(request, admin=True)
        reason = ReasonInput(data=request.data)
        reason.is_valid(raise_exception=True)
        domain = self.get_object()
        # Removing must not leave accounts usable that deactivation would have blocked.
        if domain.is_active:
            self.disable_accounts(domain, reason.validated_data["reason"])
        identity.audit(
            request.user,
            "domain.deleted",
            domain.pk,
            {"domain": domain.domain, "reason": reason.validated_data["reason"]},
        )
        domain.delete()
        return Response(status=204)


class MembershipViewSet(
    NoStoreMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
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
            request.user,
            "membership.created",
            obj.pk,
            {
                "user": obj.user_id,
                "group": obj.group_id,
                "can_view_restricted": obj.can_view_restricted,
                "can_transfer": obj.can_transfer,
                "can_cancel": obj.can_cancel,
            },
        )
        return Response(serializer.data, status=201)

    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        identity.identity_lock()
        locked_actor(request, admin=True)
        return super().partial_update(request, *args, **kwargs)

    def perform_update(self, serializer):
        changes = {
            field: {
                "from": getattr(getattr(serializer.instance, field), "pk", None)
                if field in {"user", "group"}
                else getattr(serializer.instance, field),
                "to": getattr(value, "pk", value),
            }
            for field, value in serializer.validated_data.items()
        }
        obj = serializer.save()
        identity.audit(self.request.user, "membership.updated", obj.pk, changes)

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
