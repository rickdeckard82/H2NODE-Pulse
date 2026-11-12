from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from core import identity
from core.identity_views import NoStoreMixin, locked_actor
from core.models import User
from core.serializers import StrictSerializer
from wiki.models import WikiPage

EDITORS = {User.Role.MANAGER, User.Role.ADMIN}


class PageInput(StrictSerializer):
    title = serializers.CharField(max_length=200)
    body = serializers.CharField(max_length=50000)
    tags = serializers.ListField(
        child=serializers.CharField(max_length=30), max_length=5, required=False
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
    author_name = serializers.CharField(source="author.first_name", read_only=True)

    class Meta:
        model = WikiPage
        fields = ["id", "title", "tags", "author_name", "created_at", "updated_at"]
        read_only_fields = fields


class PageDetail(PageSummary):
    updated_by_name = serializers.CharField(
        source="updated_by.first_name", read_only=True, default=""
    )

    class Meta(PageSummary.Meta):
        fields = [*PageSummary.Meta.fields, "body", "updated_by_name"]
        read_only_fields = fields


def pages():
    return WikiPage.objects.select_related("author", "updated_by")


class PageListView(NoStoreMixin, APIView):
    """Every signed-in user reads; only managers and administrators write."""

    @extend_schema(responses=PageSummary(many=True))
    def get(self, request):
        return Response(PageSummary(pages()[:500], many=True).data)

    @extend_schema(request=PageInput, responses={201: PageDetail})
    @transaction.atomic
    def post(self, request):
        actor = editor(request)
        data = validated(request)
        page = WikiPage.objects.create(author=actor, **data)
        identity.audit(actor, "wiki.created", page.uuid, {"title": page.title})
        return Response(PageDetail(page).data, status=201)


class PageView(NoStoreMixin, APIView):
    @extend_schema(responses=PageDetail)
    def get(self, request, page_id):
        return Response(PageDetail(get_object_or_404(pages(), uuid=page_id)).data)

    @extend_schema(request=PageInput, responses=PageDetail)
    @transaction.atomic
    def patch(self, request, page_id):
        actor = editor(request)
        page = get_object_or_404(pages().select_for_update(of=("self",)), uuid=page_id)
        for field, value in validated(request).items():
            setattr(page, field, value)
        page.updated_by, page.updated_at = actor, timezone.now()
        page.save()
        identity.audit(actor, "wiki.updated", page.uuid, {"title": page.title})
        return Response(PageDetail(page).data)

    @extend_schema(responses={204: None})
    @transaction.atomic
    def delete(self, request, page_id):
        actor = editor(request)
        page = get_object_or_404(pages().select_for_update(of=("self",)), uuid=page_id)
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
