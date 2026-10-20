from django.db import migrations


def copy_company_data(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    Brand = apps.get_model("brands", "Brand")
    for user in User.objects.filter(role="producer"):
        if Brand.objects.filter(owner=user).exists():
            continue
        name = getattr(user, "company_name", "") or user.name
        Brand.objects.create(
            owner=user,
            name=name,
            website=getattr(user, "company_website", "") or "",
            description=getattr(user, "company_description", "") or "",
            location=user.location,
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("brands", "0001_initial"),
        ("accounts", "0002_user_company_description_user_company_name_and_more"),
    ]

    operations = [
        migrations.RunPython(copy_company_data, noop),
    ]
