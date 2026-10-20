import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("brands", "0004_seed_categories"),
    ]

    operations = [
        migrations.AlterField(
            model_name="brand",
            name="category",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="brands",
                to="brands.category",
            ),
        ),
    ]
