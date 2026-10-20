from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("brands", "0011_campaign_content"),
        ("ai", "0009_master_character_reference"),
    ]

    operations = [
        migrations.CreateModel(
            name="BulkGeneration",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "mode",
                    models.CharField(
                        choices=[
                            ("character", "Character variations"),
                            ("product", "Product variations"),
                            ("reference_location", "Reuse story, change location"),
                            ("reference_character", "Reuse story, change character"),
                        ],
                        max_length=32,
                    ),
                ),
                ("title", models.CharField(blank=True, max_length=160)),
                (
                    "language",
                    models.CharField(
                        choices=[
                            ("conversational_bm", "Conversational BM"),
                            ("formal_bm", "Formal BM"),
                            ("bm_english", "BM + English"),
                            ("english", "English"),
                            ("chinese", "Chinese"),
                            ("cantonese", "Cantonese"),
                            ("hokkien", "Hokkien"),
                            ("mandarin_my", "Malaysian Mandarin"),
                            ("tamil_my", "Malaysian Tamil"),
                        ],
                        default="conversational_bm",
                        max_length=32,
                    ),
                ),
                (
                    "speaking_style",
                    models.CharField(
                        choices=[
                            ("warm", "Warm and friendly"),
                            ("bold", "Bold and energetic"),
                            ("calm", "Calm and trusted"),
                            ("luxury", "Premium and refined"),
                        ],
                        default="warm",
                        max_length=32,
                    ),
                ),
                ("duration_seconds", models.PositiveIntegerField(default=45)),
                ("requested_count", models.PositiveIntegerField(default=10)),
                ("character_ids", models.JSONField(blank=True, default=list)),
                ("locks", models.JSONField(blank=True, default=dict)),
                ("variables", models.JSONField(blank=True, default=dict)),
                ("reference_video", models.FileField(blank=True, upload_to="ai/bulk/references/%Y/%m/")),
                ("master_spec", models.JSONField(blank=True, default=dict)),
                ("generation_plan", models.JSONField(blank=True, default=list)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("analyzing", "Analyzing"),
                            ("plan_ready", "Plan ready"),
                            ("queued", "Queued"),
                            ("generating", "Generating"),
                            ("completed", "Completed"),
                            ("completed_with_errors", "Completed with errors"),
                            ("failed", "Failed"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="draft",
                        max_length=32,
                    ),
                ),
                ("error_message", models.CharField(blank=True, max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "character",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="bulk_generations",
                        to="ai.character",
                    ),
                ),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="bulk_generations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "product",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="bulk_generations",
                        to="brands.product",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="BulkGenerationItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sequence", models.PositiveIntegerField(default=1)),
                ("title", models.CharField(blank=True, max_length=200)),
                ("variation_config", models.JSONField(blank=True, default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("planned", "Planned"),
                            ("queued", "Queued"),
                            ("generating", "Generating"),
                            ("completed", "Completed"),
                            ("failed", "Failed"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="draft",
                        max_length=16,
                    ),
                ),
                ("error_message", models.CharField(blank=True, max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "bulk",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="items",
                        to="ai.bulkgeneration",
                    ),
                ),
                (
                    "video_project",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="bulk_item",
                        to="ai.videoproject",
                    ),
                ),
            ],
            options={"ordering": ["sequence", "id"]},
        ),
        migrations.AlterUniqueTogether(
            name="bulkgenerationitem",
            unique_together={("bulk", "sequence")},
        ),
    ]
