"""SLA clocks against hand-computed fixtures; report scope, exports and alerts on PostgreSQL."""

import csv
import io
from datetime import datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from django.db import DatabaseError, connection, transaction
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from core.models import IdentityEvent
from tickets.models import NotificationOutbox, ReportExport, SlaPolicy, Ticket
from tickets.reports import ZONE, cleanup_exports
from tickets.sla import alert_breaches, business_seconds, measure
from tickets.tests import TicketHelpers

SP = ZoneInfo("America/Sao_Paulo")


def policy(**overrides):
    values = {
        "timezone": "America/Sao_Paulo",
        "weekdays": "0,1,2,3,4",
        "start_time": time(8),
        "end_time": time(18),
        "holidays": "2026-11-02",
        "p3_response": 120,
        "p3_resolution": 240,
    }
    return SlaPolicy(**{**values, **overrides})


def at(day, hour, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=SP)


def event(when, to_state, action="x", public_by=None):
    return SimpleNamespace(
        created_at=when,
        to_state=to_state,
        action=action,
        comment_id=1 if public_by else None,
        visibility="public",
        actor_id=public_by,
    )


class BusinessClockTests(SimpleTestCase):
    def test_weekend_and_holiday_are_skipped(self):
        # Fri 17-18 (1h) + Sat/Sun off + Mon 2 Nov holiday + Tue 08-09 (1h).
        start = datetime(2026, 10, 30, 17, tzinfo=SP)
        self.assertEqual(business_seconds(policy(), start, at(3, 9)), 7200)
        self.assertEqual(business_seconds(policy(), at(3, 6), at(3, 7, 59)), 0)
        self.assertEqual(business_seconds(policy(), at(3, 9), at(3, 9)), 0)

    def test_daylight_saving_day_counts_real_time(self):
        # New York springs forward on 8 Mar 2026: 00:00-12:00 local is 11 real hours.
        zone = ZoneInfo("America/New_York")
        rule = policy(
            timezone="America/New_York", weekdays="6", start_time=time(0), end_time=time(12)
        )
        start = datetime(2026, 3, 8, 0, tzinfo=zone)
        self.assertEqual(business_seconds(rule, start, start + timedelta(hours=23)), 39600)

    def test_pause_reopen_and_breach(self):
        ticket = SimpleNamespace(sla_policy=policy(), priority=3, requester_id=1, state="resolved")
        history = [
            event(at(3, 9), "new", "created"),
            event(at(3, 9, 30), "in_progress", "claimed"),
            event(at(3, 10), "waiting_information", "request_information", public_by=2),
            event(at(4, 9), "in_progress", "requester.replied"),
            event(at(4, 10), "resolved", "resolve", public_by=2),
        ]
        result = measure(ticket, history, at(9, 12))
        self.assertEqual(result["response_seconds"], 3600)
        self.assertTrue(result["response_met"])
        # Tue 09:00-10:00 + Wed 09:00-10:00; the pause overnight is excluded.
        self.assertEqual(result["resolution_seconds"], 7200)
        self.assertTrue(result["resolution_met"])
        self.assertEqual(result["elapsed_seconds"], 25 * 3600)

        history += [
            event(at(5, 8), "in_progress", "reopen"),
            event(at(5, 12), "resolved", "resolve", public_by=2),
        ]
        result = measure(ticket, history, at(9, 12))
        self.assertEqual(result["resolution_seconds"], 7200 + 4 * 3600)
        self.assertFalse(result["resolution_met"])
        self.assertEqual(result["reopens"], 1)

    def test_technician_pause_stops_the_resolution_clock(self):
        ticket = SimpleNamespace(sla_policy=policy(), priority=3, requester_id=1, state="resolved")
        history = [
            event(at(3, 9), "new", "created"),
            event(at(3, 9, 30), "in_progress", "claimed"),
            event(at(3, 10), "paused", "pause", public_by=2),
            event(at(3, 15), "in_progress", "resume"),
            event(at(3, 16), "resolved", "resolve", public_by=2),
        ]
        # 09:00-10:00 + 15:00-16:00 running; the 5 paused hours are excluded.
        self.assertEqual(measure(ticket, history, at(9, 12))["resolution_seconds"], 7200)

    def test_unanswered_ticket_breaches_and_cancelled_is_excluded(self):
        ticket = SimpleNamespace(sla_policy=policy(), priority=3, requester_id=1, state="new")
        result = measure(ticket, [event(at(3, 9), "new", "created")], at(3, 12))
        self.assertFalse(result["response_met"])
        self.assertIsNone(result["resolution_met"])
        cancelled = [event(at(3, 9), "new", "created"), event(at(3, 9, 5), "cancelled", "cancel")]
        result = measure(ticket, cancelled, at(9, 12))
        self.assertIsNone(result["response_met"])
        self.assertIsNone(result["resolution_met"])
        # The requester's own public text never counts as a response.
        own = [event(at(3, 9), "new", "created"), event(at(3, 9, 1), "new", public_by=1)]
        self.assertIsNone(measure(ticket, own, at(3, 9, 2))["first_response_at"])


SLA_INPUT = {
    "reason": "Política sintética",
    "timezone": "America/Sao_Paulo",
    "weekdays": "0,1,2,3,4",
    "start_time": "08:00",
    "end_time": "18:00",
    "holidays": "2026-12-25, 2026-11-02",
    **{
        f"p{p}_{c}": 60 * p * (1 if c == "response" else 4)
        for p in range(1, 5)
        for c in ("response", "resolution")
    },
}


@override_settings(IDENTITY_RATE_LIMIT=100)
class SlaReportTests(TicketHelpers, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_fixtures()

    def setUp(self):
        self.clients = {}
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL ROLE pulse_runtime")

    def today(self):
        return timezone.now().astimezone(ZONE).date()

    def summary(self, user, start=None, end=None):
        start = start or self.today()
        return self.client_as(user).get(
            f"/api/v1/reports/summary/?start={start}&end={end or start}"
        )

    def test_policy_versions_are_validated_frozen_and_append_only(self):
        admin = self.client_as(self.admin)
        path = "/api/v1/settings/sla-policies/"
        for bad in [
            {"timezone": "Mars/Base"},
            {"end_time": "07:00"},
            {"weekdays": "1,9"},
            {"holidays": "25/12/2026"},
            {"p1_response": 999},
        ]:
            self.assertEqual(self.post(admin, path, {**SLA_INPUT, **bad}).status_code, 400, bad)
        self.assertEqual(self.post(self.client_as(self.manager), path, SLA_INPUT).status_code, 403)
        response = self.post(admin, path, SLA_INPUT)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["holidays"], "2026-11-02 2026-12-25")
        first = SlaPolicy.objects.get(pk=response.json()["id"])
        ticket = self.create()
        self.assertEqual(self.post(admin, path, {**SLA_INPUT, "reason": "Nova"}).status_code, 201)
        ticket.refresh_from_db()
        self.assertEqual(ticket.sla_policy_id, first.pk)
        self.assertNotEqual(self.create().sla_policy_id, first.pk)
        with self.assertRaises(DatabaseError), transaction.atomic():
            SlaPolicy.objects.filter(pk=first.pk).update(p1_response=1)
        self.assertTrue(IdentityEvent.objects.filter(action="sla_policy.created").exists())

    def test_report_scope_reconciles_and_respects_period_bounds(self):
        self.post(self.client_as(self.admin), "/api/v1/settings/sla-policies/", SLA_INPUT)
        open_ticket = self.create()
        self.resolve(self.create())
        self.create(category=self.restricted_category.pk)
        cancelled = self.create()
        self.transition(cancelled, self.owner, "cancel", message="Não preciso mais")
        for user in [self.owner, self.tech]:
            self.assertEqual(self.summary(user).status_code, 403)
        data = self.summary(self.manager).json()
        self.assertEqual(data["created"], 4)
        self.assertEqual(data["resolved"], 1)
        self.assertTrue(data["has_scope"])
        self.assertEqual(data["cancelled"], 1)
        self.assertEqual(data["backlog_at_end"], 2)
        self.assertEqual(sum(row["count"] for row in data["open_by_state"]), 2)
        for clock in ("response", "resolution"):
            counts = data[clock]
            self.assertEqual(counts["met"] + counts["breached"] + counts["pending"], 4)
        self.assertEqual(data["response"]["met"], 1)
        self.assertEqual(data["open_by_assignee"], [])
        # Admin has full access, restricted tickets and individual figures included.
        admin_data = self.summary(self.admin).json()
        self.assertEqual(admin_data["created"], 4)
        self.assertTrue(admin_data["has_scope"])
        self.assertEqual(admin_data["open_by_assignee"], [])
        # Calendar days are local: 23:59 of the previous day belongs to that day only.
        late = datetime.combine(self.today() - timedelta(days=1), time(23, 59), tzinfo=ZONE)
        Ticket.objects.filter(pk=open_ticket.pk).update(created_at=late)
        yesterday = self.today() - timedelta(days=1)
        self.assertEqual(self.summary(self.manager, yesterday).json()["created"], 1)
        self.assertEqual(self.summary(self.manager).json()["created"], 3)
        self.assertEqual(self.summary(self.manager, self.today(), yesterday).status_code, 400)
        self.assertEqual(
            self.summary(self.manager, yesterday - timedelta(days=400), yesterday).status_code,
            400,
        )

    def test_export_escapes_formulas_expires_and_is_owner_only(self):
        self.create(subject='=HYPERLINK("http://x")')
        self.create(subject="@SUM(1)")
        self.create(subject="Impressora;=1+1;ok")
        manager = self.client_as(self.manager)
        response = self.post(
            manager,
            "/api/v1/reports/exports/",
            {"start": str(self.today()), "end": str(self.today())},
        )
        self.assertEqual(response.status_code, 201, response.content)
        export_id = response.json()["id"]
        download = manager.get(f"/api/v1/reports/exports/{export_id}/")
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download["Cache-Control"], "no-store")
        rows = list(csv.reader(io.StringIO(download.content.decode("utf-8-sig"))))
        self.assertIn("responsavel", rows[0])
        subjects = {row[rows[0].index("assunto")] for row in rows[1:]}
        self.assertEqual(subjects, {'\'=HYPERLINK("http://x")', "'@SUM(1)", "Impressora;=1+1;ok"})
        # Every field is quoted, so a ";" list separator cannot start a new formula cell.
        self.assertIn('"Impressora;=1+1;ok"', download.content.decode("utf-8-sig"))
        for user in [self.admin, self.tech]:
            self.assertIn(
                self.client_as(user).get(f"/api/v1/reports/exports/{export_id}/").status_code,
                {403, 404},
            )
        self.assertEqual(
            self.post(self.client_as(self.tech), "/api/v1/reports/exports/", {}).status_code, 403
        )
        for action in ["report.exported", "report.downloaded"]:
            self.assertTrue(
                IdentityEvent.objects.filter(action=action, actor=self.manager).exists()
            )
        ReportExport.objects.filter(pk=export_id).update(expires_at=timezone.now())
        self.assertEqual(manager.get(f"/api/v1/reports/exports/{export_id}/").status_code, 404)
        self.assertEqual(cleanup_exports(), 1)

    def test_breach_alert_is_internal_and_recorded_once(self):
        targets = {f"p{p}_{c}": 1 for p in range(1, 5) for c in ("response", "resolution")}
        SlaPolicy.objects.create(
            actor=self.admin,
            reason="Sintética",
            weekdays="0,1,2,3,4,5,6",
            start_time=time(0),
            end_time=time(23, 59),
            **targets,
        )
        ticket = self.create()
        later = timezone.now() + timedelta(days=3)
        self.assertEqual(alert_breaches(later), 2)
        self.assertEqual(alert_breaches(later), 0)
        alerts = ticket.events.filter(action="sla.breached")
        self.assertEqual(sorted(e.changes["clock"] for e in alerts), ["resolution", "response"])
        self.assertTrue(all(e.visibility == "internal" for e in alerts))
        self.assertEqual(
            {o.audience for o in NotificationOutbox.objects.filter(event__in=alerts)}, {"support"}
        )
        self.assertNotIn(
            "sla.breached",
            [e["action"] for e in self.read(ticket, self.owner, "events/").json()["results"]],
        )
        ticket.refresh_from_db()
        self.assertEqual(ticket.state, "new")
