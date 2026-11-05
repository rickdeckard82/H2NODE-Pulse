from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0009_simplify_roles"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="chat_space",
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name="chatconfiguration",
            name="project_number",
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name="chatconfiguration",
            name="encrypted_service_account",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="chatconfiguration",
            name="google_certs",
            field=models.JSONField(default=dict),
        ),
        migrations.AddField(
            model_name="chatconfiguration",
            name="certs_updated_at",
            field=models.DateTimeField(null=True),
        ),
    ]
