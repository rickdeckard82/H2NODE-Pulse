import json
import tempfile
import time
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from django.core import mail
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone
from google.auth import crypt, jwt

from core.chat_events import ISSUER
from core.chat_settings import active_webhook
from core.identity import cipher
from core.models import (
    ChatConfiguration,
    Department,
    IdentityEvent,
    Membership,
    SupportGroup,
)
from tickets.attachments import path_for
from tickets.models import (
    Attachment,
    Category,
    Comment,
    IntegrationCheck,
    NotificationAttempt,
    NotificationDelivery,
    NotificationOutbox,
    NotificationRead,
    RetentionPolicy,
    Ticket,
    TicketEvent,
)
from tickets.notifications import (
    RetryableDelivery,
    check_one,
    deliver_one,
    refresh_chat_certs,
)
from tickets.retention import run_retention
from tickets.tests import TicketHelpers

EVENTS = "/api/v1/integrations/google-chat/events/"
PROJECT = "1234567890"


def signing_material():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "synthetic")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return pem, certificate.public_bytes(serialization.Encoding.PEM).decode()


KEY, CERTIFICATE = signing_material()
ACCOUNT = json.dumps(
    {
        "type": "service_account",
        "client_email": "pulse-chat@synthetic.iam.gserviceaccount.com",
        "private_key": KEY,
        "private_key_id": "k1",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
)


@override_settings(
    IDENTITY_RATE_LIMIT=100,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_HOST="smtp.synthetic.test",
    DEFAULT_FROM_EMAIL="pulse@company.test",
    APP_BASE_URL="https://support.company.test",
)
class NotificationTests(TicketHelpers, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_fixtures()

    def setUp(self):
        self.clients = {}
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL ROLE pulse_runtime")

    def drain(self, limit=20):
        for _ in range(limit):
            if not deliver_one():
                break

    @patch("tickets.notifications.active_webhook", return_value=None)
    def test_creation_notifies_support_once_and_not_requester(self, unused):
        ticket = self.create()
        self.drain()
        outbox = NotificationOutbox.objects.get(event__ticket=ticket)
        deliveries = outbox.deliveries.all()
        self.assertEqual(deliveries.count(), 3)
        self.assertFalse(deliveries.filter(recipient=self.owner).exists())
        self.assertFalse(deliveries.exclude(status="sent").exists())
        self.assertEqual(len(mail.outbox), 3)
        self.assertTrue(all(ticket.subject not in message.body for message in mail.outbox))
        self.assertEqual(NotificationAttempt.objects.filter(outcome="sent").count(), 3)
        self.assertFalse(deliver_one())
        self.assertEqual(len(mail.outbox), 3)

    @patch("tickets.notifications.active_webhook", return_value=None)
    def test_internal_note_never_targets_requester(self, unused):
        ticket = self.create()
        self.claim(ticket)
        response = self.mutate(
            ticket,
            self.tech,
            "comments",
            {"body": "Nota interna sintética", "visibility": "internal"},
        )
        self.assertEqual(response.status_code, 201, response.content)
        outbox = NotificationOutbox.objects.get(event_id=response.json()["event_id"])
        self.drain()
        self.assertFalse(outbox.deliveries.filter(recipient=self.owner).exists())
        self.assertFalse(outbox.deliveries.filter(recipient=self.tech).exists())
        self.assertTrue(outbox.deliveries.filter(recipient=self.manager, status="sent").exists())

    @patch("tickets.notifications._send_email", side_effect=RetryableDelivery("smtp_unavailable"))
    @patch("tickets.notifications.active_webhook", return_value=None)
    def test_retry_is_persisted_and_stale_lease_is_recovered(self, unused_webhook, unused_send):
        ticket = self.create()
        outbox = NotificationOutbox.objects.get(event__ticket=ticket)
        outbox.status = "leased"
        outbox.lease_until = timezone.now() - timedelta(seconds=1)
        outbox.save(update_fields=["status", "lease_until"])
        self.assertTrue(deliver_one())
        delivery = outbox.deliveries.get(status="retry")
        self.assertEqual(delivery.attempts, 1)
        self.assertEqual(delivery.last_error_code, "smtp_unavailable")
        self.assertTrue(delivery.history.filter(outcome="retry").exists())

    @patch("tickets.notifications._send_chat", return_value="spaces/test/messages/1")
    @patch(
        "tickets.notifications.active_webhook",
        return_value="https://chat.googleapis.com/v1/spaces/AAA/messages?key=x&token=y",
    )
    def test_chat_payload_is_minimal_and_restricted_ticket_is_suppressed(
        self, unused_webhook, send
    ):
        ticket = self.create()
        self.drain()
        chat = NotificationDelivery.objects.get(
            outbox__event__ticket=ticket, channel=NotificationDelivery.Channel.CHAT
        )
        self.assertEqual(chat.status, "sent")
        payload = send.call_args.args[0]
        self.assertIn(f"#{ticket.number}", payload["text"])
        self.assertNotIn(ticket.subject, payload["text"])
        self.assertNotIn(ticket.description, payload["text"])

        restricted = self.create(category=self.restricted_category.pk)
        self.drain()
        self.assertFalse(
            NotificationDelivery.objects.filter(
                outbox__event__ticket=restricted, channel=NotificationDelivery.Channel.CHAT
            ).exists()
        )

    @patch("tickets.notifications.delivery_configuration")
    @patch("tickets.notifications.active_webhook", return_value=None)
    def test_unexpected_error_keeps_worker_alive_and_is_sanitized(self, unused, configured):
        configured.side_effect = RuntimeError("owner@company.test rejeitado")
        ticket = self.create()
        self.assertTrue(deliver_one())
        delivery = NotificationDelivery.objects.get(outbox__event__ticket=ticket, status="retry")
        self.assertEqual(delivery.last_error_code, "internal_error")
        self.assertNotIn("company.test", str(list(delivery.history.values())))

    @patch("tickets.notifications.build_opener")
    @patch(
        "tickets.notifications.active_webhook",
        return_value="https://chat.googleapis.com/v1/spaces/AAA/messages?key=x&token=y",
    )
    @patch("tickets.notifications._send_email", return_value="<id@company.test>")
    def test_chat_rate_limit_timeout_and_permanent_rejection(self, unused, webhook, opener):
        url = webhook.return_value
        cases = [
            (HTTPError(url, 429, "limit", {"Retry-After": "120"}, None), "retry", "chat_http_429"),
            (TimeoutError(), "retry", "chat_unavailable"),
            (HTTPError(url, 503, "down", {}, None), "retry", "chat_http_503"),
            (HTTPError(url, 400, "bad", {}, None), "failed", "chat_http_400"),
        ]
        for error, status, code in cases:
            with self.subTest(code=code):
                opener.return_value.open.side_effect = error
                ticket = self.create()
                before = timezone.now()
                self.drain()
                chat = NotificationDelivery.objects.get(
                    outbox__event__ticket=ticket, channel=NotificationDelivery.Channel.CHAT
                )
                self.assertEqual((chat.status, chat.last_error_code), (status, code))
                self.assertNotIn("token", str(list(chat.history.values())))
                if code == "chat_http_429":
                    self.assertGreaterEqual(chat.next_attempt_at, before + timedelta(seconds=120))

    @patch("tickets.notifications.active_webhook", return_value=None)
    def test_lost_lease_does_not_overwrite_new_owner(self, unused):
        ticket = self.create()
        outbox = NotificationOutbox.objects.get(event__ticket=ticket)
        other = uuid.uuid4()

        def taken_over(delivery):
            NotificationOutbox.objects.filter(pk=outbox.pk).update(lease_token=other)

        with patch("tickets.notifications._attempt", side_effect=taken_over):
            self.assertTrue(deliver_one())
        outbox.refresh_from_db()
        self.assertEqual((outbox.status, outbox.lease_token), ("leased", other))

    @patch("tickets.notifications._send_email", side_effect=RetryableDelivery("smtp_unavailable"))
    @patch("tickets.notifications.active_webhook", return_value=None)
    def test_exhausted_delivery_fails_and_admin_requeues(self, unused, send):
        ticket = self.create()
        self.assertTrue(deliver_one())
        delivery = NotificationDelivery.objects.get(outbox__event__ticket=ticket, status="retry")
        delivery.attempts = 7
        delivery.next_attempt_at = timezone.now()
        delivery.save()
        NotificationOutbox.objects.filter(pk=delivery.outbox_id).update(available_at=timezone.now())
        self.drain()
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, "failed")

        path = f"/api/v1/settings/notifications/{delivery.pk}/retry/"
        denied = self.post(self.client_as(self.tech), path, {"reason": "x"})
        self.assertEqual(denied.status_code, 403)
        listing = self.client_as(self.admin).get("/api/v1/settings/notifications/").json()
        self.assertNotIn(delivery.recipient_key, str(listing))
        response = self.post(self.client_as(self.admin), path, {"reason": "SMTP restabelecido"})
        self.assertEqual(response.status_code, 200, response.content)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, "pending")
        send.side_effect = None
        send.return_value = "<id@company.test>"
        self.drain()
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, "sent")
        sent = self.post(self.client_as(self.admin), path, {"reason": "de novo"})
        self.assertEqual(sent.status_code, 409)

    def test_chat_settings_validate_encrypt_and_hide_webhook(self):
        admin = self.client_as(self.admin)
        webhook = "https://chat.googleapis.com/v1/spaces/AAA/messages?key=k1&token=t1"
        self.assertEqual(self.client_as(self.tech).get("/api/v1/settings/chat/").status_code, 403)
        for bad in [
            "http://chat.googleapis.com/v1/spaces/AAA/messages?key=k&token=t",
            "https://evil.test/v1/spaces/AAA/messages?key=k&token=t",
            "https://chat.googleapis.com/v1/spaces/AAA/messages?key=k",
            "https://chat.googleapis.com:8443/v1/spaces/AAA/messages?key=k&token=t",
        ]:
            response = self.patch(admin, "/api/v1/settings/chat/", {"webhook": bad, "reason": "x"})
            self.assertEqual(response.status_code, 400, bad)
        response = self.patch(admin, "/api/v1/settings/chat/", {"enabled": True, "reason": "x"})
        self.assertEqual(response.status_code, 400)
        response = self.patch(
            admin,
            "/api/v1/settings/chat/",
            {"webhook": webhook, "enabled": True, "reason": "Espaço de homologação"},
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertNotIn("t1", response.content.decode())
        stored = ChatConfiguration.objects.get()
        self.assertNotIn("t1", stored.encrypted_webhook)
        self.assertEqual(active_webhook(), webhook)

    @patch("tickets.notifications._send_chat", side_effect=RetryableDelivery("chat_x"))
    def test_integration_test_is_queued_for_worker_and_sends_to_admin_only(self, unused):
        admin = self.client_as(self.admin)
        path = "/api/v1/settings/notifications/test/"
        denied = self.post(self.client_as(self.tech), path, {"channel": "email", "reason": "x"})
        self.assertEqual(denied.status_code, 403)
        for channel in ["email", "chat"]:
            response = self.post(admin, path, {"channel": channel, "reason": "Homologação"})
            self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual(len(mail.outbox), 0)
        while check_one():
            pass
        self.assertEqual(mail.outbox[-1].to, [self.admin.email])
        results = {row["channel"]: row for row in admin.get(path).json()}
        self.assertEqual(results["email"]["status"], "sent")
        self.assertEqual(
            (results["chat"]["status"], results["chat"]["error_code"]), ("failed", "chat_x")
        )


class WorkingTechnicianNotificationTests(TicketHelpers, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_fixtures()

    def setUp(self):
        self.clients = {}
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL ROLE pulse_runtime")

    def notified(self, user):
        for _ in range(30):
            if not deliver_one():
                break
        return NotificationDelivery.objects.filter(recipient=user).count()

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        EMAIL_HOST="smtp.synthetic.test",
        DEFAULT_FROM_EMAIL="pulse@company.test",
        APP_BASE_URL="https://support.company.test",
    )
    def test_assignee_and_participant_outside_group_are_notified(self):
        group = SupportGroup.objects.create(name="Grupo sem os técnicos")
        category = Category.objects.create(name="Fora do grupo", group=group)
        ticket = self.create(category=category.pk)
        self.assertEqual(self.notified(self.outsider), 0)
        self.claim(ticket, self.outsider)
        self.assertEqual(self.mutate(ticket, self.tech2, "join").status_code, 200)
        before = self.notified(self.outsider), self.notified(self.tech2)
        self.mutate(ticket, self.owner, "comments", {"body": "Resposta", "visibility": "public"})
        self.assertGreater(self.notified(self.outsider), before[0])
        self.assertGreater(self.notified(self.tech2), before[1])
        self.assertEqual(self.notified(self.tech), 0)
        self.assertFalse(
            NotificationDelivery.objects.filter(
                recipient=self.owner, outbox__event__action="comment.added"
            ).exists()
        )


class ChatAppTests(TicketHelpers, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_fixtures()
        ChatConfiguration.objects.create(
            project_number=PROJECT,
            encrypted_service_account=cipher().encrypt(ACCOUNT.encode()).decode(),
            google_certs={"k1": CERTIFICATE},
        )

    def setUp(self):
        self.clients = {}
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL ROLE pulse_runtime")

    def token(self, **overrides):
        now = int(time.time())
        claims = {"iss": ISSUER, "aud": PROJECT, "iat": now, "exp": now + 300, **overrides}
        return jwt.encode(crypt.RSASigner.from_string(KEY, "k1"), claims).decode()

    def event(self, kind="ADDED_TO_SPACE", token=None, email=None, **space):
        return self.client.post(
            EVENTS,
            {
                "type": kind,
                "user": {"name": "users/1", "email": email or self.owner.email.upper()},
                "space": {"name": "spaces/DM1", "singleUserBotDm": True, **space},
            },
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token or self.token()}",
        )

    def test_events_require_google_signature(self):
        now = int(time.time())
        forged, _ = signing_material()
        for token in [
            "not-a-token",
            self.token(aud="999"),
            self.token(iss="attacker@example.com"),
            self.token(iat=now - 900, exp=now - 600),
            jwt.encode(crypt.RSASigner.from_string(forged, "k1"), {"iss": ISSUER}).decode(),
        ]:
            self.assertEqual(self.event(token=token).status_code, 401, token)
        self.assertEqual(self.client.post(EVENTS, {}).status_code, 401)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.chat_space, "")

    def test_install_links_user_and_removal_unlinks(self):
        response = self.event()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn("Pronto", response.json()["text"])
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.chat_space, "spaces/DM1")
        self.assertEqual(self.event("REMOVED_FROM_SPACE").status_code, 200)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.chat_space, "")

    def test_message_links_users_who_installed_before_the_endpoint_existed(self):
        self.assertEqual(self.event("MESSAGE").status_code, 200)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.chat_space, "spaces/DM1")

    def test_unknown_inactive_group_space_and_bad_name_never_link(self):
        self.assertIn("Não encontrei", self.event(email="ghost@company.test").json()["text"])
        self.assertEqual(self.event(singleUserBotDm=False).json(), {})
        self.assertEqual(self.event(name="spaces/../evil").json(), {})
        User = type(self.owner)
        User.objects.filter(pk=self.owner.pk).update(is_active=False)
        self.assertIn("Não encontrei", self.event().json()["text"])
        self.assertFalse(User.objects.exclude(chat_space="").exists())

    @patch("tickets.notifications._chat_token", return_value="access")
    @patch("tickets.notifications.build_opener")
    def test_linked_user_receives_minimal_direct_message(self, opener, unused):
        response = MagicMock()
        response.read.return_value = b'{"name": "spaces/DM1/messages/1"}'
        opener.return_value.open.return_value.__enter__.return_value = response
        self.owner.chat_space = "spaces/DM1"
        self.owner.save(update_fields=["chat_space"])
        ticket = self.create()
        self.claim(ticket)
        self.mutate(ticket, self.tech, "comments", {"body": "SEGREDO", "visibility": "public"})
        for _ in range(20):
            if not deliver_one():
                break
        sent = NotificationDelivery.objects.filter(
            channel=NotificationDelivery.Channel.CHAT_DM, recipient=self.owner
        )
        self.assertTrue(sent.exists())
        self.assertEqual({item.status for item in sent}, {"sent"})
        requests = [call.args[0] for call in opener.return_value.open.call_args_list]
        self.assertTrue(requests)
        for request in requests:
            self.assertEqual(request.full_url, "https://chat.googleapis.com/v1/spaces/DM1/messages")
            self.assertEqual(request.headers["Authorization"], "Bearer access")
            self.assertNotIn("SEGREDO", request.data.decode())

    def test_unlinked_user_keeps_email_only(self):
        self.create(user=self.peer)
        for _ in range(20):
            if not deliver_one():
                break
        self.assertFalse(
            NotificationDelivery.objects.filter(
                channel=NotificationDelivery.Channel.CHAT_DM
            ).exists()
        )

    def test_integration_check_needs_a_linked_administrator(self):
        check = IntegrationCheck.objects.create(
            channel=NotificationDelivery.Channel.CHAT_DM, requested_by=self.admin
        )
        check_one()
        check.refresh_from_db()
        self.assertEqual((check.status, check.error_code), ("failed", "chat_not_linked"))

    def test_settings_validate_key_and_never_return_it(self):
        admin = self.client_as(self.admin)
        csrf = admin.get("/api/v1/auth/csrf/").json()["csrfToken"]

        def patch_chat(body):
            return admin.patch(
                "/api/v1/settings/chat/",
                {"reason": "x", **body},
                content_type="application/json",
                HTTP_X_CSRFTOKEN=csrf,
            )

        redirected = {**json.loads(ACCOUNT), "token_uri": "https://evil.example/token"}
        for bad in ["{", "[]", json.dumps(redirected)]:
            self.assertEqual(patch_chat({"service_account": bad}).status_code, 400, bad)
        self.assertEqual(patch_chat({"project_number": "abc"}).status_code, 400)
        response = patch_chat({"service_account": ACCOUNT, "project_number": "777"})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["app_configured"])
        self.assertNotIn("private_key", response.content.decode())
        stored = ChatConfiguration.objects.get()
        self.assertNotIn("private_key", stored.encrypted_service_account)
        self.assertEqual(stored.project_number, "777")
        self.assertFalse(patch_chat({"clear_app": True}).json()["app_configured"])
        self.assertEqual(ChatConfiguration.objects.get().google_certs, {})

    @patch("tickets.notifications.build_opener")
    def test_worker_refreshes_certificates_hourly(self, opener):
        response = MagicMock()
        response.read.return_value = b'{"k2": "pem"}'
        opener.return_value.open.return_value.__enter__.return_value = response
        refresh_chat_certs()
        config = ChatConfiguration.objects.get()
        self.assertEqual(config.google_certs, {"k2": "pem"})
        refresh_chat_certs()
        self.assertEqual(opener.return_value.open.call_count, 1)
        opener.return_value.open.side_effect = TimeoutError
        ChatConfiguration.objects.update(certs_updated_at=None)
        refresh_chat_certs()
        self.assertEqual(ChatConfiguration.objects.get().google_certs, {"k2": "pem"})


class RetentionTests(TicketHelpers, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_fixtures()

    def setUp(self):
        self.clients = {}
        self.now = timezone.now()
        self.old = self.now - timedelta(days=400)
        self.policy = RetentionPolicy.objects.create(
            enabled=True,
            tickets_days=365,
            users_days=365,
            groups_days=365,
            categories_days=365,
            departments_days=365,
            logs_days=365,
        )
        RetentionPolicy.objects.update(updated_at=self.now - timedelta(days=2))

    def closed_ticket(self, user=None, closed_at=None):
        ticket = self.create(user=user)
        self.claim(ticket)
        Ticket.objects.filter(pk=ticket.pk).update(state="closed", closed_at=closed_at or self.old)
        return ticket

    def run_now(self):
        with self.captureOnCommitCallbacks(execute=True):
            return run_retention(self.now)

    def test_disabled_grace_and_daily_limit_remove_nothing(self):
        ticket = self.closed_ticket()
        RetentionPolicy.objects.update(enabled=False)
        self.assertIsNone(self.run_now())
        RetentionPolicy.objects.update(enabled=True, updated_at=self.now - timedelta(hours=23))
        self.assertIsNone(self.run_now())
        RetentionPolicy.objects.update(
            updated_at=self.now - timedelta(days=2), last_run_at=self.now - timedelta(hours=23)
        )
        self.assertIsNone(self.run_now())
        self.assertTrue(Ticket.objects.filter(pk=ticket.pk).exists())

    def test_zero_period_never_disposes_of_that_class(self):
        ticket = self.closed_ticket()
        RetentionPolicy.objects.update(tickets_days=0)
        self.assertEqual(self.run_now()["removed"]["tickets"], 0)
        self.assertTrue(Ticket.objects.filter(pk=ticket.pk).exists())

    def test_expired_ticket_is_erased_with_every_trace_and_file(self):
        ticket = self.closed_ticket()
        comment = Comment.objects.create(
            ticket=ticket, actor=self.owner, body="SEGREDO", visibility="public"
        )
        NotificationRead.objects.create(user=self.tech, event=ticket.events.first())
        with tempfile.TemporaryDirectory() as folder, override_settings(ATTACHMENT_ROOT=folder):
            key = uuid.uuid4()
            stored = path_for(key)
            stored.write_bytes(b"conteudo")
            Attachment.objects.create(
                comment=comment,
                storage_key=key,
                name="a.txt",
                media_type="text/plain",
                size=8,
                sha256="0" * 64,
                status="clean",
            )
            result = self.run_now()
            self.assertFalse(stored.exists())
        self.assertEqual(result["removed"]["tickets"], 1)
        self.assertFalse(Ticket.objects.filter(pk=ticket.pk).exists())
        for model in [Comment, TicketEvent, Attachment, NotificationOutbox, NotificationRead]:
            self.assertFalse(model.objects.exists(), model)
        self.assertEqual(self.owner.pk, type(self.owner).objects.get(pk=self.owner.pk).pk)

    def test_open_recent_and_referenced_tickets_stay(self):
        expired = self.closed_ticket()
        recent = self.closed_ticket(closed_at=self.now - timedelta(days=10))
        opened = self.create()
        linked = self.closed_ticket()
        Ticket.objects.filter(pk=opened.pk).update(related_ticket=linked)
        result = self.run_now()
        self.assertEqual(result["removed"]["tickets"], 1)
        self.assertEqual(result["waiting"]["tickets"], 1)
        self.assertFalse(Ticket.objects.filter(pk=expired.pk).exists())
        self.assertEqual(Ticket.objects.count(), 3)
        self.assertTrue(Ticket.objects.filter(pk=recent.pk).exists())

    def test_deactivation_date_comes_from_the_database(self):
        User = type(self.owner)
        User.objects.filter(pk=self.peer.pk).update(is_active=False)
        self.peer.refresh_from_db()
        self.assertIsNotNone(self.peer.deactivated_at)
        self.peer.first_name = "Outro"
        self.peer.deactivated_at = None
        self.peer.save()
        self.peer.refresh_from_db()
        self.assertIsNotNone(self.peer.deactivated_at)
        User.objects.filter(pk=self.peer.pk).update(is_active=True)
        self.peer.refresh_from_db()
        self.assertIsNone(self.peer.deactivated_at)

    def expire(self, model, pk):
        model.objects.filter(pk=pk).update(is_active=False)

    def test_inactive_records_go_only_when_nothing_references_them(self):
        User = type(self.owner)
        ticket = self.create(user=self.peer)
        spare = User.objects.create(username="spare", email="spare@company.test")
        system = User.objects.create(username="system:test", email="", is_active=True)
        self.expire(User, spare.pk)
        self.expire(User, self.peer.pk)
        self.expire(User, system.pk)
        self.expire(Category, self.category.pk)
        group = SupportGroup.objects.create(name="Sem uso")
        Membership.objects.create(user=self.tech, group=group)
        self.expire(SupportGroup, group.pk)
        area = Department.objects.create(name="Sem uso")
        self.expire(Department, area.pk)
        # The trigger owns the date, so time moves forward instead of the date backward.
        self.now += timedelta(days=400)
        result = self.run_now()
        self.assertFalse(User.objects.filter(pk=spare.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.peer.pk).exists())
        self.assertTrue(User.objects.filter(pk=system.pk).exists())
        self.assertTrue(Category.objects.filter(pk=self.category.pk).exists())
        self.assertFalse(SupportGroup.objects.filter(pk=group.pk).exists())
        self.assertFalse(Department.objects.filter(pk=area.pk).exists())
        self.assertEqual(result["waiting"]["users"], 1)
        self.assertEqual(result["waiting"]["categories"], 1)
        self.assertTrue(Ticket.objects.filter(pk=ticket.pk).exists())

    def test_logs_expire_and_the_run_leaves_only_counts(self):
        old_event = IdentityEvent.objects.create(action="x", subject_id="1")
        IdentityEvent.objects.filter(pk=old_event.pk).update(created_at=self.old)
        kept = IdentityEvent.objects.create(action="y", subject_id="2")
        result = self.run_now()
        self.assertGreaterEqual(result["removed"]["logs"], 1)
        self.assertFalse(IdentityEvent.objects.filter(pk=old_event.pk).exists())
        self.assertTrue(IdentityEvent.objects.filter(pk=kept.pk).exists())
        record = IdentityEvent.objects.get(action="retention.purged")
        self.assertEqual(record.changes, result)
        self.assertIsNotNone(RetentionPolicy.objects.get().last_run_at)

    def test_settings_require_admin_minimum_and_typed_confirmation(self):
        path = "/api/v1/settings/retention/"
        self.closed_ticket()
        data = {
            "enabled": True,
            "tickets_days": 365,
            "users_days": 0,
            "groups_days": 0,
            "categories_days": 0,
            "departments_days": 0,
            "logs_days": 365,
            "confirmation": "REMOVER",
            "reason": "Teste",
        }
        admin = self.client_as(self.admin)
        csrf = admin.get("/api/v1/auth/csrf/").json()["csrfToken"]

        def save(body):
            return admin.patch(path, body, content_type="application/json", HTTP_X_CSRFTOKEN=csrf)

        self.assertEqual(self.client_as(self.manager).get(path).status_code, 403)
        self.assertEqual(save({**data, "tickets_days": 29}).status_code, 400)
        self.assertEqual(save({**data, "confirmation": ""}).status_code, 400)
        self.assertEqual(save({**data, "confirmation": "sim"}).status_code, 400)
        response = save(data)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["preview"]["tickets"], 1)
        self.assertIsNotNone(response.json()["next_run_at"])
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertIsNone(run_retention())
        off = {**data, "enabled": False, "confirmation": ""}
        self.assertIsNone(save(off).json()["next_run_at"])
