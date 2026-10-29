"""Small, expiring delivery queue dedicated to account challenges, not ticket notifications."""

from datetime import timedelta
from smtplib import SMTPException

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from core.identity import cipher, domain_allowed
from core.models import AuthRateBucket, IdentityMail, IdentityToken


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
    if not settings.EMAIL_HOST or not settings.DEFAULT_FROM_EMAIL:
        return False
    raw = cipher().decrypt(mail.encrypted_body.encode()).decode()
    labels = {
        "verify": "Confirmação de cadastro",
        "reset": "Recuperação de senha",
        "email": "Confirmação de novo e-mail",
    }
    try:
        delivered = send_mail(
            f"Pulse Services — {labels[token.purpose]}",
            f"Seu código de uso único (válido por 30 minutos):\n{raw}\n\n"
            "Use-o no portal Pulse Services. Se não fez esta solicitação, ignore a mensagem.",
            settings.DEFAULT_FROM_EMAIL,
            [token.email],
            fail_silently=False,
        )
        if delivered != 1:
            raise OSError("Mail not accepted")
    except SMTPException, OSError:
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
    IdentityToken.objects.filter(expires_at__lt=now).delete()
    AuthRateBucket.objects.filter(window__lt=int(now.timestamp()) // 900 - 1).delete()
