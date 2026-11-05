from django.db import migrations, models
from django.db.models import F


def demote_privacy(apps, schema_editor):
    # Least privilege; the bumped session version ends any session using the retired role.
    apps.get_model("core", "User").objects.filter(role="privacy").update(
        role="collaborator", session_version=F("session_version") + 1
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0008_user_notifications"),
    ]

    operations = [
        migrations.RunPython(demote_privacy, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[
                    ("collaborator", "Colaborador"),
                    ("technician", "Técnico"),
                    ("manager", "Gestor"),
                    ("admin", "Administrador"),
                ],
                default="collaborator",
                max_length=20,
            ),
        ),
    ]
