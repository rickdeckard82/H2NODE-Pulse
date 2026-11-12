from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("tickets", "0009_retention")]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="client_ip",
            field=models.GenericIPAddressField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="ticket",
            name="client_os",
            field=models.CharField(blank=True, max_length=120),
        ),
    ]
