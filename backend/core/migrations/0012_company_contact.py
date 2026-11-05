from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0011_companyprofile"),
    ]

    operations = [
        migrations.AddField(
            model_name="companyprofile",
            name="responsible_email",
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="website",
            field=models.URLField(blank=True),
        ),
    ]
