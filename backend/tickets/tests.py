"""Integration and concurrency tests on PostgreSQL, including restricted runtime SQL privileges."""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import psycopg
import pyotp
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import DatabaseError, IntegrityError, close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from core.identity import cipher
from core.models import (
    AllowedDomain,
    Department,
    IdentityEvent,
    Membership,
    SupportGroup,
    User,
)
from core.test_identity import PASSWORD, HTTPHelpers
from tickets.models import (
    AuditEvent,
    Category,
    Comment,
    IdempotencyRecord,
    NotificationOutbox,
    ReopenPolicy,
    Ticket,
    TicketEvent,
    next_number,
)
from tickets.permissions import outbox_projection


@contextmanager
def owner_role():
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL ROLE pulse")
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL ROLE pulse_runtime")


class TicketHelpers(HTTPHelpers):
    @classmethod
    def make_fixtures(cls):
        AllowedDomain.objects.create(domain="company.test")
        cls.department = Department.objects.create(name="Comercial sintético")
        cls.group = SupportGroup.objects.create(name="Suporte sintético")
        cls.other_group = SupportGroup.objects.create(name="Infraestrutura sintética")
        hashed = make_password(PASSWORD)
        for name, role in [
            ("owner", "collaborator"),
            ("peer", "collaborator"),
            ("tech", "technician"),
            ("tech2", "technician"),
            ("manager", "manager"),
            ("admin", "admin"),
            ("outsider", "technician"),
        ]:
            user = User.objects.create(
                username=name,
                email=f"{name}@company.test",
                first_name=name,
                password=hashed,
                email_verified_at=timezone.now(),
                role=role,
                department=cls.department,
                mfa_enabled=role != "collaborator",
                mfa_secret=cipher().encrypt(pyotp.random_base32().encode()).decode(),
            )
            setattr(cls, name, user)
        for user in [cls.tech, cls.tech2, cls.manager]:
            Membership.objects.create(
                user=user,
                group=cls.group,
                can_view_restricted=user != cls.tech2,
                can_transfer=user != cls.tech2,
                can_cancel=user == cls.manager,
            )
        for user in [cls.tech, cls.outsider, cls.manager]:
            Membership.objects.create(
                user=user, group=cls.other_group, can_view_restricted=True, can_transfer=True
            )
        cls.category = Category.objects.create(name="Acesso", group=cls.group)
        cls.restricted_category = Category.objects.create(
            name="Restrito", group=cls.group, restricted=True
        )
        cls.policy = ReopenPolicy.objects.create(
            hours=48, actor=cls.admin, reason="Política sintética de teste"
        )

    def client_as(self, user):
        if user.pk not in self.clients:
            self.clients[user.pk] = self.login(user)
        return self.clients[user.pk]

    def send(self, user, path, data, key=None):
        client = self.client_as(user)
        csrf = client.get("/api/v1/auth/csrf/").json()["csrfToken"]
        return client.post(
            path,
            data,
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_IDEMPOTENCY_KEY=str(key or uuid.uuid4()),
        )

    def create(self, user=None, **overrides):
        data = {
            "category": self.category.pk,
            "subject": "Acesso sintético",
            "description": "Solicitação sintética de acesso",
            "priority": 2,
            **overrides,
        }
        response = self.send(user or self.owner, "/api/v1/tickets/", data)
        self.assertEqual(response.status_code, 201, response.content)
        return Ticket.objects.get(number=response.json()["number"])

    def mutate(self, ticket, user, action, data=None, key=None):
        ticket.refresh_from_db()
        return self.send(
            user,
            f"/api/v1/tickets/{ticket.uuid}/{action}/",
            {"expected_version": ticket.version, **(data or {})},
            key=key,
        )

    def claim(self, ticket, user=None):
        response = self.mutate(ticket, user or self.tech, "claim")
        self.assertEqual(response.status_code, 200, response.content)

    def transition(self, ticket, user, action, **data):
        response = self.mutate(ticket, user, "transitions", {"action": action, **data})
        self.assertEqual(response.status_code, 200, response.content)
        ticket.refresh_from_db()
        return response

    def read(self, ticket, user, suffix=""):
        return self.client_as(user).get(f"/api/v1/tickets/{ticket.uuid}/{suffix}")

    def resolve(self, ticket):
        self.claim(ticket)
        self.transition(
            ticket,
            self.tech,
            "resolve",
            message="Solução pública sintética",
            resolution_class="configuration",
        )


@override_settings(IDENTITY_RATE_LIMIT=100)
class TicketTests(TicketHelpers, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_fixtures()

    def setUp(self):
        self.clients = {}
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL ROLE pulse_runtime")

    def test_admin_removes_only_unused_records_and_edits_access(self):
        admin = self.client_as(self.admin)

        def delete(client, path):
            csrf = client.get("/api/v1/auth/csrf/").json()["csrfToken"]
            return client.delete(path, HTTP_X_CSRFTOKEN=csrf)

        self.create()
        spare_department = Department.objects.create(name="Área sem uso")
        spare_group = SupportGroup.objects.create(name="Grupo sem uso")
        spare_category = Category.objects.create(name="Sem uso", group=spare_group)
        self.assertEqual(
            delete(
                self.client_as(self.tech), f"/api/v1/departments/{spare_department.pk}/"
            ).status_code,
            403,
        )
        in_use = [
            f"/api/v1/departments/{self.department.pk}/",
            f"/api/v1/groups/{self.group.pk}/",
            f"/api/v1/categories/{self.category.pk}/",
        ]
        for path in in_use:
            self.assertEqual(delete(admin, path).status_code, 400, path)
        self.assertTrue(Category.objects.filter(pk=self.category.pk).exists())
        for path in [
            f"/api/v1/categories/{spare_category.pk}/",
            f"/api/v1/groups/{spare_group.pk}/",
            f"/api/v1/departments/{spare_department.pk}/",
        ]:
            self.assertEqual(delete(admin, path).status_code, 204, path)
        self.assertFalse(SupportGroup.objects.filter(pk=spare_group.pk).exists())

        member = Membership.objects.get(user=self.tech2, group=self.group)
        path = f"/api/v1/memberships/{member.pk}/"
        self.assertEqual(self.patch(admin, path, {"can_view_restricted": True}).status_code, 200)
        member.refresh_from_db()
        self.assertTrue(member.can_view_restricted)
        # Management cancellation stays reserved to managers when editing too.
        self.assertEqual(self.patch(admin, path, {"can_cancel": True}).status_code, 400)

    def test_transfer_options_are_scoped_to_authorized_groups(self):
        ticket = self.create(category=self.restricted_category.pk)
        for actor, expected in [(self.owner, 403), (self.tech2, 404), (self.peer, 404)]:
            self.assertEqual(self.read(ticket, actor, "transfer-options/").status_code, expected)
        response = self.read(ticket, self.tech, "transfer-options/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.tech2.pk, [m["user"] for m in response.json()["results"]])
        self.assertTrue(self.read(ticket, self.tech).json()["can_transfer"])
        self.assertFalse(self.read(ticket, self.owner).json()["can_transfer"])

    def test_full_cycle_information_test_resolution_close_and_reopen(self):
        ticket = self.create()
        self.assertEqual(ticket.priority, 2)
        self.claim(ticket)
        for action, expected in [
            ("request_information", Ticket.State.INFORMATION),
            ("request_test", Ticket.State.TEST),
        ]:
            self.transition(ticket, self.tech, action, message="Instruções públicas sintéticas")
            self.assertEqual(ticket.state, expected)
            result = self.mutate(
                ticket,
                self.owner,
                "comments",
                {"body": "Resposta sintética", "visibility": "public"},
            )
            self.assertEqual(result.status_code, 201, result.content)
            ticket.refresh_from_db()
            self.assertEqual(ticket.state, Ticket.State.ACTIVE)
            self.assertEqual(ticket.assignee_id, self.tech.pk)
        self.transition(
            ticket, self.tech, "resolve", message="Solução", resolution_class="configuration"
        )
        self.transition(ticket, self.owner, "reopen", message="Falha ainda ocorre")
        self.transition(
            ticket,
            self.tech,
            "resolve",
            message="Solução corrigida",
            resolution_class="configuration",
        )
        self.transition(ticket, self.owner, "confirm")
        self.assertEqual(ticket.state, Ticket.State.CLOSED)
        self.assertIsNotNone(ticket.closed_at)
        self.transition(ticket, self.owner, "reopen", message="Falha voltou")
        self.assertEqual(ticket.state, Ticket.State.ACTIVE)
        events = list(ticket.events.all())
        self.assertEqual(len(events), ticket.version)
        self.assertEqual(list(range(1, ticket.version + 1)), [e.version for e in events])
        for event in events:
            self.assertTrue(event.actor_id)
            self.assertIsNotNone(event.created_at.tzinfo)
            self.assertEqual(event.auditevent.actor_id, event.actor_id)
            self.assertEqual(event.auditevent.correlation_id, event.correlation_id)
            self.assertEqual(event.notificationoutbox.status, "pending")
        self.assertEqual(AuditEvent.objects.count(), NotificationOutbox.objects.count())

    def test_no_cross_user_access_in_any_read_path(self):
        ticket = self.create()
        # A technician outside the group still sees the shared queue.
        self.assertEqual(self.read(ticket, self.outsider).status_code, 200)
        for user in [self.peer]:
            for suffix in ["", "comments/", "events/"]:
                self.assertEqual(self.read(ticket, user, suffix).status_code, 404)
            response = self.client_as(user).get(
                f"/api/v1/tickets/?search=Acesso&number={ticket.number}"
            )
            self.assertEqual(response.json()["count"], 0)
            self.assertEqual(self.mutate(ticket, user, "claim").status_code, 404)

    def test_restricted_ticket_requires_explicit_scope(self):
        ticket = self.create(category=self.restricted_category.pk)
        self.assertEqual(self.read(ticket, self.tech).status_code, 200)
        self.assertEqual(self.read(ticket, self.tech2).status_code, 404)
        self.assertEqual(self.read(ticket, self.owner).status_code, 200)
        self.assertEqual(self.mutate(ticket, self.tech2, "claim").status_code, 404)

    def test_internal_note_never_appears_in_requester_history_search_or_outbox(self):
        ticket = self.create()
        result = self.mutate(
            ticket,
            self.tech,
            "comments",
            {"body": "INTERNAL_ONLY_NEVER_PUBLIC", "visibility": "internal"},
        )
        self.assertEqual(result.status_code, 201, result.content)
        for suffix in ["", "comments/", "events/"]:
            self.assertNotIn(
                "INTERNAL_ONLY_NEVER_PUBLIC", self.read(ticket, self.owner, suffix).content.decode()
            )
        self.assertEqual(self.read(ticket, self.owner, "comments/").json()["count"], 0)
        self.assertEqual(self.read(ticket, self.tech, "comments/").json()["count"], 1)
        self.assertEqual(
            self.client_as(self.owner)
            .get("/api/v1/tickets/?search=INTERNAL_ONLY_NEVER_PUBLIC")
            .json()["count"],
            0,
        )
        item = NotificationOutbox.objects.get(event_id=result.json()["event_id"])
        self.assertEqual(item.audience, "support")
        self.assertIsNone(outbox_projection(item, self.owner))
        self.assertIsNotNone(outbox_projection(item, self.tech))
        self.assertNotIn("INTERNAL_ONLY", str(item.payload))
        self.assertNotIn("INTERNAL_ONLY", str(item.event.auditevent.changes))

    def test_admin_has_full_access_including_restricted_and_internal(self):
        ticket = self.create(category=self.restricted_category.pk)
        self.claim(ticket)
        self.mutate(
            ticket, self.tech, "comments", {"body": "Private note", "visibility": "internal"}
        )
        self.assertEqual(self.read(ticket, self.admin).status_code, 200)
        self.assertEqual(self.read(ticket, self.admin, "comments/").json()["count"], 1)
        self.assertTrue(self.read(ticket, self.admin).json()["can_cancel"])
        response = self.mutate(
            ticket, self.admin, "transitions", {"action": "close", "message": "Encerrado"}
        )
        self.assertEqual(response.status_code, 200, response.content)
        unclaimed = self.create(category=self.restricted_category.pk)
        self.assertEqual(self.mutate(unclaimed, self.admin, "claim").status_code, 200)
        own = self.create(user=self.admin)
        self.assertEqual(self.mutate(own, self.admin, "claim").status_code, 403)

    def test_technician_acts_on_unassigned_ticket_closes_and_reopens(self):
        ticket = self.create()
        self.claim(ticket)
        self.assertEqual(
            self.mutate(
                ticket,
                self.tech2,
                "transitions",
                {"action": "resolve", "message": "X", "resolution_class": "Y"},
            ).status_code,
            200,
        )
        for action, state in [("reopen", "in_progress"), ("close", "closed")]:
            response = self.mutate(
                ticket, self.outsider, "transitions", {"action": action, "message": "X"}
            )
            self.assertEqual(response.status_code, 200, response.content)
            ticket.refresh_from_db()
            self.assertEqual(ticket.state, state)
        response = self.mutate(
            ticket, self.tech2, "transitions", {"action": "reopen", "message": "X"}
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            self.mutate(
                ticket, self.peer, "transitions", {"action": "close", "message": "X"}
            ).status_code,
            404,
        )

    def test_manager_only_reaches_tickets_of_own_groups(self):
        foreign = SupportGroup.objects.create(name="Grupo de outro gestor")
        category = Category.objects.create(name="Fora do gestor", group=foreign)
        outside = self.create(category=category.pk)
        inside = self.create()
        self.assertEqual(self.read(outside, self.manager).status_code, 404)
        self.assertEqual(self.mutate(outside, self.manager, "claim").status_code, 404)
        self.assertEqual(self.read(inside, self.manager).status_code, 200)
        self.assertEqual(self.mutate(inside, self.manager, "claim").status_code, 200)
        self.assertEqual(self.read(outside, self.outsider).status_code, 200)

    def test_audit_log_merges_trails_filters_and_is_admin_only(self):
        ticket = self.create()
        self.claim(ticket)
        client = self.client_as(self.admin)
        path = "/api/v1/settings/audit/"
        self.assertEqual(self.client_as(self.manager).get(path).status_code, 403)
        rows = client.get(path).json()["results"]
        self.assertEqual({"identity", "ticket"}, {row["source"] for row in rows})
        self.assertEqual(
            [row["created_at"] for row in rows],
            sorted((row["created_at"] for row in rows), reverse=True),
        )
        claimed = next(row for row in rows if row["action"] == "claimed")
        self.assertEqual(claimed["subject"], str(ticket.number))
        self.assertEqual(claimed["actor_email"], self.tech.email)
        mine = client.get(f"{path}?user={self.tech.pk}").json()["results"]
        self.assertTrue(mine)
        self.assertEqual({row["actor_id"] for row in mine}, {self.tech.pk})
        today = timezone.localtime(timezone=ZoneInfo("America/Sao_Paulo")).date()
        past = today - timedelta(days=2)
        self.assertGreater(client.get(f"{path}?start={today}&end={today}").json()["count"], 0)
        self.assertEqual(client.get(f"{path}?end={past}").json()["count"], 0)
        self.assertEqual(client.get(f"{path}?start={today}&end={past}").status_code, 400)
        self.assertEqual(client.get(f"{path}?user=abc").status_code, 400)
        self.assertEqual(client.get(f"{path}?page=1").status_code, 200)

    def test_notification_inbox_scope_mute_and_clear(self):
        ticket = self.create()
        self.claim(ticket)
        self.mutate(ticket, self.tech, "comments", {"body": "Nota", "visibility": "internal"})
        owner = self.client_as(self.owner)
        actions = [n["action"] for n in owner.get("/api/v1/notifications/").json()["results"]]
        self.assertEqual(actions, ["claimed"])
        tech2 = [
            n["action"]
            for n in self.client_as(self.tech2).get("/api/v1/notifications/").json()["results"]
        ]
        self.assertEqual(tech2, ["created"])
        peer = self.client_as(self.peer).get("/api/v1/notifications/").json()
        self.assertEqual(peer["results"], [])
        self.assertTrue(
            self.patch(owner, "/api/v1/notifications/", {"muted": True}).json()["muted"]
        )
        csrf = owner.get("/api/v1/auth/csrf/").json()["csrfToken"]
        cleared = owner.post("/api/v1/notifications/clear/", HTTP_X_CSRFTOKEN=csrf).json()
        self.assertEqual(cleared, {"muted": True, "results": []})

    def test_number_is_year_month_and_monthly_sequence(self):
        first, second = self.create(), self.create()
        zone = ZoneInfo("America/Sao_Paulo")
        prefix = int(timezone.localtime(timezone=zone).strftime("%Y%m")) * 1_000_000
        self.assertEqual(first.number, prefix + 1)
        self.assertEqual(second.number, prefix + 2)
        # 31/10 22:00 in Brasília is already November in UTC.
        late = datetime(2026, 11, 1, 1, 0, tzinfo=UTC)
        with patch("django.utils.timezone.now", return_value=late):
            self.assertEqual(next_number(), 202610000001)

    def test_any_technician_claims_others_join_and_requester_closes(self):
        ticket = self.create()
        self.assertEqual(self.mutate(ticket, self.outsider, "claim").status_code, 200)
        self.assertEqual(self.mutate(ticket, self.outsider, "join").status_code, 409)
        self.assertEqual(self.mutate(ticket, self.owner, "join").status_code, 403)
        self.assertEqual(self.mutate(ticket, self.tech2, "join").status_code, 200)
        names = [p["name"] for p in self.read(ticket, self.owner).json()["participants"]]
        self.assertEqual(names, ["tech2"])
        # A participant acts like the assignee.
        self.assertEqual(
            self.mutate(
                ticket, self.tech2, "transitions", {"action": "request_test", "message": "Teste"}
            ).status_code,
            200,
        )
        response = self.mutate(
            ticket, self.owner, "transitions", {"action": "close", "message": "Resolvido por mim"}
        )
        self.assertEqual(response.status_code, 200, response.content)
        ticket.refresh_from_db()
        self.assertEqual(ticket.state, "closed")
        self.assertIsNotNone(ticket.closed_at)

    def test_requester_who_is_technician_cannot_self_claim_or_see_notes(self):
        ticket = self.create(user=self.tech)
        self.assertEqual(self.mutate(ticket, self.tech, "claim").status_code, 403)
        self.mutate(ticket, self.tech2, "comments", {"body": "Internal", "visibility": "internal"})
        self.assertEqual(self.read(ticket, self.tech, "comments/").json()["count"], 0)
        self.assertEqual(
            self.mutate(
                ticket, self.tech, "comments", {"body": "Internal", "visibility": "internal"}
            ).status_code,
            403,
        )

    def test_department_snapshot_survives_user_move_and_department_rename(self):
        ticket = self.create()
        with owner_role():
            other = Department.objects.create(name="Nova área")
            User.objects.filter(pk=self.owner.pk).update(department=other)
            Department.objects.filter(pk=self.department.pk).update(name="Nome alterado")
        body = self.read(ticket, self.owner).json()
        self.assertEqual(body["department"], self.department.pk)
        self.assertEqual(body["department_name"], "Comercial sintético")

    def test_invalid_transition_actor_missing_text_and_generic_patch_fail(self):
        ticket = self.create()
        self.assertEqual(
            self.mutate(
                ticket,
                self.owner,
                "transitions",
                {"action": "resolve", "message": "X", "resolution_class": "Y"},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.mutate(
                ticket, self.tech, "transitions", {"action": "request_test", "message": "X"}
            ).status_code,
            409,
        )
        self.claim(ticket)
        self.assertEqual(
            self.mutate(ticket, self.tech, "transitions", {"action": "request_test"}).status_code,
            400,
        )
        self.assertEqual(
            self.mutate(
                ticket, self.tech, "transitions", {"action": "resolve", "message": "X"}
            ).status_code,
            400,
        )
        self.assertEqual(
            self.mutate(ticket, self.tech, "transitions", {"action": "confirm"}).status_code, 403
        )
        self.assertEqual(
            self.mutate(ticket, self.owner, "transitions", {"action": "confirm"}).status_code, 409
        )
        client = self.client_as(self.owner)
        csrf = client.get("/api/v1/auth/csrf/").json()["csrfToken"]
        self.assertEqual(
            client.patch(
                f"/api/v1/tickets/{ticket.uuid}/",
                {"state": "closed"},
                content_type="application/json",
                HTTP_X_CSRFTOKEN=csrf,
            ).status_code,
            405,
        )

    def test_server_rejects_forged_owner_dates_and_visibility(self):
        data = {
            "category": self.category.pk,
            "subject": "X",
            "description": "Y",
            "priority": 4,
        }
        for field, value in [
            ("requester", self.peer.pk),
            ("impact", 1),
            ("created_at", "2020-01-01"),
            ("restricted", False),
            ("state", "resolved"),
        ]:
            self.assertEqual(
                self.send(self.owner, "/api/v1/tickets/", {**data, field: value}).status_code, 400
            )
        self.assertEqual(Ticket.objects.count(), 0)

    def test_priority_comes_from_category_unless_requester_chooses(self):
        Category.objects.filter(pk=self.category.pk).update(priority=1)
        data = {"category": self.category.pk, "subject": "X", "description": "Y"}
        response = self.send(self.owner, "/api/v1/tickets/", data)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Ticket.objects.get(number=response.json()["number"]).priority, 1)
        self.assertEqual(self.create(priority=4).priority, 4)
        for invalid in [0, 5]:
            self.assertEqual(
                self.send(
                    self.owner, "/api/v1/tickets/", {**data, "priority": invalid}
                ).status_code,
                400,
            )

    def test_category_priority_defaults_validates_and_is_audited(self):
        client = self.client_as(self.admin)
        csrf = client.get("/api/v1/auth/csrf/").json()["csrfToken"]

        def patch_priority(value):
            return client.patch(
                f"/api/v1/categories/{self.category.pk}/",
                {"priority": value},
                content_type="application/json",
                HTTP_X_CSRFTOKEN=csrf,
            )

        self.assertEqual(self.category.priority, 3)
        for invalid in [0, 5]:
            self.assertEqual(patch_priority(invalid).status_code, 400)
        response = patch_priority(1)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["priority"], 1)
        changes = IdentityEvent.objects.filter(action="category.updated").latest("pk").changes
        self.assertEqual((changes["before"]["priority"], changes["after"]["priority"]), (3, 1))

    def test_idempotency_replays_exact_receipt_and_rejects_payload_change(self):
        data = {
            "category": self.category.pk,
            "subject": "X",
            "description": "Y",
            "priority": 4,
        }
        key = uuid.uuid4()
        first = self.send(self.owner, "/api/v1/tickets/", data, key)
        second = self.send(self.owner, "/api/v1/tickets/", data, key)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(second["Idempotent-Replayed"], "true")
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(
            self.send(
                self.owner, "/api/v1/tickets/", {**data, "subject": "different"}, key
            ).status_code,
            409,
        )
        self.assertEqual(self.send(self.peer, "/api/v1/tickets/", data, key).status_code, 201)

    def test_stale_version_conflicts_but_retry_same_key_does_not_repeat_event(self):
        ticket = self.create()
        key, data = uuid.uuid4(), {"expected_version": 1}
        path = f"/api/v1/tickets/{ticket.uuid}/claim/"
        first = self.send(self.tech, path, data, key)
        repeat = self.send(self.tech, path, data, key)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json(), repeat.json())
        self.assertEqual(self.send(self.tech2, path, data).status_code, 409)
        self.assertEqual(ticket.events.count(), 2)

    def test_replay_rechecks_revoked_permissions(self):
        ticket = self.create()
        key, data = uuid.uuid4(), {"expected_version": 1}
        path = f"/api/v1/tickets/{ticket.uuid}/claim/"
        self.assertEqual(self.send(self.tech, path, data, key).status_code, 200)
        with owner_role():
            SupportGroup.objects.filter(pk=self.group.pk).update(is_active=False)
        self.assertEqual(self.send(self.tech, path, data, key).status_code, 404)

    def test_correction_appends_and_cannot_change_author_or_visibility(self):
        ticket = self.create()
        self.mutate(ticket, self.tech, "comments", {"body": "Original", "visibility": "internal"})
        original = ticket.comments.get()
        self.assertEqual(
            self.mutate(
                ticket,
                self.tech,
                "comments",
                {"body": "Correction", "visibility": "internal", "corrects": str(original.pk)},
            ).status_code,
            201,
        )
        original.refresh_from_db()
        self.assertEqual(original.body, "Original")
        self.assertEqual(ticket.comments.count(), 2)
        self.assertEqual(
            self.mutate(
                ticket,
                self.tech2,
                "comments",
                {"body": "Tamper", "visibility": "internal", "corrects": str(original.pk)},
            ).status_code,
            404,
        )
        self.assertEqual(
            self.mutate(
                ticket,
                self.tech,
                "comments",
                {"body": "Leak", "visibility": "public", "corrects": str(original.pk)},
            ).status_code,
            404,
        )

    def test_transfer_and_return_to_queue_preserve_assignment_invariants(self):
        ticket = self.create()
        self.claim(ticket)
        self.assertEqual(
            self.mutate(
                ticket,
                self.tech2,
                "transfer",
                {"group": self.other_group.pk, "assignee": self.outsider.pk, "message": "Motivo"},
            ).status_code,
            403,
        )
        response = self.mutate(
            ticket,
            self.tech,
            "transfer",
            {
                "group": self.other_group.pk,
                "assignee": self.outsider.pk,
                "message": "Transferência pública",
            },
        )
        self.assertEqual(response.status_code, 200, response.content)
        ticket.refresh_from_db()
        self.assertEqual(ticket.assignee_id, self.outsider.pk)
        # The queue is shared, so the previous group still sees the ticket.
        self.assertEqual(self.read(ticket, self.tech2).status_code, 200)
        self.transition(ticket, self.manager, "return_queue", message="Retorno à fila")
        self.assertEqual(ticket.state, Ticket.State.NEW)
        self.assertIsNone(ticket.assignee_id)

    def test_restricted_transfer_refuses_unqualified_assignee(self):
        ticket = self.create(category=self.restricted_category.pk)
        self.claim(ticket)
        self.assertEqual(
            self.mutate(
                ticket,
                self.tech,
                "transfer",
                {"group": self.group.pk, "assignee": self.tech2.pk, "message": "Motivo"},
            ).status_code,
            400,
        )

    def test_cancel_rules_and_terminal_states(self):
        ticket = self.create()
        self.transition(ticket, self.owner, "cancel", message="Solicitação cancelada")
        self.assertEqual(self.mutate(ticket, self.tech, "claim").status_code, 409)
        self.assertEqual(
            self.mutate(
                ticket, self.owner, "comments", {"body": "Não permitido", "visibility": "public"}
            ).status_code,
            409,
        )
        ticket2 = self.create()
        self.claim(ticket2)
        self.assertEqual(
            self.mutate(
                ticket2, self.owner, "transitions", {"action": "cancel", "message": "Motivo"}
            ).status_code,
            403,
        )
        self.transition(ticket2, self.manager, "cancel", message="Cancelamento da gestão")
        self.assertEqual(ticket2.state, Ticket.State.CANCELLED)
        self.assertEqual(
            self.mutate(
                ticket2, self.manager, "transitions", {"action": "cancel", "message": "Motivo"}
            ).status_code,
            409,
        )

    def test_reopening_policy_is_frozen_and_outside_window_allows_linked_ticket(self):
        ticket = self.create()
        self.resolve(ticket)
        self.transition(ticket, self.owner, "confirm")
        response = self.send(
            self.admin, "/api/v1/settings/reopen-policies/", {"hours": 1, "reason": "Nova política"}
        )
        self.assertEqual(response.status_code, 201)
        with owner_role():
            Ticket.objects.filter(pk=ticket.pk).update(
                closed_at=timezone.now() - timedelta(hours=49)
            )
        self.assertEqual(
            self.mutate(
                ticket, self.owner, "transitions", {"action": "reopen", "message": "Voltou"}
            ).status_code,
            409,
        )
        linked = self.create(related_ticket=str(ticket.uuid))
        self.assertEqual(linked.related_ticket_id, ticket.pk)
        self.assertNotEqual(linked.reopen_policy_id, ticket.reopen_policy_id)
        self.assertEqual(ticket.reopen_policy_id, self.policy.pk)

    def test_missing_policy_disables_closed_reopen_and_manager_can_reassign(self):
        with owner_role():
            ReopenPolicy.objects.all().delete()
        ticket = self.create()
        self.resolve(ticket)
        self.transition(ticket, self.owner, "confirm")
        self.assertEqual(
            self.mutate(
                ticket, self.owner, "transitions", {"action": "reopen", "message": "Motivo"}
            ).status_code,
            409,
        )
        with owner_role():
            policy = ReopenPolicy.objects.create(hours=24, actor=self.admin, reason="Sintético")
            Ticket.objects.filter(pk=ticket.pk).update(reopen_policy=policy)
            User.objects.filter(pk=self.tech.pk).update(is_active=False)
        self.assertEqual(
            self.mutate(
                ticket, self.owner, "transitions", {"action": "reopen", "message": "Motivo"}
            ).status_code,
            409,
        )
        self.transition(
            ticket,
            self.manager,
            "reopen",
            message="Atribuição regularizada",
            assignee=self.tech2.pk,
        )
        self.assertEqual(ticket.assignee_id, self.tech2.pk)

    def test_queue_filters_pagination_and_no_internal_search(self):
        self.create(subject="First")
        self.create(subject="Second", priority=4)
        self.create(user=self.peer, subject="Other")
        client = self.client_as(self.owner)
        result = client.get("/api/v1/tickets/?ordering=priority").json()
        self.assertEqual(result["count"], 2)
        self.assertEqual([x["priority"] for x in result["results"]], [2, 4])
        self.assertEqual(client.get("/api/v1/tickets/?priority=4").json()["count"], 1)
        self.assertEqual(client.get("/api/v1/tickets/?page=2").status_code, 404)
        for query in ["ordering=password", "state=invalid", "requester=2", "priority=0"]:
            self.assertEqual(client.get("/api/v1/tickets/?" + query).status_code, 400)

    def test_mutation_and_creation_rollback_event_audit_outbox_and_idempotency(self):
        ticket = self.create()
        for target in [
            "tickets.services.AuditEvent.objects.create",
            "tickets.services.NotificationOutbox.objects.create",
            "tickets.services.IdempotencyRecord.objects.create",
        ]:
            with patch(target, side_effect=RuntimeError("synthetic failure")):
                with self.assertRaises(RuntimeError):
                    self.mutate(ticket, self.tech, "claim")
            ticket.refresh_from_db()
            self.assertEqual(ticket.version, 1)
            self.assertEqual(ticket.state, Ticket.State.NEW)
            self.assertEqual(ticket.events.count(), 1)
            self.assertEqual(AuditEvent.objects.count(), 1)
            self.assertEqual(NotificationOutbox.objects.count(), 1)
            self.assertEqual(IdempotencyRecord.objects.count(), 1)
        with patch(
            "tickets.services.NotificationOutbox.objects.create",
            side_effect=RuntimeError("synthetic failure"),
        ):
            with self.assertRaises(RuntimeError):
                self.create()
        self.assertEqual(Ticket.objects.count(), 1)

    def test_postgres_constraints_reject_unassigned_active_ticket(self):
        ticket = self.create()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Ticket.objects.filter(pk=ticket.pk).update(state="in_progress", assignee=None)

    def test_runtime_cannot_rewrite_audit_comments_or_policies(self):
        ticket = self.create()
        self.mutate(ticket, self.tech, "comments", {"body": "Immutable", "visibility": "internal"})
        for model in [AuditEvent, TicketEvent, Comment, ReopenPolicy, IdempotencyRecord]:
            with self.assertRaises(DatabaseError), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(f'DELETE FROM "{model._meta.db_table}"')
        with self.assertRaises(DatabaseError), transaction.atomic():
            Comment.objects.update(body="Changed")
        with self.assertRaises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("UPDATE core_identityevent SET action='tampered'")

    def test_runtime_login_cannot_become_owner_or_create_schema_objects(self):
        config = settings.DATABASES["default"]
        password = Path("/run/secrets/postgres_runtime_password").read_text().strip()
        with psycopg.connect(
            host=config["HOST"],
            dbname=connection.settings_dict["NAME"],
            user="pulse_runtime",
            password=password,
            autocommit=True,
        ) as runtime:
            self.assertEqual(
                runtime.execute("SELECT session_user,current_user").fetchone(),
                ("pulse_runtime", "pulse_runtime"),
            )
            for sql in [
                "SET ROLE pulse",
                "CREATE TABLE forbidden_probe(id integer)",
                "TRUNCATE tickets_auditevent",
                "ALTER TABLE tickets_auditevent ADD COLUMN forbidden integer",
            ]:
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    runtime.execute(sql)

    def test_outbox_authorization_rechecks_account_and_group_changes(self):
        ticket = self.create()
        item = NotificationOutbox.objects.get(event__ticket=ticket)
        self.assertIsNotNone(outbox_projection(item, self.tech))
        with owner_role():
            User.objects.filter(pk=self.tech.pk).update(is_active=False)
        self.assertIsNone(outbox_projection(item, self.tech))
        self.assertIsNone(outbox_projection(item, self.peer))

    def test_csrf_authentication_and_idempotency_key_required(self):
        self.assertEqual(self.client.get("/api/v1/tickets/").status_code, 403)
        client = self.client_as(self.owner)
        data = {
            "category": self.category.pk,
            "subject": "X",
            "description": "Y",
            "priority": 4,
        }
        self.assertEqual(
            client.post("/api/v1/tickets/", data, content_type="application/json").status_code, 403
        )
        csrf = client.get("/api/v1/auth/csrf/").json()["csrfToken"]
        self.assertEqual(
            client.post(
                "/api/v1/tickets/", data, content_type="application/json", HTTP_X_CSRFTOKEN=csrf
            ).status_code,
            400,
        )


@override_settings(IDENTITY_RATE_LIMIT=100)
class ConcurrentTicketTests(TicketHelpers, TransactionTestCase):
    def setUp(self):
        self.make_fixtures()
        self.clients = {}
        for user in [self.owner, self.tech, self.tech2]:
            self.client_as(user)

    def parallel(self, functions):
        barrier = threading.Barrier(len(functions))

        def run(function):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET ROLE pulse_runtime")
                barrier.wait(timeout=10)
                return function()
            finally:
                with connection.cursor() as cursor:
                    cursor.execute("RESET ROLE")
                close_old_connections()

        with ThreadPoolExecutor(max_workers=len(functions)) as executor:
            return list(executor.map(run, functions))

    def test_parallel_creations_get_distinct_consecutive_numbers(self):
        data = {
            "category": self.category.pk,
            "subject": "Paralelo",
            "description": "Abertura simultânea",
            "priority": 2,
        }

        def create():
            return self.send(self.owner, "/api/v1/tickets/", data).json()["number"]

        numbers = sorted(self.parallel([create, create]))
        self.assertEqual(numbers[1], numbers[0] + 1)

    def test_two_claims_have_one_winner_and_one_atomic_event(self):
        ticket = self.create()
        path = f"/api/v1/tickets/{ticket.uuid}/claim/"
        results = self.parallel(
            [
                lambda: self.send(self.tech, path, {"expected_version": 1}).status_code,
                lambda: self.send(self.tech2, path, {"expected_version": 1}).status_code,
            ]
        )
        self.assertEqual(sorted(results), [200, 409])
        ticket.refresh_from_db()
        self.assertIn(ticket.assignee_id, [self.tech.pk, self.tech2.pk])
        self.assertEqual(ticket.events.count(), 2)
        self.assertEqual(AuditEvent.objects.count(), 2)
        self.assertEqual(NotificationOutbox.objects.count(), 2)

    def test_reciprocal_transfers_do_not_deadlock_on_user_foreign_keys(self):
        from tickets import services

        Membership.objects.filter(user=self.tech2, group=self.group).update(can_transfer=True)
        first, second = self.create(), self.create()
        self.claim(first, self.tech)
        self.claim(second, self.tech2)
        save_barrier = threading.Barrier(2)
        original_advance = services.advance

        def simultaneous_save(ticket):
            save_barrier.wait(timeout=10)
            original_advance(ticket)

        def transfer(ticket, actor, target):
            return self.send(
                actor,
                f"/api/v1/tickets/{ticket.uuid}/transfer/",
                {
                    "expected_version": 2,
                    "group": self.group.pk,
                    "assignee": target.pk,
                    "message": "Transferência concorrente sintética",
                },
            ).status_code

        with patch("tickets.services.advance", side_effect=simultaneous_save):
            results = self.parallel(
                [
                    lambda: transfer(first, self.tech, self.tech2),
                    lambda: transfer(second, self.tech2, self.tech),
                ]
            )
        self.assertEqual(results, [200, 200])
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.assignee_id, second.assignee_id), (self.tech2.pk, self.tech.pk))

    def test_simultaneous_same_key_creation_is_single_ticket(self):
        key = uuid.uuid4()
        data = {
            "category": self.category.pk,
            "subject": "X",
            "description": "Y",
            "priority": 4,
        }

        def create():
            return self.send(self.owner, "/api/v1/tickets/", data, key).json()

        results = self.parallel([create, create])
        self.assertEqual(results[0], results[1])
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(IdempotencyRecord.objects.count(), 1)

    def test_comment_and_transition_from_same_version_cannot_overwrite(self):
        ticket = self.create()
        self.claim(ticket)
        path = f"/api/v1/tickets/{ticket.uuid}/"
        results = self.parallel(
            [
                lambda: (
                    self.send(
                        self.owner,
                        path + "comments/",
                        {"expected_version": 2, "body": "Resposta", "visibility": "public"},
                    ).status_code
                ),
                lambda: (
                    self.send(
                        self.tech,
                        path + "transitions/",
                        {
                            "expected_version": 2,
                            "action": "request_information",
                            "message": "Pergunta",
                        },
                    ).status_code
                ),
            ]
        )
        self.assertEqual(results.count(409), 1)
        self.assertEqual(sum(code in {200, 201} for code in results), 1)
        self.assertEqual(ticket.events.count(), 3)
        self.assertEqual(Comment.objects.count(), 1)
