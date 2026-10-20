from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0011_video_poster"),
    ]

    operations = [
        migrations.AddField(
            model_name="bulkgeneration",
            name="instruction",
            field=models.TextField(blank=True),
        ),
    ]
