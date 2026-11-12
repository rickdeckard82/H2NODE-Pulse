from django.contrib.auth import logout
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from core.identity import eligible
from core.models import User

# The "Usuário" role reaches only these areas, whatever the view's own permissions say.
USER_ROLE_PREFIXES = ("/api/v1/auth/", "/api/v1/wiki/")
USER_ROLE_READ_ONLY = ("/api/v1/settings/company/",)


def user_role_may_access(request):
    path = request.path
    return path.startswith(USER_ROLE_PREFIXES) or (
        path in USER_ROLE_READ_ONLY and request.method in {"GET", "HEAD", "OPTIONS"}
    )


class VerifiedSessionAuthentication(SessionAuthentication):
    def authenticate(self, request):
        user = request._request.user
        if not user.is_authenticated:
            return None
        if (
            not eligible(user)
            or request.session.get("identity_version") != user.session_version
            or (user.mfa_enabled and not request.session.get("mfa_verified"))
        ):
            logout(request._request)
            return None
        result = super().authenticate(request)
        if result and user.role == User.Role.USER and not user_role_may_access(request):
            raise PermissionDenied("Seu perfil acessa somente a wiki.")
        return result


class IsIdentityAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == User.Role.ADMIN


class VerifiedSessionScheme(OpenApiAuthenticationExtension):
    target_class = "core.authentication.VerifiedSessionAuthentication"
    name = "cookieAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "cookie",
            "name": "sessionid",
            "description": "Sessão verificada; MFA exigido em contas que o ativaram. "
            "Mutações exigem cookie CSRF e cabeçalho X-CSRFToken, inclusive login/cadastro.",
        }
