import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0006_style_recipe_and_languages"),
        ("brands", "0010_domain_layer"),
    ]

    operations = [
        migrations.AddField(
            model_name="campaign",
            name="content",
            field=models.ForeignKey(
                blank=True,
                help_text="Optional exported Studio project to distribute. References VideoProject; does not copy files.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="campaigns",
                to="ai.videoproject",
            ),
        ),
    ]
