from datetime import timedelta

import pyotp
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone

from core.identity import cipher, digest
from core.identity_mail import cleanup
from core.models import AllowedDomain, IdentityEvent, TrustedDevice, User
from core.test_identity import PASSWORD, HTTPHelpers
from core.trusted_devices import COOKIE


@override_settings(IDENTITY_RATE_LIMIT=100)
class TrustedDeviceTests(HTTPHelpers, TestCase):
    @classmethod
    def setUpTestData(cls):
        AllowedDomain.objects.create(domain="company.test")
        cls.user = User.objects.create_user(
            username="admin",
            email="admin@company.test",
            password=PASSWORD,
            role="admin",
            email_verified_at=timezone.now(),
            mfa_enabled=True,
            mfa_secret=cipher().encrypt(pyotp.random_base32().encode()).decode(),
        )

    def setUp(self):
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL ROLE pulse_runtime")
        self.client = self.client_for_test()

    def password_login(self, password=PASSWORD):
        return self.post(
            self.client, "/api/v1/auth/login/", {"email": self.user.email, "password": password}
        )

    def remember(self, enabled=True):
        self.assertEqual(self.password_login().json()["status"], "mfa_required")
        code = pyotp.TOTP(cipher().decrypt(self.user.mfa_secret.encode()).decode()).now()
        response = self.post(
            self.client, "/api/v1/auth/mfa/verify/", {"code": code, "remember_device": enabled}
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response

    def logout(self):
        self.assertEqual(self.post(self.client, "/api/v1/auth/logout/").status_code, 200)

    def test_opt_in_only_and_invalid_factor_never_remembers(self):
        self.password_login()
        response = self.post(
            self.client, "/api/v1/auth/mfa/verify/", {"code": "invalid", "remember_device": True}
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(TrustedDevice.objects.exists())
        self.assertNotIn(COOKIE, response.cookies)
        self.remember(False)
        self.assertFalse(TrustedDevice.objects.exists())
        self.logout()
        self.assertEqual(self.password_login().json()["status"], "mfa_required")

    @override_settings(SESSION_COOKIE_SECURE=True)
    def test_cookie_security_hash_only_rotation_and_fixed_deadline(self):
        response = self.remember()
        cookie = response.cookies[COOKIE]
        self.assertTrue(cookie["httponly"])
        self.assertTrue(cookie["secure"])
        self.assertEqual(cookie["samesite"], "Strict")
        self.assertEqual(cookie["path"], "/api/v1/auth/")
        self.assertTrue(30 * 86400 - 10 <= cookie["max-age"] <= 30 * 86400)
        raw = cookie.value
        row = TrustedDevice.objects.get()
        self.assertEqual(row.digest, digest(raw))
        self.assertNotIn(raw, str(list(TrustedDevice.objects.values())))
        self.assertNotIn(raw, str(list(IdentityEvent.objects.values())))
        self.assertNotIn(raw, response.content.decode())
        self.logout()
        response = self.password_login()
        self.assertEqual(response.json()["status"], "authenticated")
        self.assertNotEqual(response.cookies[COOKIE].value, raw)
        rotated = TrustedDevice.objects.get()
        self.assertEqual(rotated.expires_at, row.expires_at)
        self.assertEqual(rotated.created_at, row.created_at)
        self.assertFalse(TrustedDevice.objects.filter(digest=digest(raw)).exists())
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 200)

    def test_password_still_required_and_remembered_mfa_is_not_recent_factor(self):
        self.remember()
        self.logout()
        self.assertEqual(self.password_login("wrong").status_code, 403)
        self.assertEqual(self.password_login().json()["status"], "authenticated")
        response = self.post(self.client, "/api/v1/auth/mfa/replace/", {"password": PASSWORD})
        self.assertEqual(response.status_code, 403)

    def test_expired_and_tampered_cookie_require_mfa(self):
        self.remember()
        self.logout()
        raw = self.client.cookies[COOKIE].value
        self.client.cookies[COOKIE] = raw + "tampered"
        self.assertEqual(self.password_login().json()["status"], "mfa_required")
        self.client.cookies[COOKIE] = raw
        TrustedDevice.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.password_login().json()["status"], "mfa_required")
        cleanup()
        self.assertFalse(TrustedDevice.objects.exists())

    def test_revoke_all_and_forget_current_browser(self):
        self.remember()
        self.assertEqual(self.post(self.client, "/api/v1/auth/forget-device/").status_code, 200)
        self.assertFalse(TrustedDevice.objects.exists())
        self.assertFalse(self.client.cookies[COOKIE].value)
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 403)
        self.assertEqual(self.password_login().json()["status"], "mfa_required")

    def test_global_revocation_invalidates_other_cookie_copies(self):
        self.remember()
        raw = self.client.cookies[COOKIE].value
        self.assertEqual(self.post(self.client, "/api/v1/auth/revoke/").status_code, 200)
        self.client.cookies[COOKIE] = raw
        self.assertEqual(self.password_login().json()["status"], "mfa_required")

    def test_credentials_version_role_and_other_accounts_do_not_reuse_trust(self):
        self.remember()
        self.logout()
        raw = self.client.cookies[COOKIE].value
        self.user.session_version += 1
        self.user.save(update_fields=["session_version"])
        self.assertEqual(self.password_login().json()["status"], "mfa_required")
        self.user.session_version -= 1
        self.user.role = "manager"
        self.user.save(update_fields=["session_version", "role"])
        self.client.cookies[COOKIE] = raw
        self.assertEqual(self.password_login().json()["status"], "mfa_required")
        self.user.role = "admin"
        self.user.set_password(PASSWORD)
        self.user.save()
        self.client.cookies[COOKIE] = raw
        self.assertEqual(self.password_login().json()["status"], "mfa_required")

    def test_other_account_cannot_use_cookie_and_disabled_account_is_denied(self):
        self.remember()
        self.logout()
        raw = self.client.cookies[COOKIE].value
        other = User.objects.create_user(
            username="other",
            email="other@company.test",
            password=PASSWORD,
            role="admin",
            email_verified_at=timezone.now(),
            mfa_enabled=True,
            mfa_secret=self.user.mfa_secret,
        )
        response = self.post(
            self.client, "/api/v1/auth/login/", {"email": other.email, "password": PASSWORD}
        )
        self.assertEqual(response.json()["status"], "mfa_required")
        self.client.cookies[COOKIE] = raw
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.assertEqual(self.password_login().status_code, 403)
