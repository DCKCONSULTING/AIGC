from django.core.management import call_command
from django.test import TestCase

from accounts.models import User
from ai.models import (
    Character,
    CharacterReferenceImage,
    CharacterStatus,
    StyleRecipe,
    VideoCharacterConfig,
    VideoProject,
)
from ai.services.characters import resolve_voice
from ai.services.misa_seed import collect_summary
from brands.models import Brand, Category, Product


class MisaSeedCommandTests(TestCase):
    def test_seed_is_idempotent_and_reset_keeps_other_data(self):
        kept_category = Category.objects.create(name="Kept Category", slug="kept-category")
        outsider = User.objects.create_user(
            username="kept_producer",
            email="kept.producer@example.com",
            password="kept-password",
            name="Kept Producer",
            mobile="0120000000",
            location="Penang",
            role=User.Role.PRODUCER,
        )
        kept_brand = Brand.objects.create(
            owner=outsider,
            category=kept_category,
            name="Kept Brand",
            location="Penang",
        )
        kept_product = Product.objects.create(brand=kept_brand, name="Kept Product", price="10.00")

        call_command("seed_misa_test_data")
        first = collect_summary()
        call_command("seed_misa_test_data")
        second = collect_summary()
        self.assertEqual(first, second)
        self.assertGreaterEqual(first["products"], 12)
        self.assertGreaterEqual(first["characters"], 10)
        self.assertGreaterEqual(first["styles"], 5)
        self.assertGreaterEqual(first["videos"], 31)
        self.assertGreaterEqual(first["legacy"], 2)
        self.assertGreaterEqual(first["bulk"], 10)
        self.assertGreaterEqual(first["reviews"], 8)
        self.assertGreaterEqual(first["references"], 12)
        self.assertEqual(first["archived"], 1)

        demo = Brand.objects.get(name="MISA Demo Brand")
        other = Brand.objects.get(name="MISA Demo Brand B")
        sarah = Character.objects.get(brand=demo, name="Sarah")
        variant = Character.objects.get(brand=demo, name="Sarah — Premium Variant")
        self.assertNotEqual(sarah.pk, variant.pk)
        self.assertEqual(sarah.default_language, "english")
        self.assertEqual(sarah.default_tone, "warm")
        self.assertEqual(sarah.default_voice_id, resolve_voice("english", "female")["voice_id"])
        self.assertTrue(
            set(variant.references.values_list("image", flat=True))
            & set(sarah.references.values_list("image", flat=True))
        )
        self.assertEqual(sarah.references.filter(view_type="front").count(), 1)
        self.assertFalse(Character.objects.get(name="Alex", brand=demo).references.exists())
        self.assertEqual(
            Character.objects.get(name="Archived Demo Character", brand=demo).status,
            CharacterStatus.ARCHIVED,
        )

        blender = VideoProject.objects.get(creative_brief__seed_key="misa-test-generate-blender")
        self.assertEqual(blender.character_config.language, "mandarin_my")
        self.assertEqual(blender.character_config.tone, "luxury")
        self.assertNotEqual(blender.character_config.voice_id, sarah.default_voice_id)
        self.assertEqual(blender.google_operation, "")
        self.assertEqual(blender.provider_request_id, "")

        legacy = VideoProject.objects.filter(creative_brief__legacy=True)
        self.assertGreaterEqual(legacy.count(), 2)
        for project in legacy:
            self.assertFalse(VideoCharacterConfig.objects.filter(project=project).exists())
            self.assertTrue(project.assets.filter(metadata__presenter_reference=True).exists())

        bulk_ids = set(
            VideoProject.objects.filter(creative_brief__bulk=True).values_list(
                "character_config__character_id", flat=True
            )
        )
        self.assertEqual(bulk_ids, {sarah.pk})
        self.assertFalse(Character.objects.filter(brand=other, owner=demo.owner).exists())
        self.assertFalse(Product.objects.filter(brand=other, brand__owner=demo.owner).exists())
        self.assertGreaterEqual(StyleRecipe.objects.filter(owner=demo.owner).count(), 5)
        self.assertGreaterEqual(CharacterReferenceImage.objects.filter(character=sarah).count(), 5)

        call_command("seed_misa_test_data", "--reset")
        self.assertFalse(User.objects.filter(email="misa.producer@test.local").exists())
        self.assertFalse(Brand.objects.filter(name="MISA Demo Brand").exists())
        self.assertFalse(Category.objects.filter(slug__startswith="misa-demo-").exists())
        self.assertTrue(Product.objects.filter(pk=kept_product.pk).exists())
        self.assertTrue(Category.objects.filter(pk=kept_category.pk).exists())
