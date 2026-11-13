"""SLA policy administration, management reports and short-lived CSV exports."""

import csv
import io
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from django.db.models import Count
from django.http import Http404, HttpResponse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, mixins, serializers, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from core import identity
from core.authentication import IsIdentityAdmin
from core.identity_views import NoStoreMixin, locked_actor
from core.models import User
from tickets.models import ReportExport, SlaPolicy, TicketEvent
from tickets.permissions import report_tickets, support_memberships
from tickets.serializers import StrictModelSerializer
from tickets.sla import STOPPED, histories, holidays, measure

ZONE = ZoneInfo("America/Sao_Paulo")
EXPORT_MINUTES = 15
MAX_DAYS = 366
TARGETS = [f"p{p}_{clock}" for p in range(1, 5) for clock in ("response", "resolution")]


class SlaPolicySerializer(StrictModelSerializer):
    class Meta:
        model = SlaPolicy
        fields = [
            "id",
            "actor",
            "created_at",
            "reason",
            "timezone",
            "weekdays",
            "start_time",
            "end_time",
            "holidays",
            *TARGETS,
        ]
        read_only_fields = ["id", "actor", "created_at"]
        extra_kwargs = {name: {"min_value": 1, "max_value": 525600} for name in TARGETS}

    def validate_timezone(self, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError, ValueError:
            raise serializers.ValidationError("Fuso horário IANA inválido.") from None
        return value

    def validate_weekdays(self, value):
        days = [item.strip() for item in value.split(",") if item.strip()]
        if not days or any(item not in "0123456" or len(item) != 1 for item in days):
            raise serializers.ValidationError("Use dias de 0 (segunda) a 6 (domingo).")
        return ",".join(sorted(set(days)))

    def validate_holidays(self, value):
        try:
            return " ".join(sorted(day.isoformat() for day in holidays(SlaPolicy(holidays=value))))
        except ValueError:
            raise serializers.ValidationError("Use datas AAAA-MM-DD separadas.") from None

    def validate(self, attrs):
        if attrs["end_time"] <= attrs["start_time"]:
            raise serializers.ValidationError({"end_time": "O fim deve ser depois do início."})
        for priority in range(1, 5):
            if attrs[f"p{priority}_response"] > attrs[f"p{priority}_resolution"]:
                raise serializers.ValidationError(
                    {f"p{priority}_response": "A resposta não pode exceder a resolução."}
                )
        return attrs


class SlaPolicyViewSet(
    NoStoreMixin, mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    serializer_class = SlaPolicySerializer
    permission_classes = [IsIdentityAdmin]
    queryset = SlaPolicy.objects.order_by("-id")

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        identity.identity_lock()
        locked_actor(request, admin=True)
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        obj = serializer.save(actor=self.request.user)
        identity.audit(self.request.user, "sla_policy.created", obj.pk, {"reason": obj.reason})


class PeriodInput(serializers.Serializer):
    start = serializers.DateField()
    end = serializers.DateField()

    def validate(self, attrs):
        if not timedelta(0) <= attrs["end"] - attrs["start"] < timedelta(days=MAX_DAYS):
            raise serializers.ValidationError(f"Período inválido; máximo de {MAX_DAYS} dias.")
        return attrs


def bounds(start, end):
    """Local calendar days, end inclusive, as a half-open UTC-comparable range."""
    return (
        datetime.combine(start, time(), tzinfo=ZONE),
        datetime.combine(end + timedelta(days=1), time(), tzinfo=ZONE),
    )


def require_reports(user):
    if user.role not in {User.Role.MANAGER, User.Role.ADMIN}:
        raise PermissionDenied("Relatórios exigem perfil de gestão autorizado.")


def cohort(user, start, end, now):
    low, high = bounds(start, end)
    tickets = list(
        report_tickets(user)
        .filter(created_at__gte=low, created_at__lt=high)
        .select_related("sla_policy", "group", "assignee")
        .order_by("number")
    )
    history = histories(tickets)
    return [(ticket, measure(ticket, history[ticket.pk], now)) for ticket in tickets]


def clock_summary(rows, clock):
    measured = [m[f"{clock}_seconds"] for _, m in rows if m[f"{clock}_met"] is not None]
    return {
        "met": sum(m[f"{clock}_met"] is True for _, m in rows),
        "breached": sum(m[f"{clock}_met"] is False for _, m in rows),
        "pending": sum(m[f"{clock}_met"] is None for _, m in rows),
        "average_minutes": round(sum(measured) / len(measured) / 60, 1) if measured else None,
    }


def summarize(user, start, end, now):
    scope = report_tickets(user)
    low, high = bounds(start, end)
    period = TicketEvent.objects.filter(ticket__in=scope, created_at__gte=low, created_at__lt=high)
    # State at the end of the period comes from the last event recorded before it.
    states_at_end = (
        TicketEvent.objects.filter(ticket__in=scope, created_at__lt=high)
        .order_by("ticket_id", "-version")
        .distinct("ticket_id")
        .values_list("to_state", flat=True)
    )
    open_now = scope.exclude(state__in=STOPPED)
    rows = cohort(user, start, end, now)
    summary = {
        "start": start,
        "end": end,
        "timezone": str(ZONE),
        "created": len(rows),
        "resolved": period.filter(action="resolve").count(),
        "cancelled": period.filter(action="cancel").count(),
        "closed": period.filter(action__in=["close", "confirm"]).count(),
        # A manager outside any group has an empty report.
        "has_scope": user.role == User.Role.ADMIN or support_memberships(user).exists(),
        "reopened": period.filter(action="reopen").count(),
        "backlog_at_end": sum(state not in STOPPED for state in states_at_end),
        "without_policy": sum(ticket.sla_policy_id is None for ticket, _ in rows),
        "response": clock_summary(rows, "response"),
        "resolution": clock_summary(rows, "resolution"),
        "open_by_state": list(
            open_now.values("state").annotate(count=Count("pk")).order_by("state")
        ),
        "open_by_group": list(
            open_now.values("group__name").annotate(count=Count("pk")).order_by("group__name")
        ),
        "open_by_assignee": None,
    }
    # Individual performance is only shown to report roles, never to technicians.
    if user.role in {User.Role.MANAGER, User.Role.ADMIN}:
        summary["open_by_assignee"] = list(
            open_now.filter(assignee__isnull=False)
            .values("assignee__first_name")
            .annotate(count=Count("pk"))
            .order_by("assignee__first_name")
        )
    return summary


class CountRow(serializers.Serializer):
    count = serializers.IntegerField()


class ClockSummary(serializers.Serializer):
    met = serializers.IntegerField()
    breached = serializers.IntegerField()
    pending = serializers.IntegerField()
    average_minutes = serializers.FloatField(allow_null=True)


class SummaryOutput(serializers.Serializer):
    start = serializers.DateField()
    end = serializers.DateField()
    timezone = serializers.CharField()
    created = serializers.IntegerField()
    resolved = serializers.IntegerField()
    cancelled = serializers.IntegerField()
    closed = serializers.IntegerField()
    has_scope = serializers.BooleanField()
    reopened = serializers.IntegerField()
    backlog_at_end = serializers.IntegerField()
    without_policy = serializers.IntegerField()
    response = ClockSummary()
    resolution = ClockSummary()
    open_by_state = serializers.ListField(child=serializers.DictField())
    open_by_group = serializers.ListField(child=serializers.DictField())
    open_by_assignee = serializers.ListField(child=serializers.DictField(), allow_null=True)


class SummaryView(NoStoreMixin, generics.GenericAPIView):
    serializer_class = SummaryOutput

    @extend_schema(
        parameters=[
            OpenApiParameter("start", OpenApiTypes.DATE, required=True),
            OpenApiParameter("end", OpenApiTypes.DATE, required=True),
        ]
    )
    def get(self, request):
        require_reports(request.user)
        period = PeriodInput(data=request.query_params)
        period.is_valid(raise_exception=True)
        data = period.validated_data
        return Response(
            SummaryOutput(summarize(request.user, data["start"], data["end"], timezone.now())).data
        )


def cell(value):
    """Neutralise spreadsheet formulas (CSV injection) in every exported text cell."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in {"=", "+", "-", "@", "\t", "\r"} else text


def minutes(seconds):
    return None if seconds is None else round(seconds / 60, 1)


def yes_no(value):
    return {True: "sim", False: "não", None: ""}[value]


def render_csv(user, rows):
    individual = user.role in {User.Role.MANAGER, User.Role.ADMIN}
    out = io.StringIO()
    # Quoting every field keeps a regional ";" separator from opening new (formula) cells.
    writer = csv.writer(out, quoting=csv.QUOTE_ALL)
    header = [
        "numero",
        "aberto_em",
        "estado",
        "prioridade",
        "grupo",
        "assunto",
        "primeira_resposta_min_uteis",
        "resposta_no_prazo",
        "resolucao_min_uteis",
        "resolucao_no_prazo",
        "decorrido_min",
        "reaberturas",
        "avaliacao",
    ]
    writer.writerow(header + (["responsavel"] if individual else []))
    for ticket, m in rows:
        line = [
            ticket.number,
            ticket.created_at.astimezone(ZONE).strftime("%Y-%m-%d %H:%M"),
            m["state"],
            ticket.priority,
            ticket.group.name,
            ticket.subject,
            minutes(m["response_seconds"]),
            yes_no(m["response_met"]),
            minutes(m["resolution_seconds"]),
            yes_no(m["resolution_met"]),
            minutes(m["elapsed_seconds"]),
            m["reopens"],
            ticket.rating or "",
        ]
        if individual:
            line.append(ticket.assignee.first_name if ticket.assignee else "")
        writer.writerow([cell(value) for value in line])
    return out.getvalue()


class ExportOutput(serializers.ModelSerializer):
    class Meta:
        model = ReportExport
        fields = ["id", "created_at", "expires_at", "start", "end", "rows"]


class ExportView(NoStoreMixin, generics.GenericAPIView):
    serializer_class = PeriodInput

    @extend_schema(responses={201: ExportOutput})
    @transaction.atomic
    def post(self, request):
        user = locked_actor(request)
        require_reports(user)
        period = self.get_serializer(data=request.data)
        period.is_valid(raise_exception=True)
        start, end = period.validated_data["start"], period.validated_data["end"]
        now = timezone.now()
        rows = cohort(user, start, end, now)
        export = ReportExport.objects.create(
            user=user,
            created_at=now,
            expires_at=now + timedelta(minutes=EXPORT_MINUTES),
            start=start,
            end=end,
            rows=len(rows),
            content=render_csv(user, rows),
        )
        identity.audit(
            user,
            "report.exported",
            export.pk,
            {"start": start.isoformat(), "end": end.isoformat(), "rows": len(rows)},
        )
        return Response(ExportOutput(export).data, status=201)


class ExportDownloadView(NoStoreMixin, generics.GenericAPIView):
    serializer_class = ExportOutput

    @extend_schema(responses={(200, "text/csv"): OpenApiTypes.STR})
    def get(self, request, export_id):
        require_reports(request.user)
        export = ReportExport.objects.filter(
            pk=export_id, user=request.user, expires_at__gt=timezone.now()
        ).first()
        if not export:
            raise Http404
        identity.audit(request.user, "report.downloaded", export.pk)
        response = HttpResponse("﻿" + export.content, content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="chamados-{export.start}-a-{export.end}.csv"'
        )
        return response


def cleanup_exports():
    return ReportExport.objects.filter(expires_at__lte=timezone.now()).delete()[0]
