"""Executed through Django shell only against the isolated E2E database."""

import json
from pathlib import Path

from core.identity import cipher
from core.models import AllowedDomain, Department, Membership, SupportGroup, User
from django.conf import settings
from django.utils import timezone
from tickets.models import Category

assert settings.ENVIRONMENT == "test"
assert settings.DATABASES["default"]["NAME"] == "e2e_pulse"
config = json.loads(Path("/tmp/e2e-fixture.json").read_text())
AllowedDomain.objects.get_or_create(domain="company.test")
department, _ = Department.objects.get_or_create(name="Operações sintéticas")
group, _ = SupportGroup.objects.get_or_create(name="Suporte sintético")
Category.objects.get_or_create(name="Acessos e sistemas", defaults={"group": group})
for name, role in [
    ("owner", "collaborator"),
    ("peer", "collaborator"),
    ("tech", "technician"),
    ("admin", "admin"),
    ("enroll", "technician"),
]:
    user = User.objects.create_user(
        username=name,
        email=f"{name}@company.test",
        first_name={
            "enroll": "Cadastro MFA",
            "owner": "Ana",
            "peer": "Beatriz",
            "tech": "Lucas",
            "admin": "Administração",
        }[name],
        password=config["password"],
        role=role,
        department=department,
        email_verified_at=timezone.now(),
    )
    if role != "collaborator" and name != "enroll":
        user.mfa_enabled = True
        user.mfa_secret = cipher().encrypt(config["mfa"][name].encode()).decode()
        user.save()
    if role == "technician":
        Membership.objects.create(user=user, group=group, can_transfer=True)
print("Synthetic E2E identities created; no credentials printed.")
