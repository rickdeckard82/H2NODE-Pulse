from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0013_deactivated_at")]

    operations = [
        # Choices and default only: existing accounts keep the role they already have.
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[
                    ("user", "Usuário"),
                    ("collaborator", "Colaborador"),
                    ("technician", "Técnico"),
                    ("manager", "Gestor"),
                    ("admin", "Administrador"),
                ],
                default="user",
                max_length=20,
            ),
        ),
    ]
