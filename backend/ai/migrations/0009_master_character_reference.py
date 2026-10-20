import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0008_scene_generation_failure"),
    ]

    operations = [
        migrations.CreateModel(
            name="CharacterMasterReference",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("version", models.PositiveIntegerField()),
                ("image", models.ImageField(upload_to="ai/characters/master/%Y/%m/")),
                ("source_image", models.ImageField(blank=True, upload_to="ai/characters/source/%Y/%m/")),
                ("prompt", models.TextField(blank=True)),
                ("identity_facts", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                (
                    "character",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="master_versions",
                        to="ai.character",
                    ),
                ),
            ],
            options={
                "ordering": ["-version", "-id"],
            },
        ),
        migrations.AddField(
            model_name="character",
            name="source_front_image",
            field=models.ImageField(blank=True, upload_to="ai/characters/source/%Y/%m/"),
        ),
        migrations.AddField(
            model_name="character",
            name="master_reference_image",
            field=models.ImageField(blank=True, upload_to="ai/characters/master/%Y/%m/"),
        ),
        migrations.AddField(
            model_name="character",
            name="master_reference_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("processing", "Processing"),
                    ("ready", "Ready"),
                    ("failed", "Failed"),
                ],
                default="pending",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="character",
            name="master_reference_version",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="character",
            name="master_reference_prompt",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="character",
            name="master_reference_created_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="character",
            name="current_master",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="ai.charactermasterreference",
            ),
        ),
        migrations.AddConstraint(
            model_name="charactermasterreference",
            constraint=models.UniqueConstraint(fields=("character", "version"), name="character_master_version_uniq"),
        ),
    ]
