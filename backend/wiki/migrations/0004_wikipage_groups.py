import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0014_user_role_usuario"),
        ("wiki", "0003_alter_wikipage_id"),
    ]

    operations = [
        migrations.CreateModel(
            name="WikiPageGroup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                (
                    "group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="core.supportgroup"
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
            model_name="wikipagegroup",
            constraint=models.UniqueConstraint(fields=("page", "group"), name="wiki_page_group"),
        ),
        migrations.AddField(
            model_name="wikipage",
            name="groups",
            field=models.ManyToManyField(
                blank=True,
                related_name="wiki_pages",
                through="wiki.WikiPageGroup",
                to="core.supportgroup",
            ),
        ),
    ]
