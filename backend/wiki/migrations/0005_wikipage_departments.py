import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0015_user_email_notifications"),
        ("wiki", "0004_wikipage_groups"),
    ]

    operations = [
        migrations.CreateModel(
            name="WikiPageDepartment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                (
                    "department",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="core.department"
                    ),
                ),
                (
                    "page",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="wiki.wikipage"
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="wikipagedepartment",
            constraint=models.UniqueConstraint(
                fields=("page", "department"), name="wiki_page_department"
            ),
        ),
        migrations.AddField(
            model_name="wikipage",
            name="departments",
            field=models.ManyToManyField(
                blank=True,
                related_name="wiki_pages",
                through="wiki.WikiPageDepartment",
                to="core.department",
            ),
        ),
    ]
