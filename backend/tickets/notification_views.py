from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from core import identity
from core.authentication import IsIdentityAdmin
from core.identity_views import NoStoreMixin, locked_actor
from core.models import User
from core.serializers import StrictSerializer
from tickets.models import (
    Comment,
    IntegrationCheck,
    NotificationDelivery,
    NotificationOutbox,
    TicketEvent,
)
from tickets.permissions import can_read_internal, visible_tickets


class DeliveryOutput(serializers.ModelSerializer):
    ticket_number = serializers.IntegerField(source="outbox.event.ticket.number", read_only=True)
    event_action = serializers.CharField(source="outbox.event.action", read_only=True)
    recipient = serializers.SerializerMethodField()

    def get_recipient(self, obj) -> str:
        if obj.channel == NotificationDelivery.Channel.CHAT:
            return "Espaço geral da TI"
        if obj.channel == NotificationDelivery.Channel.CHAT_DM:
            return "Conversa individual"
        local, _, domain = obj.recipient_key.partition("@")
        return f"{local[:1]}***@{domain}" if domain else "Destinatário protegido"

    class Meta:
        model = NotificationDelivery
        fields = [
            "id",
            "ticket_number",
            "event_action",
            "channel",
            "recipient",
            "status",
            "attempts",
            "next_attempt_at",
            "last_attempt_at",
            "sent_at",
            "provider_id",
            "last_error_code",
        ]


class RetryInput(StrictSerializer):
    reason = serializers.CharField(max_length=300)


class IntegrationTestInput(RetryInput):
    channel = serializers.ChoiceField(choices=NotificationDelivery.Channel.choices)


class IntegrationCheckOutput(serializers.ModelSerializer):
    class Meta:
        model = IntegrationCheck
        fields = ["id", "channel", "status", "created_at", "completed_at", "error_code"]


class NotificationDiagnosticsView(NoStoreMixin, APIView):
    permission_classes = [IsIdentityAdmin]

    @extend_schema(responses=DeliveryOutput(many=True))
    def get(self, request):
        queryset = NotificationDelivery.objects.select_related("outbox__event__ticket").order_by(
            "-last_attempt_at", "-id"
        )[:200]
        return Response(DeliveryOutput(queryset, many=True).data)


class NotificationRetryView(NoStoreMixin, APIView):
    permission_classes = [IsIdentityAdmin]

    @extend_schema(request=RetryInput, responses=DeliveryOutput)
    @transaction.atomic
    def post(self, request, delivery_id):
        identity.identity_lock()
        actor = locked_actor(request, admin=True)
        serializer = RetryInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        delivery = get_object_or_404(
            NotificationDelivery.objects.select_for_update(of=("self",)).select_related(
                "outbox__event__ticket"
            ),
            pk=delivery_id,
        )
        if delivery.status not in {"failed", "retry"}:
            return Response(
                {"detail": "Somente entregas com falha podem ser reenviadas."}, status=409
            )
        delivery.status = "pending"
        delivery.next_attempt_at = timezone.now()
        delivery.last_error_code = ""
        delivery.save(update_fields=["status", "next_attempt_at", "last_error_code"])
        NotificationOutbox.objects.filter(pk=delivery.outbox_id).update(
            status="pending", available_at=timezone.now(), completed_at=None
        )
        identity.audit(
            actor,
            "notification.requeued",
            delivery.pk,
            {
                "reason": serializer.validated_data["reason"],
                "channel": delivery.channel,
                "ticket": delivery.outbox.event.ticket.number,
            },
        )
        return Response(DeliveryOutput(delivery).data)


class IntegrationTestView(NoStoreMixin, APIView):
    permission_classes = [IsIdentityAdmin]

    @extend_schema(responses=IntegrationCheckOutput(many=True))
    def get(self, request):
        queryset = IntegrationCheck.objects.order_by("-id")[:20]
        return Response(IntegrationCheckOutput(queryset, many=True).data)

    @extend_schema(request=IntegrationTestInput, responses={202: IntegrationCheckOutput})
    @transaction.atomic
    def post(self, request):
        identity.identity_lock()
        actor = locked_actor(request, admin=True)
        serializer = IntegrationTestInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        channel = serializer.validated_data["channel"]
        check = IntegrationCheck.objects.create(channel=channel, requested_by=actor)
        identity.audit(
            actor,
            "integration.test_requested",
            check.pk,
            {"reason": serializer.validated_data["reason"], "channel": channel},
        )
        return Response(IntegrationCheckOutput(check).data, status=202)


class InboxItem(serializers.ModelSerializer):
    ticket_id = serializers.UUIDField(source="ticket.uuid", read_only=True)
    number = serializers.IntegerField(source="ticket.number", read_only=True)
    subject = serializers.CharField(source="ticket.subject", read_only=True)
    actor_name = serializers.CharField(source="actor.first_name", read_only=True)

    class Meta:
        model = TicketEvent
        fields = ["id", "ticket_id", "number", "subject", "action", "actor_name", "created_at"]


class InboxOutput(serializers.Serializer):
    muted = serializers.BooleanField()
    results = InboxItem(many=True)


class InboxInput(StrictSerializer):
    muted = serializers.BooleanField()


class InboxView(NoStoreMixin, APIView):
    """Events by others on tickets the user requested or works on.

    Support and admins also see new tickets.
    """

    def payload(self, user):
        scope = Q(ticket__requester=user) | Q(ticket__assignee=user) | Q(ticket__participants=user)
        if user.role in {User.Role.TECHNICIAN, User.Role.MANAGER, User.Role.ADMIN}:
            scope |= Q(action="created")
        events = (
            TicketEvent.objects.filter(scope, ticket__in=visible_tickets(user))
            .exclude(actor=user)
            .select_related("ticket", "actor")
            .distinct()
            .order_by("-created_at")
        )
        if user.notifications_cleared_at:
            events = events.filter(created_at__gt=user.notifications_cleared_at)
        internal = {}
        results = []
        for event in events[:50]:
            if event.visibility == Comment.Visibility.INTERNAL:
                if event.ticket_id not in internal:
                    internal[event.ticket_id] = can_read_internal(user, event.ticket)
                if not internal[event.ticket_id]:
                    continue
            results.append(event)
        return InboxOutput({"muted": user.notifications_muted, "results": results[:20]}).data

    @extend_schema(responses=InboxOutput)
    def get(self, request):
        return Response(self.payload(request.user))

    @extend_schema(request=InboxInput, responses=InboxOutput)
    def patch(self, request):
        serializer = InboxInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        request.user.notifications_muted = serializer.validated_data["muted"]
        request.user.save(update_fields=["notifications_muted"])
        return Response(self.payload(request.user))


class InboxClearView(NoStoreMixin, APIView):
    @extend_schema(request=None, responses=InboxOutput)
    def post(self, request):
        request.user.notifications_cleared_at = timezone.now()
        request.user.save(update_fields=["notifications_cleared_at"])
        return Response(InboxView().payload(request.user))
