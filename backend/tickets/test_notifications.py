import uuid
from datetime import timedelta
from unittest.mock import patch
from urllib.error import HTTPError

from django.core import mail
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone

from core.chat_settings import active_webhook
from core.models import ChatConfiguration
from tickets.models import NotificationAttempt, NotificationDelivery, NotificationOutbox
from tickets.notifications import RetryableDelivery, check_one, deliver_one
from tickets.tests import TicketHelpers


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
