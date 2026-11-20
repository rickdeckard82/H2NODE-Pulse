"""Wiki images and attachments: validated, scanned before storage, served from private disk."""

import hashlib
import re
import uuid
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from core import identity
from core.identity_views import NoStoreMixin
from tickets.attachments import scan
from wiki.models import WikiFile
from wiki.views import EDITORS, editor, pages

LIMIT = 5 * 1024 * 1024
OFFICE = "application/vnd.openxmlformats-officedocument."
# extension -> (media type, magic check). SVG and HTML are deliberately absent.
TYPES = {
    ".png": ("image/png", lambda d: d.startswith(b"\x89PNG\r\n\x1a\n")),
    ".jpg": ("image/jpeg", lambda d: d.startswith(b"\xff\xd8\xff")),
    ".jpeg": ("image/jpeg", lambda d: d.startswith(b"\xff\xd8\xff")),
    ".gif": ("image/gif", lambda d: d[:6] in {b"GIF87a", b"GIF89a"}),
    ".webp": ("image/webp", lambda d: d[:4] == b"RIFF" and d[8:12] == b"WEBP"),
    ".pdf": ("application/pdf", lambda d: d.startswith(b"%PDF-")),
    ".txt": ("text/plain", lambda d: _text(d)),
    ".docx": (OFFICE + "wordprocessingml.document", lambda d: d.startswith(b"PK\x03\x04")),
    ".xlsx": (OFFICE + "spreadsheetml.sheet", lambda d: d.startswith(b"PK\x03\x04")),
}


def _text(data):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    # Same rule as ticket attachments: no markup and no binary control characters.
    return "<" not in text and not any(ord(c) < 32 and c not in "\r\n\t" for c in text)


class ScannerUnavailable(APIException):
    status_code = 503
    default_detail = "Verificação antivírus indisponível. Tente novamente em instantes."


def path_for(key):
    return Path(settings.ATTACHMENT_ROOT) / "wiki" / str(uuid.UUID(str(key)))


class UploadInput(serializers.Serializer):
    file = serializers.FileField()


class FileSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    def get_url(self, obj) -> str:
        return f"/api/v1/wiki/files/{obj.pk}/"

    class Meta:
        model = WikiFile
        fields = ["id", "name", "media_type", "size", "url", "created_at"]
        read_only_fields = fields


class FileUploadView(NoStoreMixin, APIView):
    parser_classes = [MultiPartParser]

    @extend_schema(request=UploadInput, responses={201: FileSerializer})
    def post(self, request):
        # Short transaction only for the permission check: the scan below must not hold locks.
        with transaction.atomic():
            actor = editor(request)
        serializer = UploadInput(data=request.data.dict())
        serializer.is_valid(raise_exception=True)
        upload = serializer.validated_data["file"]
        if not 0 < upload.size <= LIMIT:
            raise ValidationError("Envie um arquivo de até 5 MiB.")
        data = upload.read(LIMIT + 1)
        suffix = Path(upload.name).suffix.lower()
        media, check = TYPES.get(suffix, (None, None))
        if not media or len(data) > LIMIT or upload.content_type != media or not check(data):
            raise ValidationError(
                "Tipo ou conteúdo inválido. Aceitos: PNG, JPG, GIF, WebP, PDF, TXT, DOCX e XLSX."
            )
        name = re.sub(r"[^\w .()-]", "_", Path(upload.name).name)[:110].strip(" .") or "arquivo"
        file = WikiFile(
            name=name,
            media_type=media,
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            uploaded_by=actor,
        )
        target = path_for(file.pk)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
        target.chmod(0o600)
        try:
            # Fail closed: nothing is kept or referenced unless the scanner confirms it clean.
            try:
                result = scan(target)
            except OSError:
                raise ScannerUnavailable() from None
            if result != "clean":
                raise ValidationError("Arquivo bloqueado pela verificação antivírus.")
            with transaction.atomic():
                file.save()
                identity.audit(
                    actor, "wiki.file_uploaded", file.pk, {"name": name, "size": file.size}
                )
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return Response(FileSerializer(file).data, status=201)


class FileView(NoStoreMixin, APIView):
    @extend_schema(responses={(200, "application/octet-stream"): bytes})
    def get(self, request, file_id):
        item = get_object_or_404(WikiFile, pk=file_id)
        # Readers get a file only through a page they can see; editors see every page anyway.
        if (
            request.user.role not in EDITORS
            and not pages(request.user)
            .filter(body__contains=f"/api/v1/wiki/files/{item.pk}/")
            .exists()
        ):
            raise Http404
        try:
            stream = path_for(item.pk).open("rb")
        except FileNotFoundError:
            raise ValidationError("Arquivo indisponível.") from None
        if hashlib.file_digest(stream, "sha256").hexdigest() != item.sha256:
            stream.close()
            raise ValidationError("Arquivo indisponível: integridade inválida.")
        stream.seek(0)
        inline = item.media_type.startswith("image/")
        response = FileResponse(
            stream,
            as_attachment=not inline,
            filename=item.name,
            content_type=item.media_type if inline else "application/octet-stream",
        )
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return response
