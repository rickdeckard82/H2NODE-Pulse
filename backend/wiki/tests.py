import tempfile
import uuid
from io import StringIO
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from core.models import User
from tickets.models import Ticket
from tickets.tests import TicketHelpers
from wiki.files import path_for
from wiki.models import WikiFile, WikiPage


class WikiTests(TicketHelpers, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_fixtures()

    def setUp(self):
        self.clients = {}
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL ROLE pulse_runtime")

    def call(self, user, method, path, data=None):
        client = self.client_as(user)
        csrf = client.get("/api/v1/auth/csrf/").json()["csrfToken"]
        return getattr(client, method)(
            path, data, content_type="application/json", HTTP_X_CSRFTOKEN=csrf
        )

    def test_only_managers_and_admins_write(self):
        body = {
            "title": "Limpar cache",
            "body": "Passo 1",
            "tags": ["Suporte", "suporte", " Rede,x "],
        }
        for user in [self.owner, self.tech]:
            self.assertEqual(self.call(user, "post", "/api/v1/wiki/", body).status_code, 403)
        self.assertEqual(WikiPage.objects.count(), 0)
        for user in [self.manager, self.admin]:
            response = self.call(user, "post", "/api/v1/wiki/", body)
            self.assertEqual(response.status_code, 201, response.content)
        page = WikiPage.objects.first()
        self.assertEqual(page.tags, ["Suporte", "Rede x"])
        self.assertEqual(page.author, self.admin)

    def test_everyone_reads_but_cannot_edit_or_delete(self):
        page = WikiPage.objects.create(title="A", body="B", author=self.manager)
        path = f"/api/v1/wiki/{page.uuid}/"
        for user in [self.owner, self.tech]:
            self.assertEqual(self.client_as(user).get(path).json()["body"], "B")
            listing = self.client_as(user).get("/api/v1/wiki/").json()
            self.assertEqual([p["title"] for p in listing], ["A"])
            self.assertNotIn("body", listing[0])
            self.assertEqual(self.call(user, "patch", path, {"title": "X"}).status_code, 403)
            self.assertEqual(self.call(user, "delete", path).status_code, 403)
        page.refresh_from_db()
        self.assertEqual(page.title, "A")

    def test_edit_delete_and_audit(self):
        page = WikiPage.objects.create(title="A", body="B", author=self.manager)
        path = f"/api/v1/wiki/{page.uuid}/"
        response = self.call(self.admin, "patch", path, {"title": "Novo", "tags": ["T"]})
        self.assertEqual(response.status_code, 200, response.content)
        page.refresh_from_db()
        self.assertEqual((page.title, page.body, page.tags), ("Novo", "B", ["T"]))
        self.assertEqual(page.updated_by, self.admin)
        self.assertEqual(self.call(self.manager, "delete", path).status_code, 204)
        self.assertFalse(WikiPage.objects.exists())
        self.assertEqual(
            list(
                self.admin.identity_actions.filter(action__startswith="wiki.").values_list(
                    "action", flat=True
                )
            ),
            ["wiki.updated"],
        )
        self.assertEqual(self.call(self.manager, "delete", path).status_code, 404)
        self.assertEqual(
            self.call(self.manager, "delete", f"/api/v1/wiki/{uuid.uuid4()}/").status_code, 404
        )

    def test_rejects_unknown_fields_and_too_many_tags(self):
        base = {"title": "A", "body": "B"}
        for extra in [{"author": 1}, {"tags": list("abcdef")}]:
            self.assertEqual(
                self.call(self.manager, "post", "/api/v1/wiki/", {**base, **extra}).status_code,
                400,
            )


class AreaVisibilityTests(WikiTests):
    def setUp(self):
        super().setUp()
        from core.models import Department

        self.other = Department.objects.create(name="Outra área sintética")

    def titles(self, user):
        return sorted(p["title"] for p in self.client_as(user).get("/api/v1/wiki/").json())

    def make(self, title, *departments):
        response = self.call(
            self.manager,
            "post",
            "/api/v1/wiki/",
            {"title": title, "body": "X", "departments": [d.pk for d in departments]},
        )
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def test_page_visible_only_to_listed_areas(self):
        mine = self.make("Da área", self.department)
        self.assertEqual(mine["departments"][0]["id"], self.department.pk)
        other = self.make("De outra", self.other)
        self.make("Aberta")
        both = self.make("Das duas", self.department, self.other)
        # owner (collaborator), tech and outsider (technician) all sit in self.department.
        for user in [self.owner, self.tech, self.outsider]:
            self.assertEqual(self.titles(user), ["Aberta", "Da área", "Das duas"])
        # Managers and administrators see everything.
        for user in [self.manager, self.admin]:
            self.assertEqual(len(self.titles(user)), 4)
        for user in [self.owner, self.tech]:
            self.assertEqual(
                self.client_as(user).get(f"/api/v1/wiki/{other['id']}/").status_code, 404
            )
            self.assertEqual(
                self.client_as(user).get(f"/api/v1/wiki/{both['id']}/").status_code, 200
            )

    def test_user_without_area_only_sees_open_pages(self):
        self.make("Restrita", self.department)
        self.make("Aberta")
        User.objects.filter(pk=self.owner.pk).update(department=None)
        self.assertEqual(self.titles(self.owner), ["Aberta"])

    def test_area_changes_validation_and_permissions(self):
        page = self.make("T", self.other)
        path = f"/api/v1/wiki/{page['id']}/"
        self.assertEqual(self.client_as(self.owner).get(path).status_code, 404)
        self.assertEqual(
            self.call(self.manager, "patch", path, {"title": "T2"}).json()["departments"][0]["id"],
            self.other.pk,
        )
        done = self.call(self.manager, "patch", path, {"departments": []})
        self.assertEqual(done.json()["departments"], [])
        self.assertEqual(self.client_as(self.owner).get(path).status_code, 200)
        for bad in ([999999], ["x"]):
            self.assertEqual(
                self.call(self.manager, "patch", path, {"departments": bad}).status_code, 400
            )
        self.assertEqual(
            self.call(self.tech, "patch", path, {"departments": [self.other.pk]}).status_code, 403
        )
        self.assertEqual(
            self.client_as(self.tech).get("/api/v1/wiki/departments/").status_code, 403
        )
        self.assertEqual(
            self.client_as(self.manager).get("/api/v1/wiki/departments/").status_code, 200
        )


class ImportTests(TicketHelpers, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_fixtures()

    def run_import(self, *args):
        out = StringIO()
        call_command("import_wiki", *args, stdout=out)
        return out.getvalue()

    def test_bundled_pages_import_once_with_original_dates(self):
        author = ["--author", self.manager.email]
        self.assertIn("Simulação: 10 criada(s)", self.run_import(*author, "--dry-run"))
        self.assertEqual(WikiPage.objects.count(), 0)
        self.assertIn("10 criada(s), 0 já existente(s)", self.run_import(*author))
        self.assertIn("0 criada(s), 10 já existente(s)", self.run_import(*author))
        page = WikiPage.objects.get(title__contains="Limpar o cache")
        self.assertEqual(
            (page.author, page.tags, page.created_at.year), (self.manager, ["Suporte"], 2026)
        )
        self.assertTrue(self.manager.identity_actions.filter(action="wiki.imported").exists())

    def test_author_must_be_manager_or_admin(self):
        for user in [self.owner, self.tech]:
            with self.assertRaises(CommandError):
                self.run_import("--author", user.email)
        with self.assertRaises(CommandError):
            self.run_import("--author", "ninguem@company.test")
        self.assertEqual(WikiPage.objects.count(), 0)


PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 40 + b"IEND\xaeB`\x82"
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


class FileTests(TicketHelpers, TestCase):
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

    def upload(self, user, raw=PNG, name="print.png", mime="image/png"):
        client = self.client_as(user)
        csrf = client.get("/api/v1/auth/csrf/").json()["csrfToken"]
        return client.post(
            "/api/v1/wiki/files/",
            {"file": SimpleUploadedFile(name, raw, content_type=mime)},
            HTTP_X_CSRFTOKEN=csrf,
        )

    def stored(self):
        return [p for p in Path(self.temp.name).rglob("*") if p.is_file()]

    def test_manager_uploads_everyone_reads_with_safe_headers(self):
        response = self.upload(self.manager)
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["url"], f"/api/v1/wiki/files/{body['id']}/")
        image = self.client_as(self.owner).get(body["url"])
        self.assertEqual(image["Content-Type"], "image/png")
        self.assertTrue(image["Content-Disposition"].startswith("inline"))
        self.assertEqual(image["X-Content-Type-Options"], "nosniff")
        self.assertIn("sandbox", image["Content-Security-Policy"])
        pdf = self.upload(self.admin, b"%PDF-1.4 x", "guia.pdf", "application/pdf").json()
        download = self.client_as(self.tech).get(pdf["url"])
        self.assertTrue(download["Content-Disposition"].startswith("attachment"))
        self.assertEqual(download["Content-Type"], "application/octet-stream")
        self.assertTrue(self.manager.identity_actions.filter(action="wiki.file_uploaded").exists())

    def test_only_managers_and_admins_upload(self):
        for user in [self.owner, self.tech]:
            self.assertEqual(self.upload(user).status_code, 403)
        self.assertEqual(WikiFile.objects.count(), 0)
        self.assertEqual(self.stored(), [])
        self.assertEqual(
            self.client_as(self.owner).get(f"/api/v1/wiki/files/{uuid.uuid4()}/").status_code, 404
        )

    def test_spoofed_dangerous_and_empty_files_rejected(self):
        cases = [
            (b"<svg onload=alert(1)>", "x.svg", "image/svg+xml"),
            (b"<script>alert(1)</script>", "x.png", "image/png"),
            (PNG, "x.png", "image/jpeg"),
            (b"MZ\x90\x00", "x.exe", "application/octet-stream"),
            (b"<html>", "x.txt", "text/plain"),
            (b"", "x.png", "image/png"),
        ]
        for raw, name, mime in cases:
            self.assertEqual(self.upload(self.manager, raw, name, mime).status_code, 400, name)
        self.assertEqual(WikiFile.objects.count(), 0)
        self.assertEqual(self.stored(), [])

    def test_real_scanner_blocks_eicar_and_keeps_nothing(self):
        response = self.upload(self.manager, EICAR, "teste.txt", "text/plain")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(WikiFile.objects.count(), 0)
        self.assertEqual(self.stored(), [])

    def test_scanner_down_fails_closed(self):
        with override_settings(CLAMAV_HOST="127.0.0.1", CLAMAV_PORT=1):
            self.assertEqual(self.upload(self.manager).status_code, 503)
        self.assertEqual(WikiFile.objects.count(), 0)
        self.assertEqual(self.stored(), [])

    def test_tampered_file_is_never_served(self):
        item = WikiFile.objects.get(pk=self.upload(self.manager).json()["id"])
        path_for(item.pk).write_bytes(PNG + b"x")
        self.assertEqual(
            self.client_as(self.owner).get(f"/api/v1/wiki/files/{item.pk}/").status_code, 400
        )


@override_settings(IDENTITY_RATE_LIMIT=100)
class AutocommitTests(TicketHelpers, TransactionTestCase):
    """Without the wrapping transaction of TestCase, row locks outside atomic() would fail."""

    def setUp(self):
        self.make_fixtures()
        self.clients = {}
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        override = override_settings(ATTACHMENT_ROOT=self.temp.name)
        override.enable()
        self.addCleanup(override.disable)

    def test_upload_and_page_writes_work_in_autocommit(self):
        client = self.client_as(self.manager)
        csrf = client.get("/api/v1/auth/csrf/").json()["csrfToken"]
        response = client.post(
            "/api/v1/wiki/files/",
            {"file": SimpleUploadedFile("a.png", PNG, content_type="image/png")},
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(response.status_code, 201, response.content)
        page = client.post(
            "/api/v1/wiki/",
            {"title": "T", "body": f"![x]({response.json()['url']} =320x)"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(page.status_code, 201, page.content)


class UserRoleTests(TicketHelpers, TestCase):
    """The self-registered "Usuário" role reaches the wiki and nothing else."""

    @classmethod
    def setUpTestData(cls):
        cls.make_fixtures()
        cls.visitor = User.objects.create(
            username="visitor",
            email="visitor@company.test",
            first_name="visitor",
            password=cls.owner.password,
            email_verified_at=timezone.now(),
        )

    def setUp(self):
        self.clients = {}
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL ROLE pulse_runtime")

    def test_new_accounts_default_to_user_role(self):
        self.assertEqual(self.visitor.role, "user")

    def test_registration_creates_user_role(self):
        from core import identity

        identity.register({"email": "novo@company.test", "name": "Novo"})
        self.assertEqual(User.objects.get(email="novo@company.test").role, "user")

    def test_user_role_reads_wiki_but_cannot_write(self):
        page = WikiPage.objects.create(title="A", body="B", author=self.manager)
        client = self.client_as(self.visitor)
        self.assertEqual(client.get("/api/v1/wiki/").status_code, 200)
        self.assertEqual(client.get(f"/api/v1/wiki/{page.uuid}/").status_code, 200)
        self.assertEqual(client.get("/api/v1/auth/me/").json()["role"], "user")
        self.assertEqual(client.get("/api/v1/settings/company/").status_code, 200)
        self.assertEqual(client.get("/api/v1/company/legal/").status_code, 200)
        body = {"title": "X", "body": "Y"}
        self.assertEqual(self.call(self.visitor, "post", "/api/v1/wiki/", body).status_code, 403)

    def call(self, user, method, path, data=None):
        client = self.client_as(user)
        csrf = client.get("/api/v1/auth/csrf/").json()["csrfToken"]
        return getattr(client, method)(
            path, data, content_type="application/json", HTTP_X_CSRFTOKEN=csrf
        )

    def test_user_role_is_denied_everywhere_else(self):
        ticket = Ticket.objects.create(
            requester=self.owner,
            category=self.category,
            group=self.group,
            subject="S",
            description="D",
            priority=2,
        )
        client = self.client_as(self.visitor)
        for path in [
            "/api/v1/tickets/",
            f"/api/v1/tickets/{ticket.uuid}/",
            f"/api/v1/tickets/{ticket.uuid}/attachments/",
            "/api/v1/categories/",
            "/api/v1/notifications/",
            "/api/v1/reports/summary/",
            "/api/v1/users/",
            "/api/v1/departments/",
            "/api/v1/groups/",
            "/api/v1/memberships/",
            "/api/v1/settings/audit/",
            "/api/v1/settings/smtp/",
            "/api/v1/settings/sla-policies/",
            "/api/v1/settings/domains/",
        ]:
            self.assertEqual(client.get(path).status_code, 403, path)
        created = self.call(
            self.visitor,
            "post",
            "/api/v1/tickets/",
            {"category": self.category.pk, "subject": "X", "description": "Y"},
        )
        self.assertEqual(created.status_code, 403)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(
            self.call(self.visitor, "patch", "/api/v1/settings/company/", {}).status_code, 403
        )

    def test_collaborator_is_not_restricted_and_promotion_works(self):
        self.assertEqual(self.client_as(self.owner).get("/api/v1/tickets/").status_code, 200)
        response = self.call(
            self.admin,
            "patch",
            f"/api/v1/users/{self.visitor.pk}/",
            {"role": "collaborator", "reason": "Liberar chamados"},
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.visitor.refresh_from_db()
        self.assertEqual(self.visitor.role, "collaborator")
        self.clients.clear()
        self.assertEqual(self.client_as(self.visitor).get("/api/v1/tickets/").status_code, 200)
