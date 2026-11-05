"""Read-only administrator view over the identity and ticket audit trails."""

from django.db.models import CharField, F, Value
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast
from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers
from rest_framework.exceptions import ValidationError

from core.authentication import IsIdentityAdmin
from core.identity_views import NoStoreMixin
from core.models import IdentityEvent
from core.serializers import StrictSerializer
from tickets.models import AuditEvent
from tickets.reports import bounds

COLUMNS = [
    "created_at",
    "actor_id",
    "action",
    "source",
    "subject",
    "actor_name",
    "actor_email",
    "reason",
]


class AuditFilter(StrictSerializer):
    user = serializers.IntegerField(min_value=1, required=False)
    start = serializers.DateField(required=False)
    end = serializers.DateField(required=False)
    page = serializers.IntegerField(min_value=1, required=False)


class AuditRow(serializers.Serializer):
    created_at = serializers.DateTimeField()
    actor_id = serializers.IntegerField(allow_null=True)
    actor_name = serializers.CharField(allow_null=True)
    actor_email = serializers.CharField(allow_null=True)
    action = serializers.CharField()
    source = serializers.ChoiceField(choices=["identity", "ticket"])
    subject = serializers.CharField()
    reason = serializers.CharField(allow_null=True)


def narrowed(queryset, filters):
    if "user" in filters:
        queryset = queryset.filter(actor_id=filters["user"])
    if "start" in filters:
        queryset = queryset.filter(created_at__gte=bounds(filters["start"], filters["start"])[0])
    if "end" in filters:
        queryset = queryset.filter(created_at__lt=bounds(filters["end"], filters["end"])[1])
    return queryset.annotate(actor_name=F("actor__first_name"), actor_email=F("actor__email"))


class AuditLogView(NoStoreMixin, generics.ListAPIView):
    serializer_class = AuditRow
    permission_classes = [IsIdentityAdmin]

    @extend_schema(parameters=[AuditFilter])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return IdentityEvent.objects.none()
        form = AuditFilter(data=self.request.query_params.dict())
        form.is_valid(raise_exception=True)
        filters = form.validated_data
        if {"start", "end"} <= set(filters) and filters["end"] < filters["start"]:
            raise ValidationError({"end": "A data final deve ser depois da inicial."})
        identity = narrowed(IdentityEvent.objects.all(), filters).annotate(
            source=Value("identity", output_field=CharField()),
            subject=Cast("subject_id", CharField()),
            reason=KeyTextTransform("reason", "changes"),
        )
        tickets = narrowed(AuditEvent.objects.all(), filters).annotate(
            source=Value("ticket", output_field=CharField()),
            subject=Cast("event__ticket__number", CharField()),
            reason=Value(None, output_field=CharField()),
        )
        # shortcut: sorts both tables on each request, add created_at indexes if the log grows.
        return (
            identity.values(*COLUMNS)
            .union(tickets.values(*COLUMNS), all=True)
            .order_by("-created_at", "-subject")
        )
