from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tickets", "0006_ticket_number_participants"),
    ]

    operations = [
        migrations.AddField(
            model_name="category",
            name="priority",
            field=models.PositiveSmallIntegerField(default=3),
        ),
        migrations.AddConstraint(
            model_name="category",
            constraint=models.CheckConstraint(
                condition=models.Q(("priority__range", (1, 4))), name="category_valid_priority"
            ),
        ),
        migrations.AlterField(
            model_name="ticket",
            name="impact",
            field=models.PositiveSmallIntegerField(null=True),
        ),
        migrations.AlterField(
            model_name="ticket",
            name="urgency",
            field=models.PositiveSmallIntegerField(null=True),
        ),
    ]
