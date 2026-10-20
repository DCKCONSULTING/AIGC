from django.db import migrations


def create_profiles(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    AgentProfile = apps.get_model("agents", "AgentProfile")
    for user in User.objects.filter(role="agent"):
        AgentProfile.objects.get_or_create(user=user)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("agents", "0001_initial"),
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_profiles, noop),
    ]
