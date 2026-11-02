from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0005_trusteddevice")]

    operations = [
        migrations.CreateModel(
            name="ChatConfiguration",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(
                        default=1, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("enabled", models.BooleanField(default=False)),
                ("encrypted_webhook", models.TextField(blank=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(condition=models.Q(("id", 1)), name="chat_singleton")
                ]
            },
        )
    ]
