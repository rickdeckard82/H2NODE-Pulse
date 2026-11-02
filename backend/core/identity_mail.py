"""Small, expiring delivery queue dedicated to account challenges, not ticket notifications."""

from datetime import timedelta
from smtplib import SMTPException

from cryptography.fernet import InvalidToken
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from core.identity import cipher, domain_allowed
from core.models import AuthRateBucket, IdentityMail, IdentityToken, TrustedDevice
from core.smtp_settings import delivery_configuration


@transaction.atomic
def deliver_one():
    now = timezone.now()
    mail = (
        IdentityMail.objects.select_for_update(skip_locked=True)
        .filter(
            sent_at=None,
            next_attempt_at__lte=now,
        )
        .order_by("id")
        .first()
    )
    if not mail:
        return False
    token = mail.token
    user = token.user
    if (
        token.used_at
        or token.expires_at <= now
        or token.version != user.session_version
        or not user.is_active
        or not domain_allowed(token.email)
    ):
        mail.delete()
        return True
    raw = cipher().decrypt(mail.encrypted_body.encode()).decode()
    labels = {
        "verify": "Confirmação de cadastro",
        "reset": "Recuperação de senha",
        "invite": "Convite de acesso",
        "email": "Confirmação de novo e-mail",
    }
    try:
        config = delivery_configuration()
        if config is None:
            return False
        sender, connection = config
        delivered = send_mail(
            f"Pulse Services — {labels[token.purpose]}",
            (
                "Uma conta foi criada para você no Pulse Services. No portal, clique em "
                "Recuperar senha, informe este e-mail e use o código abaixo para definir "
                f"sua senha (válido por 72 horas):\n{raw}\n"
                if token.purpose == "invite"
                else f"Seu código de uso único (válido por 30 minutos):\n{raw}\n\n"
                "Use-o no portal Pulse Services. Se não fez esta solicitação, ignore a mensagem."
            ),
            sender,
            [token.email],
            fail_silently=False,
            connection=connection,
        )
        if delivered != 1:
            raise OSError("Mail not accepted")
    except SMTPException, OSError, ValidationError, InvalidToken:
        # Never log SMTP exceptions: providers can echo recipient/message content.
        mail.attempts += 1
        mail.next_attempt_at = now + timedelta(seconds=min(60 * 2 ** min(mail.attempts, 5), 900))
        mail.save(update_fields=["attempts", "next_attempt_at"])
    else:
        mail.sent_at, mail.encrypted_body = now, ""
        mail.save(update_fields=["sent_at", "encrypted_body"])
    return True


def cleanup():
    now = timezone.now()
    TrustedDevice.objects.filter(expires_at__lte=now).delete()
    IdentityToken.objects.filter(expires_at__lt=now).delete()
    AuthRateBucket.objects.filter(window__lt=int(now.timestamp()) // 900 - 1).delete()
