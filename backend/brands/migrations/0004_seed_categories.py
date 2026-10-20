from django.db import migrations


CATEGORIES = (
    ("fashion-beauty", "Fashion & Beauty"),
    ("food-home", "Food & Home"),
)


def seed_categories(apps, schema_editor):
    Category = apps.get_model("brands", "Category")
    Brand = apps.get_model("brands", "Brand")
    for slug, name in CATEGORIES:
        Category.objects.get_or_create(slug=slug, defaults={"name": name})
    first = Category.objects.order_by("id").first()
    if first:
        Brand.objects.filter(category__isnull=True).update(category=first)


def unseed_categories(apps, schema_editor):
    Category = apps.get_model("brands", "Category")
    Category.objects.filter(slug__in=[slug for slug, _ in CATEGORIES]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("brands", "0003_category_brand_category"),
    ]

    operations = [
        migrations.RunPython(seed_categories, unseed_categories),
    ]
