from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from core import identity
from core.identity_views import NoStoreMixin, locked_actor
from core.models import Membership, SupportGroup, User
from core.serializers import StrictSerializer
from wiki.models import WikiPage, WikiPageGroup

EDITORS = {User.Role.MANAGER, User.Role.ADMIN}


class PageInput(StrictSerializer):
    title = serializers.CharField(max_length=200)
    body = serializers.CharField(max_length=50000)
    tags = serializers.ListField(
        child=serializers.CharField(max_length=30), max_length=5, required=False
    )
    groups = serializers.ListField(
        child=serializers.PrimaryKeyRelatedField(
            queryset=SupportGroup.objects.filter(is_active=True)
        ),
        max_length=50,
        required=False,
    )

    def validate_tags(self, value):
        seen, tags = set(), []
        for tag in value:
            tag = " ".join(tag.replace(",", " ").split())
            if tag and tag.casefold() not in seen:
                seen.add(tag.casefold())
                tags.append(tag)
        return tags


class PageSummary(serializers.ModelSerializer):
    id = serializers.UUIDField(source="uuid", read_only=True)
    groups = serializers.SerializerMethodField()

    def get_groups(self, obj) -> list[dict]:
        return [{"id": g.pk, "name": g.name} for g in obj.groups.all()]

    author_name = serializers.CharField(source="author.first_name", read_only=True)

    class Meta:
        model = WikiPage
        fields = ["id", "title", "tags", "groups", "author_name", "created_at", "updated_at"]
        read_only_fields = fields


class PageDetail(PageSummary):
    updated_by_name = serializers.CharField(
        source="updated_by.first_name", read_only=True, default=""
    )

    class Meta(PageSummary.Meta):
        fields = [*PageSummary.Meta.fields, "body", "updated_by_name"]
        read_only_fields = fields


def pages(user):
    """Pages this user may see: unrestricted ones, or those of a group they belong to.

    Managers and administrators (the editors) see everything.
    """
    query = WikiPage.objects.select_related("author", "updated_by").prefetch_related("groups")
    if user.role in EDITORS:
        return query
    mine = Membership.objects.filter(user=user, group__is_active=True).values("group")
    return query.filter(Q(groups__isnull=True) | Q(wikipagegroup__group__in=mine)).distinct()


def set_groups(page, data):
    if "groups" in data:
        groups = data.pop("groups")
        page.groups.clear()
        WikiPageGroup.objects.bulk_create(
            WikiPageGroup(page=page, group=g) for g in dict.fromkeys(groups)
        )
    return data


class GroupOption(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class GroupListView(NoStoreMixin, APIView):
    @extend_schema(responses=GroupOption(many=True))
    def get(self, request):
        if request.user.role not in EDITORS:
            raise PermissionDenied("Somente gestores e administradores editam a wiki.")
        rows = SupportGroup.objects.filter(is_active=True).order_by("name")
        return Response([{"id": g.pk, "name": g.name} for g in rows])


class PageListView(NoStoreMixin, APIView):
    """Every signed-in user reads; only managers and administrators write."""

    @extend_schema(responses=PageSummary(many=True))
    def get(self, request):
        return Response(PageSummary(pages(request.user)[:500], many=True).data)

    @extend_schema(request=PageInput, responses={201: PageDetail})
    @transaction.atomic
    def post(self, request):
        actor = editor(request)
        data = validated(request)
        groups = data.pop("groups", [])
        page = WikiPage.objects.create(author=actor, **data)
        set_groups(page, {"groups": groups})
        identity.audit(
            actor,
            "wiki.created",
            page.uuid,
            {"title": page.title, "groups": [g.pk for g in groups]},
        )
        return Response(PageDetail(page).data, status=201)


class PageView(NoStoreMixin, APIView):
    @extend_schema(responses=PageDetail)
    def get(self, request, page_id):
        return Response(PageDetail(get_object_or_404(pages(request.user), uuid=page_id)).data)

    @extend_schema(request=PageInput, responses=PageDetail)
    @transaction.atomic
    def patch(self, request, page_id):
        actor = editor(request)
        page = get_object_or_404(pages(actor).select_for_update(of=("self",)), uuid=page_id)
        data = validated(request)
        changed = "groups" in data
        set_groups(page, data)
        for field, value in data.items():
            setattr(page, field, value)
        page.updated_by, page.updated_at = actor, timezone.now()
        page.save()
        details = {"title": page.title}
        if changed:
            details["groups"] = [g.pk for g in page.groups.all()]
        identity.audit(actor, "wiki.updated", page.uuid, details)
        return Response(PageDetail(page).data)

    @extend_schema(responses={204: None})
    @transaction.atomic
    def delete(self, request, page_id):
        actor = editor(request)
        page = get_object_or_404(pages(actor).select_for_update(of=("self",)), uuid=page_id)
        identity.audit(actor, "wiki.deleted", page.uuid, {"title": page.title})
        page.delete()
        return Response(status=204)


def editor(request):
    if request.user.role not in EDITORS:
        raise PermissionDenied("Somente gestores e administradores editam a wiki.")
    identity.identity_lock()
    actor = locked_actor(request)
    if actor.role not in EDITORS:
        raise PermissionDenied("Somente gestores e administradores editam a wiki.")
    return actor


def validated(request):
    serializer = PageInput(data=request.data, partial=request.method == "PATCH")
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data
