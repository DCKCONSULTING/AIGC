from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0003_videoproject_creative_directions_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="merchantpreference",
            name="speaker_gender",
            field=models.CharField(
                choices=[("female", "Female"), ("male", "Male"), ("neutral", "Neutral")],
                default="female",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="videoproject",
            name="speaker_gender",
            field=models.CharField(
                choices=[("female", "Female"), ("male", "Male"), ("neutral", "Neutral")],
                default="female",
                max_length=16,
            ),
        ),
    ]
