"""Integration tests: real PostgreSQL, HTTP/CSRF sessions, concurrency and local SMTP.

No corporate mailbox is contacted. All fixture identities use reserved .test domains.
"""

import base64
import secrets
import socketserver
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from importlib import import_module
from io import StringIO
from unittest.mock import patch

import pyotp
from django.apps import apps
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from core import identity
from core.identity_mail import cleanup, deliver_one
from core.models import (
    AllowedDomain,
    AuthRateBucket,
    Department,
    IdentityEvent,
    IdentityMail,
    IdentityToken,
    Membership,
    SupportGroup,
    User,
)

PASSWORD = "Synthetic!Only-For-Tests-92716"
NEW_PASSWORD = "Synthetic!Replaced-Password-48271"


class HTTPHelpers:
    def client_for_test(self):
        return Client(enforce_csrf_checks=True)

    def post(self, client, path, data=None):
        csrf = client.get("/api/v1/auth/csrf/").json()["csrfToken"]
        return client.post(path, data or {}, content_type="application/json", HTTP_X_CSRFTOKEN=csrf)

    def patch(self, client, path, data):
        csrf = client.get("/api/v1/auth/csrf/").json()["csrfToken"]
        return client.patch(path, data, content_type="application/json", HTTP_X_CSRFTOKEN=csrf)

    def login(self, user, client=None, password=PASSWORD):
        client = client or self.client_for_test()
        response = self.post(
            client, "/api/v1/auth/login/", {"email": user.email, "password": password}
        )
        self.assertEqual(response.status_code, 200, response.content)
        if user.privileged:
            code = pyotp.TOTP(identity.cipher().decrypt(user.mfa_secret.encode()).decode()).now()
            response = self.post(client, "/api/v1/auth/mfa/verify/", {"code": code})
            self.assertEqual(response.status_code, 200, response.content)
        return client

    def latest_token(self, user, purpose):
        token = IdentityToken.objects.filter(user=user, purpose=purpose).latest("id")
        raw = identity.cipher().decrypt(token.identitymail.encrypted_body.encode()).decode()
        return token, raw


@override_settings(IDENTITY_RATE_LIMIT=100)
class IdentityTests(HTTPHelpers, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.domain = AllowedDomain.objects.create(domain="company.test")
        cls.department = Department.objects.create(name="Comercial")
        cls.group = SupportGroup.objects.create(name="Suporte")
        cls.hashed = make_password(PASSWORD)
        cls.alice = cls.make_user("alice")
        cls.bob = cls.make_user("bob")
        cls.admin = cls.make_user("admin", User.Role.ADMIN)

    @classmethod
    def make_user(cls, name, role=User.Role.COLLABORATOR):
        raw = pyotp.random_base32()
        return User.objects.create(
            username=name,
            email=f"{name}@company.test",
            password=cls.hashed,
            department=cls.department,
            email_verified_at=timezone.now(),
            role=role,
            mfa_enabled=role != User.Role.COLLABORATOR,
            mfa_secret=identity.cipher().encrypt(raw.encode()).decode(),
        )

    def setUp(self):
        self.client = self.client_for_test()

    def test_registration_confirmation_login_logout_and_argon2id(self):
        data = {"email": " New@COMPANY.test ", "name": "Pessoa sintética", "password": PASSWORD}
        response = self.post(self.client, "/api/v1/auth/register/", data)
        self.assertEqual(response.status_code, 200)
        user = User.objects.get(email="new@company.test")
        self.assertEqual(
            IdentityMail.objects.filter(token__user=user, token__purpose="verify").count(),
            1,
        )
        self.assertIsNone(IdentityMail.objects.get(token__user=user).sent_at)
        self.assertTrue(user.password.startswith("argon2$argon2id$"))
        self.assertEqual(user.role, User.Role.COLLABORATOR)
        self.assertFalse(user.is_staff or user.is_superuser)
        login_data = {"email": user.email, "password": PASSWORD}
        self.assertEqual(self.post(self.client, "/api/v1/auth/login/", login_data).status_code, 403)
        token, raw = self.latest_token(user, "verify")
        self.assertNotIn(raw, response.content.decode())
        self.assertNotEqual(token.digest, raw)
        self.assertEqual(
            self.post(self.client, "/api/v1/auth/confirm/", {"token": raw}).status_code, 200
        )
        self.assertEqual(
            self.post(self.client, "/api/v1/auth/confirm/", {"token": raw}).status_code, 400
        )
        self.login(user, self.client)
        self.assertEqual(self.client.get("/api/v1/auth/me/").json()["id"], user.pk)
        self.assertEqual(self.client.get("/api/v1/auth/me/")["Cache-Control"], "no-store")
        self.assertTrue(self.client.cookies[settings.SESSION_COOKIE_NAME]["httponly"])
        self.assertEqual(self.post(self.client, "/api/v1/auth/logout/").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 403)

    def test_domain_exact_match_absent_inactive_and_no_enumeration(self):
        expected = None
        for email in [
            "x@evil.test",
            "x@company.test.evil.test",
            "x@sub.company.test",
            self.alice.email,
        ]:
            response = self.post(
                self.client,
                "/api/v1/auth/register/",
                {
                    "email": email,
                    "name": "Synthetic",
                    "password": PASSWORD,
                },
            )
            self.assertEqual(response.status_code, 200)
            expected = expected or response.json()
            self.assertEqual(response.json(), expected)
        self.assertEqual(User.objects.count(), 3)
        AllowedDomain.objects.all().delete()
        response = self.post(
            self.client,
            "/api/v1/auth/register/",
            {
                "email": "new@company.test",
                "name": "Synthetic",
                "password": PASSWORD,
            },
        )
        self.assertEqual(response.json(), expected)
        self.assertEqual(User.objects.count(), 3)

    def test_registration_rejects_privilege_and_weak_password_fields(self):
        data = {"email": "new@company.test", "name": "Synthetic", "password": PASSWORD}
        for field, value in [("role", "admin"), ("is_staff", True), ("is_superuser", True)]:
            self.assertEqual(
                self.post(
                    self.client,
                    "/api/v1/auth/register/",
                    {
                        **data,
                        field: value,
                    },
                ).status_code,
                400,
            )
        self.assertEqual(
            self.post(
                self.client,
                "/api/v1/auth/register/",
                {
                    **data,
                    "password": "12345678",
                },
            ).status_code,
            400,
        )
        self.assertEqual(User.objects.count(), 3)

    def test_expired_wrong_purpose_and_removed_domain_tokens_fail(self):
        identity.issue_token(self.alice, "reset")
        token, raw = self.latest_token(self.alice, "reset")
        error = self.post(self.client, "/api/v1/auth/confirm/", {"token": raw})
        self.assertEqual(error.status_code, 400)
        self.assertEqual(error.json()["detail"], "Dados inválidos.")
        self.assertIn("errors", error.json())
        self.assertEqual(
            self.post(self.client, "/api/v1/auth/confirm/", {"token": raw}).status_code, 400
        )
        token.expires_at = timezone.now() - timedelta(seconds=1)
        token.save()
        self.assertEqual(
            self.post(
                self.client,
                "/api/v1/auth/reset/",
                {
                    "token": raw,
                    "password": NEW_PASSWORD,
                },
            ).status_code,
            400,
        )
        identity.issue_token(self.alice, "verify")
        _, raw = self.latest_token(self.alice, "verify")
        self.domain.is_active = False
        self.domain.save()
        self.assertEqual(
            self.post(self.client, "/api/v1/auth/confirm/", {"token": raw}).status_code, 400
        )

    def test_resend_invalidates_previous_token(self):
        self.alice.email_verified_at = None
        self.alice.save()
        self.post(self.client, "/api/v1/auth/resend/", {"email": self.alice.email})
        _, first = self.latest_token(self.alice, "verify")
        self.post(self.client, "/api/v1/auth/resend/", {"email": self.alice.email})
        _, second = self.latest_token(self.alice, "verify")
        self.assertEqual(
            self.post(self.client, "/api/v1/auth/confirm/", {"token": first}).status_code, 400
        )
        self.assertEqual(
            self.post(self.client, "/api/v1/auth/confirm/", {"token": second}).status_code, 200
        )

    def test_authenticated_password_change_requires_current_and_revokes_session(self):
        client = self.login(self.alice)
        self.assertEqual(
            self.post(
                client,
                "/api/v1/auth/password/",
                {"current_password": "invalid", "new_password": NEW_PASSWORD},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.post(
                client,
                "/api/v1/auth/password/",
                {"current_password": PASSWORD, "new_password": PASSWORD},
            ).status_code,
            400,
        )
        self.assertEqual(
            self.post(
                client,
                "/api/v1/auth/password/",
                {"current_password": PASSWORD, "new_password": NEW_PASSWORD},
            ).status_code,
            200,
        )
        self.assertEqual(client.get("/api/v1/auth/me/").status_code, 403)
        self.assertEqual(
            self.post(
                self.client_for_test(),
                "/api/v1/auth/login/",
                {
                    "email": self.alice.email,
                    "password": PASSWORD,
                },
            ).status_code,
            403,
        )
        self.login(self.alice, self.client_for_test(), password=NEW_PASSWORD)
        self.assertTrue(
            IdentityEvent.objects.filter(
                actor=self.alice, action="account.password_changed"
            ).exists()
        )

    def test_reset_is_single_use_and_revokes_all_sessions(self):
        first, second = self.login(self.alice), self.login(self.alice)
        result = self.post(self.client, "/api/v1/auth/forgot/", {"email": self.alice.email})
        other = self.post(self.client, "/api/v1/auth/forgot/", {"email": "absent@company.test"})
        self.assertEqual(result.json(), other.json())
        _, raw = self.latest_token(self.alice, "reset")
        data = {"token": raw, "password": NEW_PASSWORD}
        self.assertEqual(self.post(self.client, "/api/v1/auth/reset/", data).status_code, 200)
        self.assertEqual(self.post(self.client, "/api/v1/auth/reset/", data).status_code, 400)
        for client in [first, second]:
            self.assertEqual(client.get("/api/v1/auth/me/").status_code, 403)
        self.login(self.alice, password=NEW_PASSWORD)
        self.assertEqual(
            self.post(
                self.client,
                "/api/v1/auth/login/",
                {
                    "email": self.alice.email,
                    "password": PASSWORD,
                },
            ).status_code,
            403,
        )

    def test_profile_updates_name_and_avatar_but_never_email(self):
        client = self.login(self.alice)
        photo = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xe0fake").decode()
        response = self.patch(
            client, "/api/v1/auth/me/", {"first_name": "Alice B", "avatar": photo}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["avatar"], photo)
        self.assertEqual(client.get("/api/v1/auth/me/").json()["first_name"], "Alice B")
        self.assertNotIn(
            "avatar", self.login(self.admin).get("/api/v1/users/").json()["results"][0]
        )
        for data in [
            {"email": "changed@company.test"},
            {"avatar": "data:image/svg+xml;base64,PHN2Zz4="},
            {"avatar": "data:image/jpeg;base64," + base64.b64encode(b"<svg>").decode()},
            {"avatar": "data:image/jpeg;base64,!!!"},
            {"first_name": ""},
        ]:
            self.assertEqual(self.patch(client, "/api/v1/auth/me/", data).status_code, 400, data)
        self.assertEqual(self.post(client, "/api/v1/auth/email/", {}).status_code, 404)
        self.assertEqual(
            self.patch(client, "/api/v1/auth/me/", {"avatar": ""}).json()["avatar"], ""
        )
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.email, "alice@company.test")
        self.assertTrue(
            IdentityEvent.objects.filter(
                action="account.profile_updated", actor=self.alice
            ).exists()
        )

    def test_csrf_login_register_logout_and_hostile_origin(self):
        data = {"email": self.alice.email, "password": PASSWORD}
        self.assertEqual(self.client.post("/api/v1/auth/login/", data).status_code, 403)
        self.assertEqual(self.client.post("/api/v1/auth/register/", data).status_code, 403)
        csrf = self.client.get("/api/v1/auth/csrf/").json()["csrfToken"]
        self.assertEqual(
            self.client.post(
                "/api/v1/auth/login/",
                data,
                content_type="application/json",
                HTTP_X_CSRFTOKEN=csrf,
                HTTP_ORIGIN="https://evil.test",
            ).status_code,
            403,
        )
        client = self.login(self.alice)
        self.assertEqual(client.post("/api/v1/auth/logout/").status_code, 403)
        self.assertEqual(client.get("/api/v1/auth/me/").status_code, 200)

    @override_settings(IDENTITY_RATE_LIMIT=2)
    def test_rate_limit_survives_invalid_credentials_and_session_rotation(self):
        for _ in range(2):
            self.assertEqual(
                self.post(
                    self.client_for_test(),
                    "/api/v1/auth/login/",
                    {
                        "email": self.alice.email,
                        "password": "wrong",
                    },
                ).status_code,
                403,
            )
        response = self.post(
            self.client_for_test(),
            "/api/v1/auth/login/",
            {
                "email": self.alice.email.upper(),
                "password": PASSWORD,
            },
        )
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response)
        self.assertNotIn(self.alice.email, str(list(AuthRateBucket.objects.values())))

    def test_mfa_setup_replay_and_single_use_recovery(self):
        user = self.make_user("tech", User.Role.TECHNICIAN)
        user.mfa_enabled, user.mfa_secret = False, ""
        user.save()
        response = self.post(
            self.client, "/api/v1/auth/login/", {"email": user.email, "password": PASSWORD}
        )
        self.assertEqual(response.json()["status"], "mfa_setup_required")
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 403)
        setup = self.post(self.client, "/api/v1/auth/mfa/setup/").json()
        self.assertIn("otpauth://totp/", setup["uri"])
        user.refresh_from_db()
        self.assertNotIn(setup["secret"], user.mfa_secret)
        code = pyotp.TOTP(setup["secret"]).now()
        response = self.post(self.client, "/api/v1/auth/mfa/verify/", {"code": code})
        self.assertEqual(response.status_code, 200)
        recovery = response.json()["recovery_codes"][0]
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 200)
        user.refresh_from_db()
        self.assertNotIn(recovery, user.recovery_hashes)
        self.post(self.client, "/api/v1/auth/login/", {"email": user.email, "password": PASSWORD})
        self.assertEqual(
            self.post(self.client, "/api/v1/auth/mfa/verify/", {"code": code}).status_code, 403
        )
        self.assertEqual(
            self.post(self.client, "/api/v1/auth/mfa/verify/", {"code": recovery}).status_code, 200
        )
        self.post(self.client, "/api/v1/auth/login/", {"email": user.email, "password": PASSWORD})
        self.assertEqual(
            self.post(self.client, "/api/v1/auth/mfa/verify/", {"code": recovery}).status_code, 403
        )

    def test_expired_mfa_challenge_and_inactive_account_fail(self):
        self.post(
            self.client, "/api/v1/auth/login/", {"email": self.admin.email, "password": PASSWORD}
        )
        session = self.client.session
        pending = session["pending_identity"]
        pending["at"] -= 301
        session["pending_identity"] = pending
        session.save()
        self.assertEqual(
            self.post(self.client, "/api/v1/auth/mfa/verify/", {"code": "123456"}).status_code, 403
        )
        self.alice.is_active = False
        self.alice.save()
        self.assertEqual(
            self.post(
                self.client,
                "/api/v1/auth/login/",
                {
                    "email": self.alice.email,
                    "password": PASSWORD,
                },
            ).status_code,
            403,
        )

    def test_mfa_replacement_requires_recent_factor_and_revokes_old_codes(self):
        old_code = secrets.token_hex(10)
        self.admin.recovery_hashes = [identity.digest(old_code)]
        self.admin.save()
        admin = self.login(self.admin)
        other = self.client_for_test()
        self.post(other, "/api/v1/auth/login/", {"email": self.admin.email, "password": PASSWORD})
        self.assertEqual(
            self.post(other, "/api/v1/auth/mfa/verify/", {"code": old_code}).status_code, 200
        )
        response = self.post(other, "/api/v1/auth/mfa/replace/", {"password": "incorrect"})
        self.assertEqual(response.status_code, 403)
        response = self.post(other, "/api/v1/auth/mfa/replace/", {"password": PASSWORD})
        self.assertEqual(response.status_code, 200)
        raw = response.json()["secret"]
        response = self.post(
            other, "/api/v1/auth/mfa/replace/confirm/", {"code": pyotp.TOTP(raw).now()}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["recovery_codes"]), 8)
        self.assertEqual(admin.get("/api/v1/auth/me/").status_code, 403)
        self.assertEqual(other.get("/api/v1/auth/me/").status_code, 200)
        self.admin.refresh_from_db()
        self.assertNotIn(identity.digest(old_code), self.admin.recovery_hashes)
        self.assertEqual(identity.cipher().decrypt(self.admin.mfa_secret.encode()).decode(), raw)
        session = other.session
        session["mfa_at"] -= 301
        session.save()
        self.assertEqual(
            self.post(other, "/api/v1/auth/mfa/replace/", {"password": PASSWORD}).status_code, 403
        )

    @override_settings(IDENTITY_RATE_LIMIT=2)
    def test_mfa_rate_limit_persists_failed_factors(self):
        self.post(
            self.client, "/api/v1/auth/login/", {"email": self.admin.email, "password": PASSWORD}
        )
        for _ in range(2):
            self.assertEqual(
                self.post(
                    self.client,
                    "/api/v1/auth/mfa/verify/",
                    {
                        "code": "invalid",
                    },
                ).status_code,
                403,
            )
        self.assertEqual(
            self.post(
                self.client,
                "/api/v1/auth/mfa/verify/",
                {
                    "code": "invalid",
                },
            ).status_code,
            429,
        )

    def test_unconfirmed_account_cannot_be_promoted(self):
        self.alice.email_verified_at = None
        self.alice.save()
        admin = self.login(self.admin)
        self.assertEqual(
            self.patch(
                admin,
                f"/api/v1/users/{self.alice.pk}/",
                {
                    "role": "admin",
                    "reason": "Synthetic",
                },
            ).status_code,
            400,
        )

    @override_settings(SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True)
    def test_secure_cookie_flags(self):
        client = self.login(self.alice)
        cookie = client.cookies[settings.SESSION_COOKIE_NAME]
        self.assertTrue(cookie["secure"])
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        self.assertTrue(client.cookies[settings.CSRF_COOKIE_NAME]["secure"])

    def test_own_profile_only_even_same_department_and_staff_flag(self):
        self.alice.is_staff = self.alice.is_superuser = True
        self.alice.save()
        client = self.login(self.alice)
        self.assertEqual(client.get("/api/v1/users/").json()["count"], 1)
        self.assertEqual(client.get(f"/api/v1/users/{self.bob.pk}/").status_code, 404)
        self.assertEqual(client.get("/api/v1/schema/").status_code, 403)
        self.assertEqual(
            self.patch(
                client,
                f"/api/v1/users/{self.alice.pk}/",
                {
                    "role": "admin",
                    "reason": "attempt",
                },
            ).status_code,
            403,
        )
        self.assertEqual(
            self.post(client, "/api/v1/groups/", {"name": "Forbidden"}).status_code, 403
        )
        self.assertEqual(client.get("/api/v1/settings/domains/").status_code, 403)

    def test_retired_privacy_role_becomes_collaborator_and_loses_sessions(self):
        user = self.make_user("retired", "privacy")
        version = user.session_version
        import_module("core.migrations.0009_simplify_roles").demote_privacy(apps, None)
        user.refresh_from_db()
        self.assertEqual(user.role, User.Role.COLLABORATOR)
        self.assertEqual(user.session_version, version + 1)

    def test_role_matrix_has_no_implicit_administration(self):
        for role in [User.Role.TECHNICIAN, User.Role.MANAGER]:
            user = self.make_user(role, role)
            client = self.login(user)
            self.assertEqual(client.get("/api/v1/users/").json()["count"], 1)
            self.assertEqual(client.get("/api/v1/settings/domains/").status_code, 403)
            self.assertEqual(
                self.post(client, "/api/v1/departments/", {"name": "Forbidden"}).status_code, 403
            )
            self.assertEqual(
                self.post(
                    client,
                    "/api/v1/memberships/",
                    {
                        "user": user.pk,
                        "group": self.group.pk,
                    },
                ).status_code,
                403,
            )
        admin = self.login(self.admin)
        self.assertEqual(admin.get("/api/v1/users/").json()["count"], 5)
        self.assertEqual(admin.get("/api/v1/settings/domains/").status_code, 200)

    def test_promotion_revokes_session_requires_mfa_and_audits(self):
        client, admin = self.login(self.alice), self.login(self.admin)
        response = self.patch(
            admin,
            f"/api/v1/users/{self.alice.pk}/",
            {
                "role": "technician",
                "reason": "Equipe de suporte sintética",
            },
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(client.get("/api/v1/auth/me/").status_code, 403)
        result = self.post(
            client, "/api/v1/auth/login/", {"email": self.alice.email, "password": PASSWORD}
        )
        self.assertEqual(result.json()["status"], "mfa_setup_required")
        event = IdentityEvent.objects.get(action="account.updated")
        self.assertEqual(event.actor_id, self.admin.pk)
        self.assertEqual(event.changes["role"], {"from": "collaborator", "to": "technician"})
        self.assertIsNotNone(event.created_at.tzinfo)

    def test_deactivation_and_revoke_all_are_immediate(self):
        first, second = self.login(self.alice), self.login(self.alice)
        self.assertEqual(self.post(first, "/api/v1/auth/revoke/").status_code, 200)
        self.assertEqual(second.get("/api/v1/auth/me/").status_code, 403)
        client, admin = self.login(self.alice), self.login(self.admin)
        self.assertEqual(
            self.patch(
                admin,
                f"/api/v1/users/{self.alice.pk}/",
                {
                    "is_active": False,
                    "reason": "Desligamento sintético",
                },
            ).status_code,
            200,
        )
        self.assertEqual(client.get("/api/v1/auth/me/").status_code, 403)

    def test_last_admin_cannot_be_removed_by_account_or_domain(self):
        admin = self.login(self.admin)
        for data in [{"is_active": False}, {"role": "collaborator"}]:
            self.assertEqual(
                self.patch(
                    admin,
                    f"/api/v1/users/{self.admin.pk}/",
                    {
                        **data,
                        "reason": "Synthetic",
                    },
                ).status_code,
                400,
            )
        self.assertEqual(
            self.patch(
                admin,
                f"/api/v1/settings/domains/{self.domain.pk}/",
                {
                    "is_active": False,
                    "reason": "Synthetic",
                },
            ).status_code,
            400,
        )
        csrf = admin.get("/api/v1/auth/csrf/").json()["csrfToken"]
        self.assertEqual(
            admin.delete(f"/api/v1/users/{self.admin.pk}/", HTTP_X_CSRFTOKEN=csrf).status_code, 405
        )

    def test_removed_domain_disables_accounts_and_requires_explicit_reactivation(self):
        AllowedDomain.objects.create(domain="admins.test")
        self.admin.email = "admin@admins.test"
        self.admin.save()
        client, admin = self.login(self.alice), self.login(self.admin)
        self.assertEqual(
            self.patch(
                admin,
                f"/api/v1/settings/domains/{self.domain.pk}/",
                {
                    "is_active": False,
                    "reason": "Domínio retirado",
                },
            ).status_code,
            200,
        )
        self.assertEqual(client.get("/api/v1/auth/me/").status_code, 403)
        self.alice.refresh_from_db()
        self.assertFalse(self.alice.is_active)
        self.patch(
            admin,
            f"/api/v1/settings/domains/{self.domain.pk}/",
            {
                "is_active": True,
                "reason": "Domínio restaurado",
            },
        )
        self.alice.refresh_from_db()
        self.assertFalse(self.alice.is_active)

    def test_admin_creates_collaborator_who_sets_password_through_invite(self):
        admin, alice = self.login(self.admin), self.login(self.alice)
        data = {"email": "Nova@company.test", "first_name": "Nova", "reason": "Admissão"}
        self.assertEqual(self.post(alice, "/api/v1/users/", data).status_code, 403)
        for bad in [{"email": "x@other.test"}, {"email": self.alice.email}, {"role": "admin"}]:
            self.assertEqual(
                self.post(admin, "/api/v1/users/", {**data, **bad}).status_code, 400, bad
            )
        response = self.post(admin, "/api/v1/users/", data)
        self.assertEqual(response.status_code, 201, response.content)
        user = User.objects.get(email="nova@company.test")
        self.assertEqual(user.role, User.Role.COLLABORATOR)
        self.assertIsNone(user.email_verified_at)
        self.assertFalse(user.has_usable_password())
        token, raw = self.latest_token(user, "invite")
        self.assertGreater(token.expires_at, timezone.now() + timedelta(hours=71))
        # Forgot-password on a never-activated account re-sends the invite, not a reset.
        self.post(self.client, "/api/v1/auth/forgot/", {"email": user.email})
        token, raw = self.latest_token(user, "invite")
        self.assertFalse(IdentityToken.objects.filter(user=user, purpose="reset").exists())
        reset = {"token": raw, "password": NEW_PASSWORD}
        self.assertEqual(self.post(self.client, "/api/v1/auth/reset/", reset).status_code, 200)
        user.refresh_from_db()
        self.assertIsNotNone(user.email_verified_at)
        self.login(user, password=NEW_PASSWORD)
        self.assertTrue(IdentityEvent.objects.filter(action="account.created").exists())

    def test_area_change_keeps_pending_code_but_role_change_revokes_it(self):
        data = {"email": "late@company.test", "name": "Pessoa", "password": PASSWORD}
        self.assertEqual(self.post(self.client, "/api/v1/auth/register/", data).status_code, 200)
        user = User.objects.get(email="late@company.test")
        _, raw = self.latest_token(user, "verify")
        admin = self.login(self.admin)
        path = f"/api/v1/users/{user.pk}/"
        # Signing up again before confirming resends a code and voids the previous one.
        self.assertEqual(self.post(self.client, "/api/v1/auth/register/", data).status_code, 200)
        old = raw
        _, raw = self.latest_token(user, "verify")
        self.assertNotEqual(old, raw)
        self.assertEqual(
            self.post(self.client, "/api/v1/auth/confirm/", {"token": old}).status_code, 400
        )
        update = {"department": self.department.pk, "reason": "Área"}
        self.assertEqual(self.patch(admin, path, update).status_code, 200)
        self.assertEqual(
            self.post(self.client, "/api/v1/auth/confirm/", {"token": raw}).status_code, 200
        )
        user.refresh_from_db()
        self.assertIsNotNone(user.email_verified_at)
        client = self.login(user)
        self.patch(admin, path, {"role": "technician", "reason": "Promoção"})
        self.assertEqual(client.get("/api/v1/auth/me/").status_code, 403)

    def test_domain_deletion_requires_reason_admin_and_disables_accounts(self):
        admin, client = self.login(self.admin), self.login(self.alice)
        path = f"/api/v1/settings/domains/{self.domain.pk}/"

        def delete(who, data):
            csrf = who.get("/api/v1/auth/csrf/").json()["csrfToken"]
            return who.delete(path, data, content_type="application/json", HTTP_X_CSRFTOKEN=csrf)

        self.assertEqual(delete(client, {"reason": "Sem permissão"}).status_code, 403)
        self.assertEqual(delete(admin, {}).status_code, 400)
        # The only administrator belongs to this domain, so removal is refused.
        self.assertEqual(delete(admin, {"reason": "Encerrado"}).status_code, 400)
        AllowedDomain.objects.create(domain="admins.test")
        self.admin.email = "admin@admins.test"
        self.admin.save()
        admin = self.login(self.admin)
        self.assertEqual(delete(admin, {"reason": "Encerrado"}).status_code, 204)
        self.assertFalse(AllowedDomain.objects.filter(pk=self.domain.pk).exists())
        self.alice.refresh_from_db()
        self.assertFalse(self.alice.is_active)
        self.assertEqual(client.get("/api/v1/auth/me/").status_code, 403)
        self.assertTrue(IdentityEvent.objects.filter(action="domain.deleted").exists())

    def test_group_membership_separate_from_department_and_collaborator_rejected(self):
        admin = self.login(self.admin)
        self.assertEqual(
            self.post(
                admin,
                "/api/v1/memberships/",
                {
                    "user": self.alice.pk,
                    "group": self.group.pk,
                },
            ).status_code,
            400,
        )
        tech = self.make_user("tech", User.Role.TECHNICIAN)
        response = self.post(
            admin, "/api/v1/memberships/", {"user": tech.pk, "group": self.group.pk}
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(
            self.post(
                admin,
                "/api/v1/memberships/",
                {
                    "user": tech.pk,
                    "group": self.group.pk,
                },
            ).status_code,
            400,
        )
        technician = self.login(tech)
        self.assertEqual(technician.get("/api/v1/groups/").json()["count"], 1)
        self.assertEqual(self.login(self.alice).get("/api/v1/groups/").json()["count"], 0)
        self.patch(
            admin, f"/api/v1/users/{tech.pk}/", {"role": "collaborator", "reason": "Mudança"}
        )
        self.assertFalse(Membership.objects.filter(user=tech).exists())

    def test_admin_organization_crud_is_audited_and_no_sensitive_fields_returned(self):
        admin = self.login(self.admin)
        response = self.post(admin, "/api/v1/departments/", {"name": "RH"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            self.patch(
                admin,
                f"/api/v1/departments/{response.json()['id']}/",
                {
                    "name": "Pessoas",
                },
            ).status_code,
            200,
        )
        self.assertEqual(IdentityEvent.objects.filter(action__startswith="department.").count(), 2)
        profile = admin.get(f"/api/v1/users/{self.alice.pk}/").json()
        self.assertFalse(
            set(profile) & {"password", "mfa_secret", "recovery_hashes", "session_version"}
        )
        for invalid in ["*.company.test", "https://company.test", "company..test", "bad-.test"]:
            self.assertEqual(
                self.post(
                    admin,
                    "/api/v1/settings/domains/",
                    {
                        "domain": invalid,
                        "reason": "Synthetic",
                    },
                ).status_code,
                400,
            )

    def test_mutation_rolls_back_when_audit_fails(self):
        admin = self.login(self.admin)
        with patch("core.identity.audit", side_effect=RuntimeError("synthetic failure")):
            with self.assertRaises(RuntimeError):
                self.patch(
                    admin,
                    f"/api/v1/users/{self.alice.pk}/",
                    {
                        "role": "admin",
                        "reason": "Synthetic",
                    },
                )
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.role, User.Role.COLLABORATOR)
        self.assertEqual(self.alice.session_version, 1)

    def test_unique_email_is_enforced_case_insensitively_in_postgresql(self):
        self.assertEqual(connection.vendor, "postgresql")
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create(username="duplicate", email=self.alice.email.upper())

    def test_identity_mail_failure_retries_without_losing_account_or_logging_token(self):
        identity.issue_token(self.alice, "reset")
        _, raw = self.latest_token(self.alice, "reset")
        with override_settings(EMAIL_HOST="localhost", DEFAULT_FROM_EMAIL="pulse@company.test"):
            with patch("core.identity_mail.send_mail", side_effect=OSError("synthetic timeout")):
                self.assertTrue(deliver_one())
        mail = IdentityMail.objects.get()
        self.assertEqual(mail.attempts, 1)
        self.assertGreater(mail.next_attempt_at, timezone.now())
        self.assertIsNone(mail.sent_at)
        self.assertNotIn(raw, str(list(IdentityEvent.objects.values())))
        self.assertTrue(User.objects.filter(pk=self.alice.pk).exists())

    def test_expired_identity_material_is_cleaned(self):
        identity.issue_token(self.alice, "reset")
        token, _ = self.latest_token(self.alice, "reset")
        token.expires_at = timezone.now() - timedelta(seconds=1)
        token.save()
        cleanup()
        self.assertFalse(IdentityToken.objects.exists())
        self.assertFalse(IdentityMail.objects.exists())

    def test_real_local_smtp_receives_challenge_and_ciphertext_is_erased(self):
        messages = []

        class SMTPHandler(socketserver.StreamRequestHandler):
            def handle(self):
                self.wfile.write(b"220 local.test ESMTP\r\n")
                while line := self.rfile.readline():
                    verb = line.split(b" ", 1)[0].strip().upper()
                    if verb in {b"EHLO", b"HELO"}:
                        self.wfile.write(b"250 local.test\r\n")
                    elif verb == b"DATA":
                        self.wfile.write(b"354 Continue\r\n")
                        body = b""
                        while (chunk := self.rfile.readline()) != b".\r\n":
                            if not chunk:
                                return
                            body += chunk
                        messages.append(body)
                        self.wfile.write(b"250 accepted\r\n")
                    elif verb == b"QUIT":
                        self.wfile.write(b"221 bye\r\n")
                        return
                    else:
                        self.wfile.write(b"250 OK\r\n")

        identity.issue_token(self.alice, "verify")
        with socketserver.TCPServer(("127.0.0.1", 0), SMTPHandler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with override_settings(
                    EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
                    EMAIL_HOST="127.0.0.1",
                    EMAIL_PORT=server.server_address[1],
                    EMAIL_USE_TLS=False,
                    DEFAULT_FROM_EMAIL="pulse@company.test",
                ):
                    self.assertTrue(deliver_one())
            finally:
                server.shutdown()
                thread.join()
        self.assertEqual(len(messages), 1)
        self.assertIn(b"alice@company.test", messages[0])
        mail = IdentityMail.objects.get()
        self.assertIsNotNone(mail.sent_at)
        self.assertEqual(mail.encrypted_body, "")

    def test_bootstrap_has_no_default_password_or_verified_bypass(self):
        with self.assertRaises(CommandError):
            call_command(
                "bootstrap_admin", email="new@new.test", domain="new.test", stdout=StringIO()
            )
        User.objects.filter(pk=self.admin.pk).delete()
        with patch(
            "core.management.commands.bootstrap_admin.getpass.getpass", return_value=PASSWORD
        ):
            call_command(
                "bootstrap_admin", email="admin@new.test", domain="new.test", stdout=StringIO()
            )
        user = User.objects.get(role=User.Role.ADMIN)
        self.assertIsNone(user.email_verified_at)
        self.assertFalse(user.mfa_enabled)
        self.assertTrue(user.check_password(PASSWORD))
        self.assertTrue(
            IdentityEvent.objects.filter(action="bootstrap.admin_created", actor=None).exists()
        )


@override_settings(IDENTITY_RATE_LIMIT=100)
class ConcurrencyTests(HTTPHelpers, TransactionTestCase):
    def setUp(self):
        AllowedDomain.objects.create(domain="company.test")
        self.password = make_password(PASSWORD)
        self.user = User.objects.create(
            username="concurrent",
            email="concurrent@company.test",
            password=self.password,
            email_verified_at=timezone.now(),
        )

    def parallel(self, functions):
        barrier = threading.Barrier(len(functions))

        def run(function):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return function()
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=len(functions)) as executor:
            return list(executor.map(run, functions))

    def test_simultaneous_token_redemption_has_one_winner(self):
        identity.issue_token(self.user, "reset")
        _, raw = self.latest_token(self.user, "reset")

        def redeem():
            return self.post(
                self.client_for_test(),
                "/api/v1/auth/reset/",
                {
                    "token": raw,
                    "password": NEW_PASSWORD,
                },
            ).status_code

        self.assertEqual(sorted(self.parallel([redeem, redeem])), [200, 400])
        self.assertEqual(IdentityEvent.objects.filter(action="account.reset").count(), 1)

    def test_concurrent_registration_has_one_account(self):
        def register():
            return self.post(
                self.client_for_test(),
                "/api/v1/auth/register/",
                {
                    "name": "Synthetic",
                    "email": "new@company.test",
                    "password": PASSWORD,
                },
            ).status_code

        self.assertEqual(self.parallel([register, register]), [200, 200])
        self.assertEqual(User.objects.filter(email="new@company.test").count(), 1)
        # The second sign-up resends the confirmation, voiding the first code: one usable code.
        self.assertEqual(IdentityToken.objects.filter(used_at=None).count(), 1)

    def test_concurrent_admin_deactivation_preserves_one_admin(self):
        admins = []
        for index in range(2):
            raw = pyotp.random_base32()
            user = User.objects.create(
                username=f"admin{index}",
                email=f"admin{index}@company.test",
                password=self.password,
                role=User.Role.ADMIN,
                email_verified_at=timezone.now(),
                mfa_enabled=True,
                mfa_secret=identity.cipher().encrypt(raw.encode()).decode(),
            )
            admins.append((user, self.login(user)))

        def disable(index):
            user, client = admins[index]
            return self.patch(
                client,
                f"/api/v1/users/{user.pk}/",
                {
                    "is_active": False,
                    "reason": "Teste concorrente",
                },
            ).status_code

        self.assertEqual(
            sorted(self.parallel([lambda: disable(0), lambda: disable(1)])), [200, 400]
        )
        self.assertEqual(User.objects.filter(role=User.Role.ADMIN, is_active=True).count(), 1)

    def test_rate_counter_is_atomic_across_connections(self):
        def increment():
            identity.rate_limit("concurrency", secrets.token_hex(0) + "same", limit=100)

        self.parallel([increment] * 5)
        self.assertEqual(
            AuthRateBucket.objects.get(key=identity.digest("concurrency:same")).count, 5
        )
