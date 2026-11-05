from django.db import migrations, models

FUNCTION = """
CREATE FUNCTION pulse_track_deactivation() RETURNS trigger AS $$
BEGIN
    -- Derived from is_active on every update, so no code path can forge or forget the date.
    IF OLD.is_active AND NOT NEW.is_active THEN
        NEW.deactivated_at := now();
    ELSIF NEW.is_active THEN
        NEW.deactivated_at := NULL;
    ELSE
        NEW.deactivated_at := OLD.deactivated_at;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""
TABLES = ["core_user", "core_department", "core_supportgroup"]


def trigger(table):
    return (
        f"CREATE TRIGGER {table}_deactivation BEFORE UPDATE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION pulse_track_deactivation();"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0012_company_contact"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="deactivated_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="department",
            name="deactivated_at",
            field=models.DateTimeField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name="supportgroup",
            name="deactivated_at",
            field=models.DateTimeField(editable=False, null=True),
        ),
        # The real date is unknown, so the period of records already inactive starts now.
        migrations.RunSQL(
            "UPDATE core_user SET deactivated_at = now() "
            "WHERE NOT is_active AND username NOT LIKE 'system:%%';"
            "UPDATE core_department SET deactivated_at = now() WHERE NOT is_active;"
            "UPDATE core_supportgroup SET deactivated_at = now() WHERE NOT is_active;",
            migrations.RunSQL.noop,
        ),
        migrations.RunSQL(FUNCTION, "DROP FUNCTION pulse_track_deactivation();"),
        *[
            migrations.RunSQL(trigger(table), f"DROP TRIGGER {table}_deactivation ON {table};")
            for table in TABLES
        ],
    ]
