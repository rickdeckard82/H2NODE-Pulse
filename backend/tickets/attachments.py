"""Private storage and fail-closed ClamD INSTREAM scanning."""

import hashlib
import re
import socket
import struct
import uuid
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, serializers
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from core.identity_views import NoStoreMixin
from tickets import services
from tickets.models import Attachment, AttachmentScan
from tickets.permissions import can_read_internal, visible_tickets
from tickets.serializers import CommentInput, MutationResult

LIMIT = 5 * 1024 * 1024
TYPES = {
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


def path_for(key):
    return Path(settings.ATTACHMENT_ROOT) / str(uuid.UUID(str(key)))


def validate_file(upload):
    if not upload or not 0 < upload.size <= LIMIT:
        raise ValidationError("Envie um arquivo de até 5 MiB.")
    suffix = Path(upload.name).suffix.lower()
    media = TYPES.get(suffix)
    data = upload.read(LIMIT + 1)
    valid = False
    if suffix == ".txt":
        try:
            decoded = data.decode("utf-8")
            valid = (
                not any(ord(c) < 32 and c not in "\r\n\t" for c in decoded) and "<" not in decoded
            )
        except UnicodeDecodeError:
            pass
    elif suffix == ".pdf":
        valid = data.startswith(b"%PDF-") and b"%%EOF" in data[-1024:]
    elif suffix == ".png":
        valid = data.startswith(b"\x89PNG\r\n\x1a\n") and data[-8:] == b"IEND\xaeB`\x82"
    elif suffix in {".jpg", ".jpeg"}:
        valid = data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9")
    if not valid or upload.content_type != media or len(data) > LIMIT:
        raise ValidationError(
            "Tipo, extensão ou conteúdo inválido. Aceitos: TXT UTF-8, PDF, PNG e JPEG."
        )
    # Never use client names as paths or header values without normalization.
    name = re.sub(r"[^\w .()-]", "_", Path(upload.name).name)[:110].strip(" .") or "arquivo"
    return data, media, name


class AttachmentInput(CommentInput):
    file = serializers.FileField()


class AttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attachment
        fields = [
            "id",
            "comment",
            "name",
            "media_type",
            "size",
            "status",
            "created_at",
            "scanned_at",
        ]
        read_only_fields = fields


def visible_attachments(user, ticket):
    query = Attachment.objects.filter(comment__ticket=ticket).order_by("created_at", "id")
    if not can_read_internal(user, ticket):
        query = query.filter(comment__visibility="public")
    return query


class AttachmentView(NoStoreMixin, generics.GenericAPIView):
    parser_classes = [MultiPartParser]
    serializer_class = AttachmentSerializer

    @extend_schema(responses=AttachmentSerializer(many=True))
    def get(self, request, ticket_id):
        from rest_framework.pagination import PageNumberPagination

        ticket = get_object_or_404(visible_tickets(request.user), uuid=ticket_id)
        pager = PageNumberPagination()
        rows = pager.paginate_queryset(visible_attachments(request.user, ticket), request)
        return pager.get_paginated_response(AttachmentSerializer(rows, many=True).data)

    @extend_schema(
        request=AttachmentInput,
        responses={201: MutationResult},
        parameters=[
            OpenApiParameter(
                "Idempotency-Key", OpenApiTypes.UUID, OpenApiParameter.HEADER, required=True
            )
        ],
    )
    def post(self, request, ticket_id):
        get_object_or_404(visible_tickets(request.user), uuid=ticket_id)
        serializer = AttachmentInput(data=request.data.dict())
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        raw, media, name = validate_file(payload.pop("file"))
        payload.update(
            sha256=hashlib.sha256(raw).hexdigest(), name=name, media_type=media, size=len(raw)
        )
        key = uuid.uuid4()
        target = path_for(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(raw)
        target.chmod(0o600)
        keep = False
        try:

            def mutation(actor, ticket, data):
                event = services.add_comment(actor, ticket, data)
                Attachment.objects.create(
                    comment=event.comment,
                    storage_key=key,
                    name=name,
                    media_type=media,
                    size=len(raw),
                    sha256=payload["sha256"],
                )
                return event

            body, status, replay = services.execute(
                request, "attachment", payload, mutation, ticket_id, 201
            )
            keep = not replay
            return Response(
                body, status=status, headers={"Idempotent-Replayed": str(replay).lower()}
            )
        finally:
            if not keep:
                target.unlink(missing_ok=True)


class DownloadView(NoStoreMixin, APIView):
    @extend_schema(responses={(200, "application/octet-stream"): bytes})
    def get(self, request, ticket_id, attachment_id):
        ticket = get_object_or_404(visible_tickets(request.user), uuid=ticket_id)
        item = get_object_or_404(visible_attachments(request.user, ticket), pk=attachment_id)
        if item.status != "clean":
            raise services.Conflict("Arquivo indisponível: aguardando verificação ou bloqueado.")
        try:
            stream = path_for(item.storage_key).open("rb")
        except FileNotFoundError:
            raise services.Conflict("Arquivo indisponível.") from None
        if hashlib.file_digest(stream, "sha256").hexdigest() != item.sha256:
            stream.close()
            raise services.Conflict("Arquivo indisponível: integridade inválida.")
        stream.seek(0)
        response = FileResponse(
            stream, as_attachment=True, filename=item.name, content_type="application/octet-stream"
        )
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return response


def scan(path):
    with socket.create_connection(
        (settings.CLAMAV_HOST, settings.CLAMAV_PORT), timeout=5
    ) as client:
        client.settimeout(5)
        client.sendall(b"zINSTREAM\0")
        with path.open("rb") as stream:
            while chunk := stream.read(65536):
                client.sendall(struct.pack("!I", len(chunk)) + chunk)
        client.sendall(b"\0\0\0\0")
        response = b""
        while b"\0" not in response and len(response) < 4096:
            chunk = client.recv(4096)
            if not chunk:
                break
            response += chunk
        if response == b"stream: OK\0":
            return "clean"
        if response.startswith(b"stream: ") and response.endswith(b" FOUND\0"):
            return "blocked"
        raise OSError("Scanner did not confirm a result")


@transaction.atomic
def scan_one():
    item = (
        Attachment.objects.select_for_update(skip_locked=True)
        .filter(status="quarantine", next_attempt__lte=timezone.now())
        .order_by("created_at")
        .first()
    )
    if item is None:
        return False
    try:
        path = path_for(item.storage_key)
        with path.open("rb") as stream:
            intact = hashlib.file_digest(stream, "sha256").hexdigest() == item.sha256
        item.status = scan(path) if intact else "blocked"
        item.scanned_at = timezone.now()
        result = item.status
    except OSError:
        result = "unavailable"
    item.attempts += 1
    item.next_attempt = timezone.now() + timedelta(
        seconds=min(3600, 30 * 2 ** min(item.attempts, 7))
    )
    item.save()
    AttachmentScan.objects.create(attachment=item, result=result)
    return True
