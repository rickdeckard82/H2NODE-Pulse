from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0014_user_role_usuario")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="email_notifications",
            field=models.BooleanField(default=True),
        ),
    ]
