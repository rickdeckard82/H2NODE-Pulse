from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0013_deactivated_at"),
        ("tickets", "0008_chat_direct_channel"),
    ]

    operations = [
        migrations.AddField(
            model_name="category",
            name="deactivated_at",
            field=models.DateTimeField(editable=False, null=True),
        ),
        migrations.RunSQL(
            "UPDATE tickets_category SET deactivated_at = now() WHERE NOT is_active;",
            migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            "CREATE TRIGGER tickets_category_deactivation BEFORE UPDATE ON tickets_category "
            "FOR EACH ROW EXECUTE FUNCTION pulse_track_deactivation();",
            "DROP TRIGGER tickets_category_deactivation ON tickets_category;",
        ),
        migrations.CreateModel(
            name="RetentionPolicy",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(
                        default=1, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("enabled", models.BooleanField(default=False)),
                ("tickets_days", models.PositiveIntegerField(default=0)),
                ("users_days", models.PositiveIntegerField(default=0)),
                ("groups_days", models.PositiveIntegerField(default=0)),
                ("categories_days", models.PositiveIntegerField(default=0)),
                ("departments_days", models.PositiveIntegerField(default=0)),
                ("logs_days", models.PositiveIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("last_run_at", models.DateTimeField(null=True)),
                ("last_result", models.JSONField(default=dict)),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("id", 1)), name="retention_singleton"
                    )
                ],
            },
        ),
    ]
