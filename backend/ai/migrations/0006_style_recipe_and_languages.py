from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("ai", "0005_director_workflow"),
    ]

    operations = [
        migrations.AlterField(
            model_name="merchantpreference",
            name="language",
            field=models.CharField(
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
        migrations.AlterField(
            model_name="videoproject",
            name="language",
            field=models.CharField(
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
        migrations.CreateModel(
            name="StyleRecipe",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.SlugField(max_length=64)),
                ("name", models.CharField(max_length=120)),
                ("recipe", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="style_recipes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "source_project",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="saved_styles",
                        to="ai.videoproject",
                    ),
                ),
            ],
            options={
                "ordering": ["-updated_at"],
                "unique_together": {("owner", "key")},
            },
        ),
    ]
