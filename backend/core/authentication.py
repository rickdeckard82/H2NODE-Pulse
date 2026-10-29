from django.contrib.auth import logout
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import BasePermission

from core.identity import eligible
from core.models import User


class VerifiedSessionAuthentication(SessionAuthentication):
    def authenticate(self, request):
        user = request._request.user
        if not user.is_authenticated:
            return None
        if (
            not eligible(user)
            or request.session.get("identity_version") != user.session_version
            or (
                user.privileged
                and (not user.mfa_enabled or not request.session.get("mfa_verified"))
            )
        ):
            logout(request._request)
            return None
        return super().authenticate(request)


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
            "description": "Sessão verificada; MFA obrigatório para perfis privilegiados. "
            "Mutações exigem cookie CSRF e cabeçalho X-CSRFToken, inclusive login/cadastro.",
        }
