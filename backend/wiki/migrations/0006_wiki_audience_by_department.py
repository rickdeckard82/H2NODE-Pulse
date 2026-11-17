from django.db import migrations


def groups_to_departments(apps, schema_editor):
    """Keep restrictions: a group maps to the department with the same name, when one exists."""
    Department = apps.get_model("core", "Department")
    Link = apps.get_model("wiki", "WikiPageGroup")
    Target = apps.get_model("wiki", "WikiPageDepartment")
    by_name = {d.name.casefold(): d for d in Department.objects.all()}
    for link in Link.objects.select_related("group"):
        department = by_name.get(link.group.name.casefold())
        if department:
            Target.objects.get_or_create(page_id=link.page_id, department=department)


class Migration(migrations.Migration):
    dependencies = [("wiki", "0005_wikipage_departments")]

    operations = [
        migrations.RunPython(groups_to_departments, migrations.RunPython.noop),
        migrations.RemoveField(model_name="wikipage", name="groups"),
        migrations.DeleteModel(name="WikiPageGroup"),
    ]
