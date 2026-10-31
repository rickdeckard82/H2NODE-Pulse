"""Operator bootstrap and authenticated configuration on real PostgreSQL."""

import ipaddress
import os
import socket
import socketserver
import ssl
import tempfile
import threading
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import PropertyMock, patch

import pyotp
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from core.identity import cipher, issue_token
from core.identity_mail import deliver_one
from core.models import AllowedDomain, IdentityEvent, IdentityMail, SmtpConfiguration, User
from core.smtp_settings import check_destination, delivery_configuration, validate_host
from core.test_identity import PASSWORD, HTTPHelpers


class BootstrapTests(TestCase):
    def provision(self, **values):
        env = {
            "BOOTSTRAP_ADMIN_ENABLED": "true",
            "BOOTSTRAP_ADMIN_EMAIL": "operator@company.test",
            "BOOTSTRAP_ADMIN_PASSWORD": PASSWORD,
            "BOOTSTRAP_ADMIN_TRUST_EMAIL": "true",
            **values,
        }
        out = StringIO()
        with patch.dict(os.environ, env):
            call_command("initialize_admin", stdout=out)
        self.assertNotIn(PASSWORD, out.getvalue())

    def test_disabled_and_no_default_password(self):
        self.provision(BOOTSTRAP_ADMIN_ENABLED="false")
        self.assertFalse(User.objects.exists())
        with self.assertRaises(CommandError):
            self.provision(BOOTSTRAP_ADMIN_PASSWORD="")
        self.assertFalse(User.objects.exists())

    def test_creation_and_restart_preserve_password_and_mfa(self):
        self.provision()
        user = User.objects.get()
        self.assertTrue(user.email_verified_at)
        self.assertTrue(user.check_password(PASSWORD))
        self.assertFalse(user.mfa_enabled)
        user.mfa_enabled = True
        user.save()
        saved = user.password
        self.provision(BOOTSTRAP_ADMIN_PASSWORD="a different value")
        user.refresh_from_db()
        self.assertEqual(user.password, saved)
        self.assertTrue(user.mfa_enabled)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(IdentityEvent.objects.filter(action="bootstrap.admin_created").count(), 1)

    def test_existing_unverified_operator_admin_can_be_trusted_explicitly(self):
        self.provision(BOOTSTRAP_ADMIN_TRUST_EMAIL="false")
        user = User.objects.get()
        saved = user.password
        self.assertIsNone(user.email_verified_at)
        self.provision(BOOTSTRAP_ADMIN_PASSWORD="")
        user.refresh_from_db()
        self.assertTrue(user.email_verified_at)
        self.assertEqual(saved, user.password)
        self.assertTrue(IdentityEvent.objects.filter(action="bootstrap.email_trusted").exists())

    def test_no_promotion_reactivation_or_extra_admin(self):
        User.objects.create_user(
            username="ordinary", email="operator@company.test", password=PASSWORD
        )
        with self.assertRaises(CommandError):
            self.provision()
        self.assertEqual(User.objects.get().role, "collaborator")
        self.provision(BOOTSTRAP_ADMIN_EMAIL="initial@company.test")
        self.provision(BOOTSTRAP_ADMIN_EMAIL="second@company.test")
        self.assertEqual(User.objects.filter(role="admin").count(), 1)
        User.objects.filter(role="admin").update(is_active=False)
        with self.assertRaises(CommandError):
            self.provision(BOOTSTRAP_ADMIN_EMAIL="initial@company.test")


@override_settings(IDENTITY_RATE_LIMIT=100)
class ConfigurationTests(HTTPHelpers, TestCase):
    @classmethod
    def setUpTestData(cls):
        AllowedDomain.objects.create(domain="company.test")
        cls.admin = User.objects.create_user(
            username="admin",
            email="admin@company.test",
            password=PASSWORD,
            role="admin",
            email_verified_at=timezone.now(),
            mfa_enabled=True,
            mfa_secret=cipher().encrypt(pyotp.random_base32().encode()).decode(),
        )
        cls.user = User.objects.create_user(
            username="user",
            email="user@company.test",
            password=PASSWORD,
            email_verified_at=timezone.now(),
        )

    def setUp(self):
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL ROLE pulse_runtime")

    def test_admin_only_csrf_and_secret_never_returned(self):
        user_client = self.login(self.user)
        self.assertEqual(user_client.get("/api/v1/settings/smtp/").status_code, 403)
        self.assertEqual(
            self.patch(user_client, "/api/v1/settings/smtp/", {"reason": "test"}).status_code, 403
        )
        client = self.login(self.admin)
        self.assertEqual(
            client.patch("/api/v1/settings/smtp/", {}, content_type="application/json").status_code,
            403,
        )
        response = self.patch(
            client,
            "/api/v1/settings/smtp/",
            {
                "host": "smtp.company.test",
                "port": 465,
                "security": "ssl",
                "username": "mailer",
                "password": PASSWORD,
                "from_email": "service@company.test",
                "enabled": True,
                "reason": "Synthetic configuration",
            },
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["password_configured"])
        row = SmtpConfiguration.objects.get()
        self.assertNotEqual(row.encrypted_password, PASSWORD)
        self.assertEqual(cipher().decrypt(row.encrypted_password.encode()).decode(), PASSWORD)
        self.assertNotIn(PASSWORD, response.content.decode())
        self.assertNotIn(row.encrypted_password, response.content.decode())
        self.assertNotIn(PASSWORD, str(list(IdentityEvent.objects.values())))
        response = self.patch(
            client,
            "/api/v1/settings/smtp/",
            {"reason": "keep password", "password": "", "enabled": False},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["password_configured"])
        self.assertIsNone(delivery_configuration())
        response = self.patch(
            client, "/api/v1/settings/smtp/", {"reason": "remove password", "clear_password": True}
        )
        self.assertFalse(response.json()["password_configured"])

    def test_invalid_destinations_and_weak_transport_rejected(self):
        client = self.login(self.admin)
        for data in [
            {"host": "http://metadata/"},
            {"host": "127.0.0.1"},
            {"host": "169.254.169.254"},
            {"port": 80},
            {"security": "none"},
            {"enabled": True},
        ]:
            response = self.patch(client, "/api/v1/settings/smtp/", {**data, "reason": "test"})
            self.assertEqual(response.status_code, 400, response.content)
        with override_settings(SMTP_ALLOWED_HOSTS=["smtp.allowed.test"]):
            with self.assertRaises(ValidationError):
                validate_host("smtp.other.test")
        with patch(
            "core.smtp_settings.socket.getaddrinfo",
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 587))],
        ):
            with self.assertRaises(OSError):
                check_destination("smtp.company.test", 587)

    def test_failed_delivery_retains_queue_and_configuration_can_be_disabled(self):
        issue_token(self.user, "verify")
        SmtpConfiguration.objects.create(
            enabled=True, host="smtp.company.test", from_email="service@company.test"
        )
        with patch("core.smtp_settings.socket.getaddrinfo", side_effect=OSError("Unavailable")):
            self.assertTrue(deliver_one())
        mail = IdentityMail.objects.get()
        self.assertEqual(mail.attempts, 1)
        self.assertIsNone(mail.sent_at)
        SmtpConfiguration.objects.update(enabled=False)
        self.assertIsNone(delivery_configuration())

    def test_trust_domain_configuration_does_not_auto_verify_signup(self):
        client = self.login(self.admin)
        response = self.post(
            client,
            "/api/v1/settings/domains/",
            {"domain": "new.company.test", "reason": "Approved domain"},
        )
        self.assertEqual(response.status_code, 201)
        anonymous = self.client_for_test()
        response = self.post(
            anonymous,
            "/api/v1/auth/register/",
            {"name": "New User", "email": "new@new.company.test", "password": PASSWORD},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(User.objects.get(email="new@new.company.test").email_verified_at)

    def test_database_configuration_delivers_over_real_local_tls(self):
        received = []

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.wfile.write(b"220 synthetic.test ESMTP\r\n")
                while line := self.rfile.readline():
                    verb = line.split(b" ", 1)[0].strip().upper()
                    if verb in {b"EHLO", b"HELO"}:
                        self.wfile.write(b"250 synthetic.test\r\n")
                    elif verb == b"DATA":
                        self.wfile.write(b"354 Continue\r\n")
                        body = b""
                        while (chunk := self.rfile.readline()) != b".\r\n":
                            if not chunk:
                                return
                            body += chunk
                        received.append(body)
                        self.wfile.write(b"250 accepted\r\n")
                    elif verb == b"QUIT":
                        self.wfile.write(b"221 bye\r\n")
                        return
                    else:
                        self.wfile.write(b"250 OK\r\n")

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "synthetic.test")])
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(timezone.now() - timedelta(minutes=1))
            .not_valid_after(timezone.now() + timedelta(hours=1))
            .add_extension(
                x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )
        with tempfile.TemporaryDirectory() as directory:
            cert_path, key_path = Path(directory) / "cert.pem", Path(directory) / "key.pem"
            cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            key_path.write_bytes(
                key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
            server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server_context.load_cert_chain(cert_path, key_path)
            client_context = ssl.create_default_context(cafile=str(cert_path))
            with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:
                server.socket = server_context.wrap_socket(server.socket, server_side=True)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    SmtpConfiguration.objects.create(
                        enabled=True,
                        host="127.0.0.1",
                        port=server.server_address[1],
                        security="ssl",
                        from_email="service@company.test",
                    )
                    issue_token(self.user, "verify")
                    # Only the test fixture bypasses destination policy for loopback;
                    # TLS certificate verification remains enabled with its temporary CA.
                    with (
                        patch("core.smtp_settings.check_destination"),
                        patch(
                            "django.core.mail.backends.smtp.EmailBackend.ssl_context",
                            new_callable=PropertyMock,
                            return_value=client_context,
                        ),
                    ):
                        self.assertTrue(deliver_one())
                    self.assertEqual(len(received), 1)
                    self.assertIsNotNone(IdentityMail.objects.get().sent_at)
                    self.assertEqual(IdentityMail.objects.get().encrypted_body, "")
                finally:
                    server.shutdown()
                    thread.join()
