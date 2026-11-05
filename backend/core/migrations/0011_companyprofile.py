from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0010_chat_app"),
    ]

    operations = [
        migrations.CreateModel(
            name="CompanyProfile",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(
                        default=1, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("name", models.CharField(blank=True, max_length=120)),
                ("cnpj", models.CharField(blank=True, max_length=14)),
                ("responsible", models.CharField(blank=True, max_length=120)),
                ("logo", models.TextField(blank=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(condition=models.Q(("id", 1)), name="company_singleton")
                ],
            },
        ),
    ]
