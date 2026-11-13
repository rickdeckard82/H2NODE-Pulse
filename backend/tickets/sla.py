"""SLA clocks derived from the immutable ticket event history.

Every pause and resume is already a TicketEvent (from_state/to_state), so the
intervals are rebuilt from history instead of being stored a second time.
"""

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

RUNNING = {"new", "in_progress"}
PAUSED = {"waiting_information", "waiting_test", "paused"}
STOPPED = {"resolved", "closed", "cancelled"}


def holidays(policy):
    return {date.fromisoformat(item) for item in policy.holidays.replace(",", " ").split()}


def business_seconds(policy, start, end):
    """Seconds of [start, end) that fall inside the policy's working hours."""
    if end <= start:
        return 0
    zone = ZoneInfo(policy.timezone)
    days = {int(item) for item in policy.weekdays.split(",") if item.strip()}
    off = holidays(policy)
    day, last = start.astimezone(zone).date(), end.astimezone(zone).date()
    total = 0.0
    while day <= last:
        if day.weekday() in days and day not in off:
            # Converting to UTC makes the subtraction real time, also across DST changes.
            opens = datetime.combine(day, policy.start_time, tzinfo=zone).astimezone(UTC)
            closes = datetime.combine(day, policy.end_time, tzinfo=zone).astimezone(UTC)
            total += max(0.0, (min(end, closes) - max(start, opens)).total_seconds())
        day += timedelta(days=1)
    return int(total)


def target(policy, priority, clock):
    return getattr(policy, f"p{priority}_{clock}") * 60


def measure(ticket, events, now):
    """Clocks for one ticket; `events` must be its full history ordered by version."""
    policy = ticket.sla_policy
    spans = list(zip(events, [*events[1:], None], strict=True))
    first = next(
        (
            e.created_at
            for e in events
            if e.comment_id and e.visibility == "public" and e.actor_id != ticket.requester_id
        ),
        None,
    )
    state = events[-1].to_state if events else ticket.state
    elapsed = sum(
        ((nxt.created_at if nxt else now) - e.created_at).total_seconds()
        for e, nxt in spans
        if e.to_state in RUNNING | PAUSED
    )
    result = {
        "state": state,
        "elapsed_seconds": int(elapsed),
        "first_response_at": first,
        "response_seconds": None,
        "resolution_seconds": None,
        "response_met": None,
        "resolution_met": None,
        "reopens": sum(e.action == "reopen" for e in events),
    }
    if not policy or not events:
        return result
    running = sum(
        business_seconds(policy, e.created_at, nxt.created_at if nxt else now)
        for e, nxt in spans
        if e.to_state in RUNNING
    )
    result["resolution_seconds"] = running
    response_limit = target(policy, ticket.priority, "response")
    resolution_limit = target(policy, ticket.priority, "resolution")
    if first:
        result["response_seconds"] = business_seconds(policy, events[0].created_at, first)
        result["response_met"] = result["response_seconds"] <= response_limit
    elif state not in STOPPED and business_seconds(policy, events[0].created_at, now) > (
        response_limit
    ):
        result["response_met"] = False
    if state in {"resolved", "closed"}:
        result["resolution_met"] = running <= resolution_limit
    elif state != "cancelled" and running > resolution_limit:
        result["resolution_met"] = False
    return result


def histories(tickets):
    from tickets.models import TicketEvent

    found = defaultdict(list)
    for event in TicketEvent.objects.filter(ticket__in=tickets).order_by("ticket_id", "version"):
        found[event.ticket_id].append(event)
    return found


def system_actor():
    from core.models import User

    # Registered accounts use random hex usernames, so this one cannot be claimed.
    return User.objects.get_or_create(
        username="system:sla", defaults={"first_name": "Sistema (SLA)", "is_active": False}
    )[0]


def alert_breaches(now=None):
    """Record one internal history event per ticket and clock once its SLA is exceeded."""
    from tickets.models import Comment, Ticket
    from tickets.services import advance, emit

    now = now or timezone.now()
    # shortcut: rescans every open ticket each run; add a due-at index if the open queue gets large.
    candidates = (
        Ticket.objects.filter(sla_policy__isnull=False)
        .exclude(state__in=STOPPED)
        .select_related("sla_policy")
    )
    history = histories(candidates)
    created = 0
    for ticket in candidates:
        events = history[ticket.pk]
        clocks = measure(ticket, events, now)
        done = {e.changes.get("clock") for e in events if e.action == "sla.breached"}
        for clock in ("response", "resolution"):
            if clocks[f"{clock}_met"] is not False or clock in done:
                continue
            with transaction.atomic():
                locked = Ticket.objects.select_for_update(of=("self",)).get(pk=ticket.pk)
                if (
                    locked.state in STOPPED
                    or locked.events.filter(action="sla.breached", changes__clock=clock).exists()
                ):
                    continue
                advance(locked)
                emit(
                    locked,
                    system_actor(),
                    "sla.breached",
                    locked.state,
                    changes={"clock": clock},
                    visibility=Comment.Visibility.INTERNAL,
                )
                created += 1
    return created
