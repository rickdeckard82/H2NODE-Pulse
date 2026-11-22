"""Import wiki pages from a JSON export, attributing them to an existing manager/admin."""

import json
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core import identity
from core.models import User
from wiki.models import WikiPage
from wiki.views import EDITORS, PageInput


class Command(BaseCommand):
    help = "Importa páginas da wiki de um JSON. Idempotente por título."

    def add_arguments(self, parser):
        parser.add_argument("--author", required=True, help="E-mail de um gestor ou administrador.")
        parser.add_argument("--file", required=True, help="JSON exportado da wiki.")
        parser.add_argument("--dry-run", action="store_true")

    @transaction.atomic
    def handle(self, *args, author, file, dry_run, **options):
        actor = User.objects.filter(email__iexact=author, is_active=True).first()
        if not actor or actor.role not in EDITORS or not identity.eligible(actor):
            raise CommandError("O autor deve ser um gestor ou administrador ativo.")
        try:
            items = json.loads(Path(file).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CommandError(f"Arquivo inválido: {exc}") from exc
        created = skipped = 0
        for item in items:
            serializer = PageInput(
                data={k: item.get(k) for k in ("title", "body", "tags") if k in item}
            )
            if not serializer.is_valid():
                raise CommandError(f"Página inválida {item.get('title')!r}: {serializer.errors}")
            data = serializer.validated_data
            if WikiPage.objects.filter(title=data["title"]).exists():
                skipped += 1
                continue
            when = (
                datetime.fromisoformat(item["created_at"])
                if item.get("created_at")
                else timezone.now()
            )
            if not dry_run:
                page = WikiPage.objects.create(
                    author=actor, created_at=when, updated_at=when, **data
                )
                identity.audit(actor, "wiki.imported", page.uuid, {"title": page.title})
            created += 1
        if dry_run:
            transaction.set_rollback(True)
        self.stdout.write(
            f"{'Simulação: ' if dry_run else ''}{created} criada(s), {skipped} já existente(s)."
        )
