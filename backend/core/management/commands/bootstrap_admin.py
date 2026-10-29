import getpass
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.identity import audit, identity_lock, issue_token, normalize_email, password_hash
from core.models import AllowedDomain, User
from core.serializers import DomainSerializer, EmailInput


class Command(BaseCommand):
    help = "Cria o primeiro administrador; requer confirmação do e-mail e MFA antes do acesso."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--domain", required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        identity_lock()
        if User.objects.filter(role=User.Role.ADMIN).exists():
            raise CommandError("Já existe administrador. Use a administração autenticada.")
        email = normalize_email(options["email"])
        email_input = EmailInput(data={"email": email})
        existing = AllowedDomain.objects.filter(domain=options["domain"].strip().lower()).first()
        domain_input = DomainSerializer(
            instance=existing, data={"domain": options["domain"], "reason": "Bootstrap operacional"}
        )
        if not email_input.is_valid() or not domain_input.is_valid():
            raise CommandError("E-mail/domínio inválido.")
        if existing and not existing.is_active:
            raise CommandError("Domínio desativado; revise a configuração operacional.")
        domain = domain_input.validated_data["domain"]
        if email.rsplit("@", 1)[-1] != domain or User.objects.filter(email=email).exists():
            raise CommandError("E-mail não pertence ao domínio ou já está cadastrado.")
        password = getpass.getpass("Senha inicial (não será exibida): ")
        if password != getpass.getpass("Repita a senha: "):
            raise CommandError("Senhas diferentes.")
        user = User(username=uuid.uuid4().hex, email=email, role=User.Role.ADMIN)
        user.password = password_hash(password, user)
        AllowedDomain.objects.get_or_create(domain=domain, defaults={"is_active": True})
        user.save()
        issue_token(user, "verify")
        audit(None, "bootstrap.admin_created", user.pk, {"actor": "operator"})
        self.stdout.write(
            "Administrador criado. Confirme o e-mail e configure MFA no primeiro login."
        )
