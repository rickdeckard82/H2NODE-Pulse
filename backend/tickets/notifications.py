"""Persistent at-least-once ticket notification delivery."""

import json
import random
import smtplib
import uuid
from datetime import timedelta
from email.utils import make_msgid
from functools import lru_cache
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import service_account

from core.chat_settings import active_app, active_webhook
from core.identity import cipher
from core.models import ChatConfiguration, Membership, User
from core.smtp_settings import delivery_configuration
from tickets.models import (
    Comment,
    IntegrationCheck,
    NotificationAttempt,
    NotificationDelivery,
    NotificationOutbox,
)
from tickets.permissions import outbox_projection

LEASE_SECONDS = 60
MAX_ATTEMPTS = 8
CHAT_API = "https://chat.googleapis.com/v1"
CHAT_SCOPE = "https://www.googleapis.com/auth/chat.bot"
CHAT_CERTS = (
    "https://www.googleapis.com/service_accounts/v1/metadata/x509/chat@system.gserviceaccount.com"
)

ACTION_LABELS = {
    "created": "Chamado aberto",
    "claimed": "Chamado assumido",
    "comment.added": "Nova resposta",
    "comment.corrected": "Resposta corrigida",
    "requester.replied": "Resposta do solicitante",
    "request_information": "Informações solicitadas",
    "request_test": "Teste solicitado",
    "resolve": "Chamado resolvido",
    "confirm": "Solução confirmada",
    "reopen": "Chamado reaberto",
    "cancel": "Chamado cancelado",
    "return_queue": "Chamado devolvido à fila",
    "transfer": "Chamado transferido",
    "sla.breached": "Alerta de SLA",
}


class RetryableDelivery(Exception):
    def __init__(self, code, retry_after=None):
        self.code = code
        self.retry_after = retry_after


class PermanentDelivery(Exception):
    def __init__(self, code):
        self.code = code


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _support_recipients(ticket):
    memberships = Membership.objects.filter(
        group_id=ticket.group_id,
        user__is_active=True,
        user__email_verified_at__isnull=False,
        user__role__in=[User.Role.TECHNICIAN, User.Role.MANAGER],
    )
    if ticket.restricted:
        memberships = memberships.filter(can_view_restricted=True)
    return User.objects.filter(pk__in=memberships.values("user_id"))


def _materialize(outbox):
    event, ticket = outbox.event, outbox.event.ticket
    recipients = _support_recipients(ticket)
    if event.visibility == Comment.Visibility.PUBLIC and event.actor_id != ticket.requester_id:
        recipients = recipients | User.objects.filter(pk=ticket.requester_id)
    recipients = recipients.exclude(pk=event.actor_id).distinct()
    now = timezone.now()
    app = active_app()
    for recipient in recipients:
        projection = outbox_projection(outbox, recipient)
        if projection and recipient.email:
            NotificationDelivery.objects.get_or_create(
                outbox=outbox,
                channel=NotificationDelivery.Channel.EMAIL,
                recipient_key=recipient.email.lower(),
                defaults={"recipient": recipient, "next_attempt_at": now},
            )
        if projection and app and recipient.chat_space:
            NotificationDelivery.objects.get_or_create(
                outbox=outbox,
                channel=NotificationDelivery.Channel.CHAT_DM,
                recipient_key=recipient.chat_space,
                defaults={"recipient": recipient, "next_attempt_at": now},
            )
    if event.visibility == Comment.Visibility.PUBLIC and not ticket.restricted and active_webhook():
        NotificationDelivery.objects.get_or_create(
            outbox=outbox,
            channel=NotificationDelivery.Channel.CHAT,
            recipient_key="google-chat:general-space",
            defaults={"next_attempt_at": now},
        )


def _lease_one():
    now = timezone.now()
    with transaction.atomic():
        item = (
            NotificationOutbox.objects.select_for_update(skip_locked=True, of=("self",))
            .filter(Q(status__in=["pending", "retry"]) | Q(status="leased", lease_until__lt=now))
            .filter(available_at__lte=now)
            .order_by("created_at")
            .first()
        )
        if not item:
            return None
        item.status = "leased"
        item.lease_token = uuid.uuid4()
        item.lease_until = now + timedelta(seconds=LEASE_SECONDS)
        item.save(update_fields=["status", "lease_token", "lease_until"])
        return item.pk, item.lease_token


def _message(delivery):
    outbox = delivery.outbox
    event, ticket = outbox.event, outbox.event.ticket
    projection = (
        outbox_projection(outbox, delivery.recipient)
        if delivery.recipient_id
        else {
            "number": ticket.number,
            "state": ticket.state,
        }
    )
    if delivery.recipient_id and projection is None:
        return None
    label = ACTION_LABELS.get(event.action, "Chamado atualizado")
    link = f"{settings.APP_BASE_URL.rstrip('/')}/tickets/{ticket.uuid}"
    if delivery.channel == NotificationDelivery.Channel.CHAT:
        return {"text": f"Chamado #{ticket.number} · {ticket.get_state_display()}\n{link}"}
    if delivery.channel == NotificationDelivery.Channel.CHAT_DM:
        # Never the comment body: restricted tickets and internal notes also reach this channel.
        summary = f"{label} · Chamado #{ticket.number} · {ticket.get_state_display()}"
        return {"text": f"{summary}\n{link}"}
    body = [
        f"{label} no chamado #{ticket.number}.",
        f"Estado atual: {ticket.get_state_display()}.",
        "",
    ]
    if event.comment_id:
        body.extend(["Mensagem:", event.comment.body, ""])
    body.extend(["Acesse o portal para acompanhar:", link])
    return f"[Pulse Services] {label} · #{ticket.number}", "\n".join(body)


def _send_email(to, content):
    configured = delivery_configuration()
    if not configured:
        raise RetryableDelivery("smtp_not_configured", 300)
    from_email, connection = configured
    message_id = make_msgid(domain=from_email.rsplit("@", 1)[-1])
    message = EmailMessage(
        subject=content[0],
        body=content[1],
        from_email=from_email,
        to=[to],
        connection=connection,
        headers={"Message-ID": message_id, "Auto-Submitted": "auto-generated"},
    )
    try:
        if message.send(fail_silently=False) != 1:
            raise RetryableDelivery("smtp_not_accepted")
    except TimeoutError, smtplib.SMTPException, OSError:
        raise RetryableDelivery("smtp_unavailable") from None
    return message_id


@lru_cache(maxsize=1)
def _chat_credentials(encrypted):
    info = json.loads(cipher().decrypt(encrypted.encode()))
    return service_account.Credentials.from_service_account_info(info, scopes=[CHAT_SCOPE])


def _chat_token():
    encrypted = active_app()
    if not encrypted:
        raise RetryableDelivery("chat_not_configured", 300)
    credentials = _chat_credentials(encrypted)
    if not credentials.valid:
        try:
            credentials.refresh(GoogleRequest())
        except TransportError:
            raise RetryableDelivery("chat_auth_unavailable") from None
        except RefreshError:
            raise PermanentDelivery("chat_auth_rejected") from None
    return credentials.token


def _send_chat(content):
    webhook = active_webhook()
    if not webhook:
        raise RetryableDelivery("chat_not_configured", 300)
    return _post_chat(webhook, content)


def _send_chat_dm(space, content):
    token = _chat_token()
    return _post_chat(f"{CHAT_API}/{space}/messages", content, {"Authorization": f"Bearer {token}"})


def _post_chat(url, content, headers=None):
    request = Request(
        url,
        data=json.dumps(content).encode(),
        headers={"Content-Type": "application/json; charset=utf-8", **(headers or {})},
        method="POST",
    )
    try:
        with build_opener(NoRedirect).open(request, timeout=10) as response:
            result = json.loads(response.read(65536) or b"{}")
            return str(result.get("name", ""))[:200]
    except HTTPError as exc:
        retry = exc.headers.get("Retry-After")
        if exc.code == 429 or exc.code >= 500:
            raise RetryableDelivery(
                f"chat_http_{exc.code}", int(retry) if retry and retry.isdigit() else None
            ) from None
        raise PermanentDelivery(f"chat_http_{exc.code}") from None
    except TimeoutError, URLError, OSError, json.JSONDecodeError:
        raise RetryableDelivery("chat_unavailable") from None


def _send(channel, to, content):
    try:
        if channel == NotificationDelivery.Channel.EMAIL:
            return _send_email(to, content)
        if channel == NotificationDelivery.Channel.CHAT_DM:
            return _send_chat_dm(to, content)
        return _send_chat(content)
    except RetryableDelivery, PermanentDelivery:
        raise
    except Exception:
        # Unknown errors may carry recipient data; retry them without stopping the worker loop.
        raise RetryableDelivery("internal_error") from None


def _attempt(delivery):
    now = timezone.now()
    content = _message(delivery)
    if content is None:
        delivery.status = "suppressed"
        delivery.last_error_code = "authorization_changed"
        delivery.last_attempt_at = now
        delivery.save(update_fields=["status", "last_error_code", "last_attempt_at"])
        NotificationAttempt.objects.create(
            delivery=delivery, outcome="suppressed", error_code="authorization_changed"
        )
        return
    try:
        provider_id = _send(delivery.channel, delivery.recipient_key, content)
    except RetryableDelivery as exc:
        delivery.attempts += 1
        delivery.last_attempt_at = now
        delivery.last_error_code = exc.code
        if delivery.attempts >= MAX_ATTEMPTS:
            delivery.status = "failed"
        else:
            delay = exc.retry_after or min(3600, 30 * (2 ** min(delivery.attempts, 7)))
            delivery.status = "retry"
            delivery.next_attempt_at = now + timedelta(seconds=delay + random.randint(0, 15))
        delivery.save()
        NotificationAttempt.objects.create(
            delivery=delivery, outcome=delivery.status, error_code=exc.code
        )
    except PermanentDelivery as exc:
        code = exc.code
        delivery.attempts += 1
        delivery.status = "failed"
        delivery.last_attempt_at = now
        delivery.last_error_code = code
        delivery.save()
        NotificationAttempt.objects.create(delivery=delivery, outcome="failed", error_code=code)
    else:
        delivery.attempts += 1
        delivery.status = "sent"
        delivery.last_attempt_at = delivery.sent_at = now
        delivery.provider_id = provider_id
        delivery.last_error_code = ""
        delivery.save()
        NotificationAttempt.objects.create(
            delivery=delivery, outcome="sent", provider_id=provider_id
        )


def deliver_one():
    leased = _lease_one()
    if not leased:
        return False
    outbox_id, token = leased
    outbox = NotificationOutbox.objects.select_related(
        "event__ticket", "event__actor", "event__comment"
    ).get(pk=outbox_id)
    _materialize(outbox)
    delivery = (
        outbox.deliveries.filter(
            status__in=["pending", "retry"], next_attempt_at__lte=timezone.now()
        )
        .order_by("pk")
        .first()
    )
    if delivery:
        _attempt(delivery)
    now = timezone.now()
    pending = outbox.deliveries.filter(status__in=["pending", "retry"]).order_by("next_attempt_at")
    failed = outbox.deliveries.filter(status="failed").exists()
    if pending.exists():
        status, available_at, completed_at = "retry", pending.first().next_attempt_at, None
    else:
        status, available_at, completed_at = ("failed" if failed else "sent"), now, now
    NotificationOutbox.objects.filter(pk=outbox_id, lease_token=token).update(
        status=status,
        available_at=available_at,
        completed_at=completed_at,
        lease_token=None,
        lease_until=None,
    )
    return True


def check_one():
    with transaction.atomic():
        check = (
            IntegrationCheck.objects.select_for_update(skip_locked=True, of=("self",))
            .select_related("requested_by")
            .filter(status="pending")
            .order_by("pk")
            .first()
        )
        if not check:
            return False
        if check.channel == NotificationDelivery.Channel.EMAIL:
            content = (
                "[Pulse Services] Teste controlado de SMTP",
                "Este e-mail confirma a comunicação do Pulse Services com o SMTP configurado.",
            )
        else:
            content = {"text": "Pulse Services · teste controlado da integração"}
        direct = check.channel == NotificationDelivery.Channel.CHAT_DM
        to = check.requested_by.chat_space if direct else check.requested_by.email
        try:
            if not to:
                raise PermanentDelivery("chat_not_linked")
            _send(check.channel, to, content)
        except (RetryableDelivery, PermanentDelivery) as exc:
            check.status, check.error_code = "failed", exc.code
        else:
            check.status = "sent"
        check.completed_at = timezone.now()
        check.save(update_fields=["status", "error_code", "completed_at"])
        return True


def refresh_chat_certs():
    """The API has no egress, so the worker keeps Google's public certificates in the database."""
    config = ChatConfiguration.objects.exclude(project_number="").first()
    now = timezone.now()
    if not config or (
        config.certs_updated_at and now - config.certs_updated_at < timedelta(hours=1)
    ):
        return
    try:
        with build_opener(NoRedirect).open(Request(CHAT_CERTS), timeout=10) as response:
            certs = json.loads(response.read(262144))
    except TimeoutError, URLError, OSError, ValueError:
        return
    if isinstance(certs, dict) and certs:
        ChatConfiguration.objects.filter(pk=config.pk).update(
            google_certs=certs, certs_updated_at=now
        )
