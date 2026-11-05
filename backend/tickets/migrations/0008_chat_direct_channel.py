from django.db import migrations, models

CHANNELS = [("email", "E-mail"), ("chat", "Google Chat"), ("chat_dm", "Google Chat individual")]


class Migration(migrations.Migration):
    dependencies = [
        ("tickets", "0007_category_priority"),
    ]

    operations = [
        migrations.AlterField(
            model_name="integrationcheck",
            name="channel",
            field=models.CharField(choices=CHANNELS, max_length=8),
        ),
        migrations.AlterField(
            model_name="notificationdelivery",
            name="channel",
            field=models.CharField(choices=CHANNELS, max_length=8),
        ),
    ]
