import uuid

from django.db import connection
from django.test import TestCase

from tickets.tests import TicketHelpers
from wiki.models import WikiPage


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
