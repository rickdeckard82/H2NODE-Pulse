from django.db import transaction
from django.db.models import Q
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core import identity
from core.authentication import IsIdentityAdmin
from core.identity_views import AdminWriteViewSet, NoStoreMixin, locked_actor
from core.models import Membership, SupportGroup, User
from tickets import services
from tickets.client_ip import client_ip
from tickets.models import Category, ReopenPolicy, Ticket
from tickets.permissions import visible_history, visible_tickets
from tickets.serializers import (
    CategorySerializer,
    CommentInput,
    CommentSerializer,
    CreateInput,
    EventSerializer,
    MutationResult,
    QueueFilters,
    ReopenPolicySerializer,
    TicketSerializer,
    TransferInput,
    TransferOptionSerializer,
    TransitionInput,
    VersionInput,
)

KEY_PARAMETER = OpenApiParameter(
    "Idempotency-Key",
    OpenApiTypes.UUID,
    OpenApiParameter.HEADER,
    required=True,
    description="Chave única por usuário/operação. Reuso com payload diferente retorna 409.",
)


@extend_schema_view(list=extend_schema(parameters=[QueueFilters]))
class TicketViewSet(
    NoStoreMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    serializer_class = TicketSerializer
    lookup_field = "uuid"
    lookup_value_regex = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Ticket.objects.none()
        queryset = (
            visible_tickets(self.request.user)
            .select_related("requester", "assignee", "related_ticket", "group")
            .prefetch_related("participants")
        )
        if self.action != "list":
            return queryset
        params = self.request.query_params.dict()
        if "state" in params:
            # Accepts state=a&state=b (as documented) and state=a,b (as the portal sends).
            values = self.request.query_params.getlist("state")
            params["state"] = [s for v in values for s in v.split(",") if s]
        filters = QueueFilters(data=params)
        filters.is_valid(raise_exception=True)
        data = dict(filters.validated_data)
        if states := data.pop("state", None):
            data["state__in"] = states
        ordering = data.pop("ordering", "-created_at")
        search = data.pop("search", "")
        data.pop("page", None)
        if search:
            queryset = queryset.filter(
                Q(subject__icontains=search) | Q(description__icontains=search)
            )
        return queryset.filter(**data).order_by(ordering, "number")

    def mutate(self, request, operation, serializer_type, mutation, uuid=None, status_code=200):
        serializer = serializer_type(data=request.data)
        serializer.is_valid(raise_exception=True)
        body, status, replay = services.execute(
            request, operation, serializer.validated_data, mutation, uuid, status_code
        )
        return Response(body, status=status, headers={"Idempotent-Replayed": str(replay).lower()})

    @extend_schema(request=CreateInput, responses={201: MutationResult}, parameters=[KEY_PARAMETER])
    def create(self, request):
        ip = client_ip(request)
        return self.mutate(
            request,
            "create",
            CreateInput,
            lambda actor, ticket, data: services.create_ticket(actor, ticket, data, ip),
            status_code=201,
        )

    @extend_schema(
        request=VersionInput,
        responses={200: MutationResult, 409: OpenApiTypes.OBJECT},
        parameters=[KEY_PARAMETER],
    )
    @action(detail=True, methods=["post"])
    def claim(self, request, uuid=None):
        return self.mutate(request, "claim", VersionInput, services.claim, uuid)

    @extend_schema(
        request=VersionInput,
        responses={200: MutationResult, 409: OpenApiTypes.OBJECT},
        parameters=[KEY_PARAMETER],
    )
    @action(detail=True, methods=["post"])
    def join(self, request, uuid=None):
        return self.mutate(request, "join", VersionInput, services.join, uuid)

    @extend_schema(
        request=TransitionInput,
        responses={200: MutationResult, 409: OpenApiTypes.OBJECT},
        parameters=[KEY_PARAMETER],
    )
    @action(detail=True, methods=["post"])
    def transitions(self, request, uuid=None):
        return self.mutate(request, "transition", TransitionInput, services.transition, uuid)

    @extend_schema(
        request=TransferInput,
        responses={200: MutationResult, 409: OpenApiTypes.OBJECT},
        parameters=[KEY_PARAMETER],
    )
    @action(detail=True, methods=["post"])
    def transfer(self, request, uuid=None):
        return self.mutate(request, "transfer", TransferInput, services.transfer, uuid)

    @extend_schema(responses=TransferOptionSerializer(many=True))
    @action(detail=True, methods=["get"], url_path="transfer-options")
    def transfer_options(self, request, uuid=None):
        from rest_framework.exceptions import PermissionDenied

        from tickets.permissions import membership

        ticket = self.get_object()
        member = membership(request.user, ticket)
        if not member or not member.can_transfer:
            raise PermissionDenied("Sem permissão de transferência.")
        if request.user.role == User.Role.ADMIN:
            # Admins may transfer to any active group (services.transfer), member or not.
            groups = SupportGroup.objects.filter(is_active=True).values("pk")
        else:
            own = Membership.objects.filter(user=request.user, group__is_active=True)
            if ticket.restricted:
                own = own.filter(can_view_restricted=True)
            groups = own.values("group_id")
        candidates = (
            Membership.objects.filter(
                group_id__in=groups,
                user__is_active=True,
                user__email_verified_at__isnull=False,
                user__role__in=[User.Role.TECHNICIAN, User.Role.MANAGER],
            )
            .exclude(user_id=ticket.requester_id)
            .select_related("user", "group")
            .order_by("group_id", "user_id")
        )
        if ticket.restricted:
            candidates = candidates.filter(can_view_restricted=True)
        page = self.paginate_queryset(candidates)
        return self.get_paginated_response(
            [
                {
                    "group": m.group_id,
                    "group_name": m.group.name,
                    "user": m.user_id,
                    "user_name": m.user.first_name,
                }
                for m in page
                if identity.eligible(m.user)
            ]
        )

    @extend_schema(responses=CommentSerializer(many=True))
    @action(detail=True, methods=["get"])
    def comments(self, request, uuid=None):
        ticket = self.get_object()
        queryset = visible_history(ticket.comments.select_related("actor"), request.user, ticket)
        return self.get_paginated_response(
            CommentSerializer(self.paginate_queryset(queryset), many=True).data
        )

    @extend_schema(
        request=CommentInput,
        responses={201: MutationResult, 409: OpenApiTypes.OBJECT},
        parameters=[KEY_PARAMETER],
    )
    @comments.mapping.post
    def create_comment(self, request, uuid=None):
        return self.mutate(
            request, "comment", CommentInput, services.add_comment, uuid, status_code=201
        )

    @extend_schema(responses=EventSerializer(many=True))
    @action(detail=True, methods=["get"])
    def events(self, request, uuid=None):
        ticket = self.get_object()
        queryset = visible_history(
            ticket.events.select_related("actor", "comment__actor"), request.user, ticket
        )
        return self.get_paginated_response(
            EventSerializer(self.paginate_queryset(queryset), many=True).data
        )


class CategoryViewSet(AdminWriteViewSet):
    serializer_class = CategorySerializer

    def get_queryset(self):
        queryset = Category.objects.order_by("id")
        if getattr(self, "swagger_fake_view", False):
            return queryset.none()
        return (
            queryset
            if self.request.user.role == User.Role.ADMIN
            else queryset.filter(is_active=True, group__is_active=True)
        )

    def perform_create(self, serializer):
        obj = serializer.save()
        identity.audit(
            self.request.user,
            "category.created",
            obj.pk,
            {
                "name": obj.name,
                "group": obj.group_id,
                "restricted": obj.restricted,
                "priority": obj.priority,
            },
        )

    def perform_update(self, serializer):
        before = {
            "name": serializer.instance.name,
            "group": serializer.instance.group_id,
            "restricted": serializer.instance.restricted,
            "is_active": serializer.instance.is_active,
            "priority": serializer.instance.priority,
        }
        obj = serializer.save()
        identity.audit(
            self.request.user,
            "category.updated",
            obj.pk,
            {
                "before": before,
                "after": {
                    "name": obj.name,
                    "group": obj.group_id,
                    "restricted": obj.restricted,
                    "is_active": obj.is_active,
                    "priority": obj.priority,
                },
            },
        )


class ReopenPolicyViewSet(
    NoStoreMixin, mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    serializer_class = ReopenPolicySerializer
    permission_classes = [IsIdentityAdmin]
    queryset = ReopenPolicy.objects.order_by("-id")

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        identity.identity_lock()
        locked_actor(request, admin=True)
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        obj = serializer.save(actor=self.request.user)
        identity.audit(
            self.request.user,
            "reopen_policy.created",
            obj.pk,
            {"hours": obj.hours, "reason": obj.reason},
        )
