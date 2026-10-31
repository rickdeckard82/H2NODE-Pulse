"""Attachment boundaries, real ClamAV and transactional failure on PostgreSQL."""

import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone

from tickets.attachments import LIMIT, path_for, scan_one
from tickets.models import Attachment, AttachmentScan, Comment, NotificationOutbox
from tickets.tests import TicketHelpers


@override_settings(IDENTITY_RATE_LIMIT=100)
class AttachmentTests(TicketHelpers, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_fixtures()

    def setUp(self):
        self.clients = {}
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        override = override_settings(ATTACHMENT_ROOT=self.temp.name)
        override.enable()
        self.addCleanup(override.disable)
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL ROLE pulse_runtime")
        self.ticket = self.create()

    def upload(
        self, user=None, raw=b"Evidence", name="evidence.txt", mime="text/plain", key=None, **extra
    ):
        client = self.client_as(user or self.owner)
        csrf = client.get("/api/v1/auth/csrf/").json()["csrfToken"]
        self.ticket.refresh_from_db()
        data = {
            "expected_version": self.ticket.version,
            "body": "Evidence attached",
            "visibility": "public",
            **extra,
        }
        data["file"] = SimpleUploadedFile(name, raw, content_type=mime)
        return client.post(
            f"/api/v1/tickets/{self.ticket.uuid}/attachments/",
            data,
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_IDEMPOTENCY_KEY=str(key or uuid.uuid4()),
        )

    def download(self, user, item):
        return self.read(self.ticket, user, f"attachments/{item.pk}/download/")

    def test_real_scanner_clean_and_headers(self):
        self.assertEqual(self.upload().status_code, 201)
        item = Attachment.objects.get()
        self.assertEqual(self.download(self.owner, item).status_code, 409)
        self.assertTrue(scan_one())
        item.refresh_from_db()
        self.assertEqual(item.status, "clean")
        response = self.download(self.owner, item)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"Evidence")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertTrue(response["Content-Disposition"].startswith("attachment;"))
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(AttachmentScan.objects.get().actor, "system:antimalware")

    def test_real_eicar_blocked(self):
        # Standard harmless antivirus test signature assembled only in ephemeral storage.
        raw = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
        self.assertEqual(self.upload(raw=raw).status_code, 201)
        scan_one()
        item = Attachment.objects.get()
        self.assertEqual(item.status, "blocked")
        self.assertEqual(self.download(self.owner, item).status_code, 409)

    def test_scanner_down_then_retry(self):
        self.assertEqual(self.upload().status_code, 201)
        with override_settings(CLAMAV_HOST="127.0.0.1", CLAMAV_PORT=1):
            scan_one()
        item = Attachment.objects.get()
        self.assertEqual(item.status, "quarantine")
        self.assertEqual(self.download(self.owner, item).status_code, 409)
        self.assertEqual(AttachmentScan.objects.get().result, "unavailable")
        Attachment.objects.filter(pk=item.pk).update(next_attempt=timezone.now())
        scan_one()
        item.refresh_from_db()
        self.assertEqual(item.status, "clean")

    def test_internal_and_cross_account_isolation(self):
        self.claim(self.ticket)
        self.assertEqual(self.upload(self.tech, visibility="internal").status_code, 201)
        scan_one()
        item = Attachment.objects.get()
        for user in [self.owner, self.peer, self.outsider, self.admin]:
            self.assertEqual(self.download(user, item).status_code, 404)
        self.assertEqual(self.read(self.ticket, self.owner, "attachments/").json()["results"], [])
        self.assertEqual(self.download(self.tech, item).status_code, 200)

    def test_type_spoof_large_and_empty_rejected(self):
        for raw, name, mime in [
            (b"MZ binary", "fake.png", "image/png"),
            (b"<script>alert(1)</script>", "fake.txt", "text/plain"),
            (b"hello", "hello.txt", "application/pdf"),
            (b"x", "evil.exe", "text/plain"),
            (b"", "empty.txt", "text/plain"),
            (b"x" * (LIMIT + 1), "large.txt", "text/plain"),
        ]:
            self.assertEqual(self.upload(raw=raw, name=name, mime=mime).status_code, 400)
        self.assertFalse(Attachment.objects.exists())
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_rollback_cleans_file_comment_and_outbox(self):
        before = NotificationOutbox.objects.count()
        with patch(
            "tickets.attachments.Attachment.objects.create",
            side_effect=RuntimeError("test failure"),
        ):
            with self.assertRaises(RuntimeError):
                self.upload()
        self.assertFalse(Comment.objects.exists())
        self.assertFalse(Attachment.objects.exists())
        self.assertEqual(NotificationOutbox.objects.count(), before)
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_tampered_file_never_downloaded(self):
        self.upload()
        scan_one()
        item = Attachment.objects.get()
        path_for(item.storage_key).write_bytes(b"Modified")
        self.assertEqual(self.download(self.owner, item).status_code, 409)

    def test_idempotent_upload_does_not_duplicate_blob(self):
        key = uuid.uuid4()
        first = self.upload(key=key, expected_version=1)
        second = self.upload(key=key, expected_version=1)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(second["Idempotent-Replayed"], "true")
        self.assertEqual(Attachment.objects.count(), 1)
        self.assertEqual(len(list(Path(self.temp.name).iterdir())), 1)
        self.assertEqual(self.upload(key=key, expected_version=1, raw=b"Other").status_code, 409)
        self.assertEqual(len(list(Path(self.temp.name).iterdir())), 1)

    def test_cross_account_upload_creates_nothing(self):
        self.assertEqual(self.upload(self.peer).status_code, 404)
        self.assertFalse(Attachment.objects.exists())
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_interrupted_scan_rolls_back_and_can_resume(self):
        self.upload()
        with patch(
            "tickets.attachments.AttachmentScan.objects.create",
            side_effect=RuntimeError("interrupted"),
        ):
            with self.assertRaises(RuntimeError):
                scan_one()
        self.assertEqual(Attachment.objects.get().status, "quarantine")
        scan_one()
        self.assertEqual(Attachment.objects.get().status, "clean")
