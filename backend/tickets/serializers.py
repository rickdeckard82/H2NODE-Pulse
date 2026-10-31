from rest_framework import serializers

from core.models import SupportGroup, User
from core.serializers import StrictSerializer
from tickets.models import Category, Comment, ReadGrant, ReopenPolicy, Ticket, TicketEvent


class CreateInput(StrictSerializer):
    category = serializers.IntegerField(min_value=1)
    subject = serializers.CharField(max_length=200)
    description = serializers.CharField(max_length=10000)
    impact = serializers.IntegerField(min_value=1, max_value=3)
    urgency = serializers.IntegerField(min_value=1, max_value=3)
    related_ticket = serializers.UUIDField(required=False)


class VersionInput(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)


class CommentInput(VersionInput):
    body = serializers.CharField(max_length=8000)
    visibility = serializers.ChoiceField(choices=Comment.Visibility.choices)
    corrects = serializers.UUIDField(required=False)


class TransitionInput(VersionInput):
    action = serializers.ChoiceField(
        choices=[
            "request_information",
            "request_test",
            "resolve",
            "confirm",
            "reopen",
            "cancel",
            "return_queue",
        ]
    )
    message = serializers.CharField(max_length=8000, required=False)
    resolution_class = serializers.CharField(max_length=80, required=False)
    assignee = serializers.IntegerField(min_value=1, required=False)


class TransferInput(VersionInput):
    group = serializers.IntegerField(min_value=1)
    assignee = serializers.IntegerField(min_value=1)
    message = serializers.CharField(max_length=8000)


class MutationResult(serializers.Serializer):
    ticket_id = serializers.UUIDField()
    number = serializers.IntegerField()
    event_id = serializers.UUIDField()
    version = serializers.IntegerField()
    state = serializers.ChoiceField(choices=Ticket.State)
    correlation_id = serializers.UUIDField()


class TicketSerializer(serializers.ModelSerializer):
    can_transfer = serializers.SerializerMethodField()
    can_cancel = serializers.SerializerMethodField()

    def get_can_transfer(self, obj) -> bool:
        from tickets.permissions import membership

        member = membership(self.context["request"].user, obj)
        return bool(member and member.can_transfer)

    def get_can_cancel(self, obj) -> bool:
        from tickets.permissions import membership

        actor = self.context["request"].user
        member = membership(actor, obj)
        return bool(member and actor.role == User.Role.MANAGER and member.can_cancel)

    id = serializers.UUIDField(source="uuid", read_only=True)
    requester_name = serializers.CharField(source="requester.first_name", read_only=True)
    assignee_name = serializers.CharField(
        source="assignee.first_name", read_only=True, allow_null=True
    )
    related_ticket = serializers.UUIDField(
        source="related_ticket.uuid", read_only=True, allow_null=True
    )

    class Meta:
        model = Ticket
        fields = [
            "id",
            "number",
            "requester",
            "requester_name",
            "department",
            "department_name",
            "category",
            "subject",
            "description",
            "impact",
            "urgency",
            "priority",
            "group",
            "assignee",
            "assignee_name",
            "state",
            "restricted",
            "version",
            "created_at",
            "updated_at",
            "resolved_at",
            "closed_at",
            "resolution_class",
            "reopen_policy",
            "related_ticket",
            "can_transfer",
            "can_cancel",
        ]
        read_only_fields = fields


class CommentSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.first_name", read_only=True)

    class Meta:
        model = Comment
        fields = ["id", "actor", "actor_name", "created_at", "body", "visibility", "corrects"]
        read_only_fields = fields


class EventSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.first_name", read_only=True)
    comment = CommentSerializer(read_only=True, allow_null=True)

    class Meta:
        model = TicketEvent
        fields = [
            "id",
            "actor",
            "actor_name",
            "created_at",
            "correlation_id",
            "action",
            "visibility",
            "version",
            "from_state",
            "to_state",
            "comment",
            "changes",
        ]
        read_only_fields = fields


class QueueFilters(StrictSerializer):
    page = serializers.IntegerField(min_value=1, required=False)
    state = serializers.ChoiceField(choices=Ticket.State, required=False)
    priority = serializers.IntegerField(min_value=1, max_value=4, required=False)
    department = serializers.IntegerField(min_value=1, required=False)
    group = serializers.IntegerField(min_value=1, required=False)
    assignee = serializers.IntegerField(min_value=1, required=False)
    number = serializers.IntegerField(min_value=1, required=False)
    search = serializers.CharField(max_length=200, required=False)
    ordering = serializers.ChoiceField(
        choices=["-created_at", "created_at", "priority", "-priority"], required=False
    )


class StrictModelSerializer(serializers.ModelSerializer):
    def to_internal_value(self, data):
        allowed = {name for name, field in self.fields.items() if not field.read_only}
        if not isinstance(data, dict) or set(data) - allowed:
            raise serializers.ValidationError({"non_field_errors": ["Campos não permitidos."]})
        return super().to_internal_value(data)


class CategorySerializer(StrictModelSerializer):
    group = serializers.PrimaryKeyRelatedField(queryset=SupportGroup.objects.filter(is_active=True))

    class Meta:
        model = Category
        fields = ["id", "name", "group", "restricted", "is_active"]
        read_only_fields = ["id"]


class ReadGrantSerializer(StrictModelSerializer):
    user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(
            role__in=[User.Role.ADMIN, User.Role.PRIVACY],
            is_active=True,
            email_verified_at__isnull=False,
        )
    )
    group = serializers.PrimaryKeyRelatedField(queryset=SupportGroup.objects.filter(is_active=True))

    class Meta:
        model = ReadGrant
        fields = ["id", "user", "group", "internal", "restricted"]
        read_only_fields = ["id"]


class ReopenPolicySerializer(StrictModelSerializer):
    hours = serializers.IntegerField(min_value=0, max_value=8760)

    class Meta:
        model = ReopenPolicy
        fields = ["id", "hours", "actor", "created_at", "reason"]
        read_only_fields = ["id", "actor", "created_at"]


class TransferOptionSerializer(serializers.Serializer):
    group = serializers.IntegerField()
    group_name = serializers.CharField()
    user = serializers.IntegerField()
    user_name = serializers.CharField()
