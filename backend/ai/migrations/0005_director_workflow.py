from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0004_speaker_gender"),
    ]

    operations = [
        migrations.AddField(
            model_name="videoproject",
            name="selected_concept_id",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="videoproject",
            name="amendment_recommendations",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="videoproject",
            name="amendment_history",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="videoproject",
            name="director_events",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
