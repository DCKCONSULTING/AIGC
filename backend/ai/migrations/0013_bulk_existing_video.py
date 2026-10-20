from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0012_bulk_instruction"),
    ]

    operations = [
        migrations.AddField(
            model_name="bulkgeneration",
            name="reference_url",
            field=models.URLField(blank=True),
        ),
        migrations.AlterField(
            model_name="bulkgeneration",
            name="mode",
            field=models.CharField(
                choices=[
                    ("character", "Character variations"),
                    ("product", "Product variations"),
                    ("existing_video", "Same flow from existing video"),
                    ("reference_location", "Reuse story, change location"),
                    ("reference_character", "Reuse story, change character"),
                ],
                max_length=32,
            ),
        ),
    ]
