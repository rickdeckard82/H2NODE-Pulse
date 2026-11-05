"""Google Chat app events: the only way to learn each user's direct message space."""

import logging
import re

from django.conf import settings
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from google.auth import jwt
from google.auth.exceptions import GoogleAuthError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core.identity import audit, eligible
from core.identity_views import NoStoreMixin
from core.models import ChatConfiguration, User

ISSUER = "chat@system.gserviceaccount.com"
logger = logging.getLogger(__name__)


def verified(header):
    """Certificates come from the database: the worker fetches them, the API has no egress."""
    config = ChatConfiguration.objects.first()
    scheme, _, token = header.partition(" ")
    if not config or not config.project_number or not config.google_certs:
        return False
    if scheme != "Bearer" or not token:
        return False
    try:
        claims = jwt.decode(token, certs=config.google_certs, audience=config.project_number)
    except ValueError, GoogleAuthError:
        return False
    return claims.get("iss") == ISSUER


class ChatEventsView(NoStoreMixin, APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        if not verified(request.headers.get("Authorization", "")):
            return Response(status=401)
        event = request.data if isinstance(request.data, dict) else {}
        space = event.get("space") if isinstance(event.get("space"), dict) else {}
        person = event.get("user") if isinstance(event.get("user"), dict) else {}
        name = str(space.get("name", ""))
        kind = event.get("type")
        direct = space.get("singleUserBotDm") is True or space.get("type") == "DM"
        if not direct or not re.fullmatch(r"spaces/[A-Za-z0-9_-]+", name):
            return Response({})
        if kind == "REMOVED_FROM_SPACE":
            User.objects.filter(chat_space=name).update(chat_space="")
            return Response({})
        if kind not in {"ADDED_TO_SPACE", "MESSAGE"}:
            return Response({})
        email = str(person.get("email", "")).strip()
        if not email:
            logger.warning("chat_event_without_email")
        account = User.objects.filter(email__iexact=email).first() if email else None
        if not eligible(account):
            return Response({"text": "Não encontrei uma conta ativa do Pulse com este e-mail."})
        if account.chat_space != name:
            User.objects.filter(pk=account.pk).update(chat_space=name)
            audit(account, "chat.linked", account.pk)
        if kind == "MESSAGE":
            portal = settings.APP_BASE_URL.rstrip("/")
            return Response({"text": f"Este app só envia avisos. Responda pelo portal: {portal}"})
        return Response({"text": "Pronto! Você receberá aqui os avisos dos seus chamados."})
