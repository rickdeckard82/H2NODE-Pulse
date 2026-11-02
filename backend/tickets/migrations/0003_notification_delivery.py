import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tickets", "0002_attachment_attachmentscan"),
    ]

    operations = [
        migrations.AddField(
            model_name="notificationoutbox",
            name="available_at",
            field=models.DateTimeField(db_index=True, default=django.utils.timezone.now),
        ),
        migrations.AddField(
            model_name="notificationoutbox",
            name="completed_at",
            field=models.DateTimeField(null=True),
        ),
        migrations.AddField(
            model_name="notificationoutbox",
            name="lease_token",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name="notificationoutbox",
            name="lease_until",
            field=models.DateTimeField(db_index=True, null=True),
        ),
        migrations.CreateModel(
            name="NotificationDelivery",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "channel",
                    models.CharField(
                        choices=[("email", "E-mail"), ("chat", "Google Chat")], max_length=8
                    ),
                ),
                ("recipient_key", models.CharField(max_length=320)),
                ("status", models.CharField(default="pending", max_length=16)),
                ("attempts", models.PositiveIntegerField(default=0)),
                (
                    "next_attempt_at",
                    models.DateTimeField(db_index=True, default=django.utils.timezone.now),
                ),
                ("last_attempt_at", models.DateTimeField(null=True)),
                ("sent_at", models.DateTimeField(null=True)),
                ("provider_id", models.CharField(blank=True, max_length=200)),
                ("last_error_code", models.CharField(blank=True, max_length=80)),
                (
                    "outbox",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="deliveries",
                        to="tickets.notificationoutbox",
                    ),
                ),
                (
                    "recipient",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="notificationdelivery",
            constraint=models.UniqueConstraint(
                fields=("outbox", "channel", "recipient_key"), name="notification_delivery_unique"
            ),
        ),
        migrations.AddIndex(
            model_name="notificationdelivery",
            index=models.Index(
                fields=["status", "next_attempt_at"], name="tickets_not_status_db98d6_idx"
            ),
        ),
        migrations.CreateModel(
            name="NotificationAttempt",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(default=django.utils.timezone.now, editable=False),
                ),
                ("outcome", models.CharField(max_length=16)),
                ("error_code", models.CharField(blank=True, max_length=80)),
                ("provider_id", models.CharField(blank=True, max_length=200)),
                (
                    "delivery",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="history",
                        to="tickets.notificationdelivery",
                    ),
                ),
            ],
        ),
    ]
