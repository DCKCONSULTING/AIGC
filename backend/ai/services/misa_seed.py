"""Development-only MISA Studio dataset.

Records are identified by the emails, slugs, product URLs, and creative_brief.seed_key
values below. Re-running updates those rows in place. It does not touch anything else.
No Omni, Google TTS, FFmpeg, or django-q job is started.
"""

from __future__ import annotations

import io
import shutil
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFont

from accounts.models import User
from ai.models import (
    Character,
    CharacterReferenceImage,
    CharacterStatus,
    CharacterView,
    GenderChoice,
    LanguageChoice,
    MerchantPreference,
    QAStatus,
    Scene,
    StyleChoice,
    StyleRecipe,
    VideoAsset,
    VideoCharacterConfig,
    VideoProject,
    VideoProjectStatus,
    VideoProjectVersion,
)
from ai.services.characters import _identity_snapshot, _reference_snapshot, resolve_voice, sync_project_character
from ai.services.qa import release_blocking_issues
from ai.services.snapshots import product_snapshot
from brands.models import Brand, Category, Product, ProductImage

SEED_MARKER = "misa-demo-seed"
PASSWORD = "misa-demo-local"
PRODUCER_EMAIL = "misa.producer@test.local"
PRODUCER_B_EMAIL = "misa.producer.b@test.local"
SEED_EMAILS = (PRODUCER_EMAIL, PRODUCER_B_EMAIL)
BRAND_NAME = "MISA Demo Brand"
BRAND_B_NAME = "MISA Demo Brand B"

CATEGORIES = (
    ("Restaurants", "misa-demo-restaurants"),
    ("Beauty & Personal Care", "misa-demo-beauty"),
    ("Technology", "misa-demo-technology"),
    ("Home & Office", "misa-demo-home-office"),
    ("Fashion", "misa-demo-fashion"),
    ("Health & Wellness", "misa-demo-health"),
)

PRODUCTS = (
    {
        "slug": "smart-coffee-machine",
        "name": "MISA Smart Coffee Machine",
        "price": "899.00",
        "description": "Automatic coffee machine designed for home and small office use.",
        "benefit": "A consistent cup without standing over the machine.",
        "offer": "",
        "offer_days": None,
        "images": 1,
        "claims": ["Makes espresso and filter coffee from one machine"],
    },
    {
        "slug": "premium-office-chair",
        "name": "MISA Premium Office Chair",
        "price": "1299.00",
        "original_price": "1599.00",
        "description": "Adjustable office chair with a breathable back and lockable wheels.",
        "benefit": "Supports a full workday without a stiff seat.",
        "offer": "RM300 off the marked price",
        "offer_days": 30,
        "images": 2,
        "claims": ["Adjustable seat height and lockable wheels"],
    },
    {
        "slug": "air-fryer-pro",
        "name": "MISA Air Fryer Pro",
        "price": "499.00",
        "description": (
            "A 5-litre air fryer for family meals. The basket is removable for washing, "
            "the timer stops the heat at the end of the cycle, and the window lets you "
            "check the food without opening the drawer. Suitable for home kitchens. "
            "It does not replace an oven for every recipe."
        ),
        "benefit": "Crisp food with a visible basket and a timer that stops the heat.",
        "offer": "Recipe-card bundle while the current offer lasts",
        "offer_days": 14,
        "images": 1,
        "claims": ["5-litre basket", "Timer stops the heat at the end of the cycle"],
    },
    {
        "slug": "skincare-starter-set",
        "name": "MISA Skincare Starter Set",
        "price": "189.00",
        "description": "Cleanser, moisturiser, and sunscreen for a simple daily routine.",
        "benefit": "Three everyday steps in one set.",
        "offer": "",
        "offer_days": None,
        "images": 1,
        "claims": ["Includes cleanser, moisturiser, and sunscreen"],
    },
    {
        "slug": "wireless-earbuds",
        "name": "MISA Wireless Earbuds",
        "price": "299.00",
        "original_price": "349.00",
        "description": "Wireless earbuds with a charging case and touch controls.",
        "benefit": "Pocketable sound with a case that charges the buds.",
        "offer": "RM50 off",
        "offer_days": 21,
        "images": 3,
        "claims": ["Charging case included", "Touch controls on each bud"],
    },
    {
        "slug": "smart-blender",
        "name": "MISA Smart Blender",
        "price": "359.00",
        "description": (
            "Countertop blender with a marked jug, a pulse button, and a lid that locks "
            "before the blades start. Built for smoothies and crushed ice at home. "
            "The jug is dishwasher-safe on the top rack. Keep hands clear of the blades."
        ),
        "benefit": "A locked lid and marked jug for everyday blending.",
        "offer": "",
        "offer_days": None,
        "images": 1,
        "claims": ["Lid locks before the blades start"],
    },
    {
        "slug": "premium-desk-lamp",
        "name": "MISA Premium Desk Lamp",
        "price": "159.00",
        "description": "Dimmable LED desk lamp.",
        "benefit": "A dimmable light for a desk.",
        "offer": "",
        "offer_days": None,
        "images": 1,
        "claims": ["Dimmable LED"],
    },
    {
        "slug": "travel-backpack",
        "name": "MISA Travel Backpack",
        "price": "229.00",
        "description": "Carry-on backpack with a padded laptop sleeve and a side water-bottle pocket.",
        "benefit": "A padded sleeve for a laptop and a pocket for a bottle.",
        "offer": "Free packing pouch included",
        "offer_days": 60,
        "images": 2,
        "claims": ["Padded laptop sleeve"],
    },
    {
        "slug": "restaurant-loyalty-app",
        "name": "MISA Restaurant Loyalty App",
        "price": "99.00",
        "description": "A monthly app plan for recording visits and sending a stamp reward.",
        "benefit": "Customers collect a stamp each visit.",
        "offer": "",
        "offer_days": None,
        "images": 1,
        "claims": ["Records a visit and a stamp reward"],
    },
    {
        "slug": "hotel-booking-system",
        "name": "MISA Hotel Booking System",
        "price": "299.00",
        "description": (
            "A monthly booking desk for independent hotels. Staff can take a reservation, "
            "see the room calendar, and send a confirmation. The listed price is per month. "
            "It does not guarantee occupancy."
        ),
        "benefit": "Reservations and a room calendar in one monthly plan.",
        "offer": "First month RM199",
        "offer_days": -1,
        "images": 1,
        "claims": ["Room calendar and reservation confirmation"],
    },
)

CHARACTERS = (
    {
        "key": "sarah",
        "name": "Sarah",
        "gender": GenderChoice.FEMALE,
        "description": "Friendly Malaysian business presenter.",
        "appearance": (
            "Malaysian woman in her early 30s, shoulder-length dark hair, "
            "professional appearance, light blue blazer, natural makeup."
        ),
        "personality": "Friendly, confident, approachable.",
        "wardrobe": "Professional light blue blazer.",
        "language": LanguageChoice.ENGLISH,
        "tone": StyleChoice.WARM,
        "views": ("front", "left", "right", "up", "down"),
    },
    {
        "key": "ahmad",
        "name": "Ahmad",
        "gender": GenderChoice.MALE,
        "description": "Energetic Malaysian business presenter.",
        "appearance": "Malaysian man in his late 30s, short black hair, smart casual appearance.",
        "personality": "Energetic and persuasive.",
        "wardrobe": "Dark polo shirt.",
        "language": LanguageChoice.CONVERSATIONAL_BM,
        "tone": StyleChoice.BOLD,
        "views": ("front", "left", "right"),
    },
    {
        "key": "mei",
        "name": "Mei",
        "gender": GenderChoice.FEMALE,
        "description": "Premium lifestyle presenter.",
        "appearance": (
            "Malaysian Chinese woman, approximately 30 years old, "
            "long dark hair, elegant professional appearance."
        ),
        "personality": "Calm and sophisticated.",
        "wardrobe": "Elegant neutral blazer.",
        "language": LanguageChoice.MANDARIN_MY,
        "tone": StyleChoice.LUXURY,
        "views": ("front",),
    },
    {
        "key": "daniel",
        "name": "Daniel",
        "gender": GenderChoice.MALE,
        "description": "Casual technology presenter.",
        "appearance": "Young Malaysian man, short dark hair, casual modern clothing.",
        "personality": "Relaxed, knowledgeable, conversational.",
        "wardrobe": "Casual shirt.",
        "language": LanguageChoice.BM_ENGLISH,
        "tone": StyleChoice.CALM,
        "views": ("front", "right"),
    },
    {
        "key": "priya",
        "name": "Priya",
        "gender": GenderChoice.FEMALE,
        "description": "Friendly lifestyle presenter.",
        "appearance": (
            "Malaysian Indian woman, approximately 30 years old, "
            "long dark hair, warm natural appearance."
        ),
        "personality": "Warm and enthusiastic.",
        "wardrobe": "Soft everyday blouse.",
        "language": LanguageChoice.TAMIL_MY,
        "tone": StyleChoice.WARM,
        "views": ("front",),
    },
    {
        "key": "alex",
        "name": "Alex",
        "gender": GenderChoice.NEUTRAL,
        "description": "Modern technology presenter.",
        "appearance": "Professional modern presenter with neutral styling.",
        "personality": "Clear, informative, confident.",
        "wardrobe": "Neutral tailored jacket.",
        "language": LanguageChoice.ENGLISH,
        "tone": StyleChoice.LUXURY,
        "views": (),
    },
)

STYLES = (
    ("misa-demo-premium-product", "Premium Product Commercial", "Clean premium commercial with cinematic product shots."),
    ("misa-demo-social-fast", "Social Fast Cut", "Fast-paced vertical social video optimized for short attention spans."),
    ("misa-demo-malaysian-lifestyle", "Malaysian Lifestyle", "Natural Malaysian lifestyle commercial with warm everyday scenes."),
    ("misa-demo-restaurant", "Restaurant Showcase", "Food-focused commercial emphasizing atmosphere and product detail."),
    ("misa-demo-modern-technology", "Modern Technology", "Clean modern technology commercial with dynamic camera movement."),
)

# Workflow projects. Overrides are per video and must not be written back onto the Character.
WORKFLOW = (
    {"key": "misa-test-brief-coffee", "product": "smart-coffee-machine", "character": "sarah", "stage": "brief", "duration": 45, "language": "english", "tone": "warm"},
    {"key": "misa-test-brief-chair", "product": "premium-office-chair", "character": "ahmad", "stage": "brief", "duration": 30, "language": "conversational_bm", "tone": "bold"},
    {"key": "misa-test-concepts-fryer", "product": "air-fryer-pro", "character": "mei", "stage": "concepts", "duration": 45, "language": "english", "tone": "warm", "override": True},
    {"key": "misa-test-concepts-earbuds", "product": "wireless-earbuds", "character": "daniel", "stage": "concepts", "duration": 30, "language": "bm_english", "tone": "calm"},
    {"key": "misa-test-story-skincare", "product": "skincare-starter-set", "character": "priya", "stage": "storyboard", "duration": 60, "language": "tamil_my", "tone": "warm", "reorder": True},
    {"key": "misa-test-story-lamp", "product": "premium-desk-lamp", "character": "alex", "stage": "storyboard", "duration": 15, "language": "english", "tone": "luxury"},
    {"key": "misa-test-generate-blender", "product": "smart-blender", "character": "sarah", "stage": "planning", "duration": 45, "language": "mandarin_my", "tone": "luxury", "override": True, "voice_gender": "female"},
    {"key": "misa-test-generate-backpack", "product": "travel-backpack", "character": "ahmad", "stage": "generating", "duration": 30, "language": "bm_english", "tone": "calm", "override": True, "voice_gender": "female"},
    {"key": "misa-test-review-pass", "product": "restaurant-loyalty-app", "character": "sarah", "stage": "review", "duration": 30, "language": "formal_bm", "tone": "warm", "qa": "pass"},
    {"key": "misa-test-review-price", "product": "premium-office-chair", "character": "mei", "stage": "review", "duration": 45, "language": "chinese", "tone": "bold", "qa": "price_fail"},
    {"key": "misa-test-approve-earbuds", "product": "wireless-earbuds", "character": "daniel", "stage": "approved", "duration": 30, "language": "hokkien", "tone": "bold", "qa": "pass"},
    {"key": "misa-test-approve-skincare", "product": "skincare-starter-set", "character": "priya", "stage": "approved", "duration": 45, "language": "cantonese", "tone": "calm", "qa": "pass"},
    {"key": "misa-test-review-audio", "product": "smart-coffee-machine", "character": "sarah", "stage": "review", "duration": 30, "language": "english", "tone": "warm", "qa": "missing_audio"},
    {"key": "misa-test-review-visual", "product": "wireless-earbuds", "character": "daniel", "stage": "review", "duration": 30, "language": "english", "tone": "calm", "qa": "visual_mismatch"},
    {"key": "misa-test-review-caption", "product": "travel-backpack", "character": "ahmad", "stage": "review", "duration": 30, "language": "conversational_bm", "tone": "bold", "qa": "caption_fail"},
    {"key": "misa-test-review-cta", "product": "premium-desk-lamp", "character": "alex", "stage": "review", "duration": 30, "language": "english", "tone": "luxury", "qa": "incomplete_cta"},
    {"key": "misa-test-review-captions-open", "product": "air-fryer-pro", "character": "mei", "stage": "review", "duration": 45, "language": "mandarin_my", "tone": "luxury", "qa": "captions_unchecked"},
    {"key": "misa-test-review-expired", "product": "hotel-booking-system", "character": "sarah", "stage": "review", "duration": 45, "language": "english", "tone": "luxury", "qa": "expired_offer"},
    {"key": "misa-test-legacy-presenter-1", "product": "smart-coffee-machine", "character": None, "stage": "storyboard", "duration": 30, "language": "english", "tone": "warm", "legacy": True},
    {"key": "misa-test-legacy-presenter-2", "product": "premium-office-chair", "character": None, "stage": "review", "duration": 45, "language": "conversational_bm", "tone": "calm", "legacy": True, "qa": "pass"},
    {"key": "misa-test-archived-history", "product": "restaurant-loyalty-app", "character": "archived", "stage": "review", "duration": 30, "language": "english", "tone": "calm", "qa": "pass", "archived_subject": True},
)

BULK_LANGUAGES = (
    "conversational_bm",
    "formal_bm",
    "bm_english",
    "english",
    "chinese",
    "cantonese",
    "hokkien",
    "mandarin_my",
    "tamil_my",
    "english",
)
BULK_TONES = ("warm", "calm", "bold", "luxury")


def development_allowed() -> bool:
    if settings.DEBUG:
        return True
    return "test" in __import__("sys").argv


class SeedError(Exception):
    pass


def seed_dataset() -> dict:
    if not development_allowed():
        raise SeedError("seed_misa_test_data is development-only. DEBUG is false.")
    with transaction.atomic():
        created_password = _seed()
    errors = validate_dataset()
    if errors:
        raise SeedError("Seed validation failed:\n" + "\n".join(errors))
    summary = collect_summary()
    summary["password_set"] = created_password
    return summary


def reset_dataset() -> dict:
    if not development_allowed():
        raise SeedError("seed_misa_test_data is development-only. DEBUG is false.")
    summary = collect_summary()
    delete_dataset()
    return summary


def delete_dataset() -> None:
    if not development_allowed():
        raise SeedError("seed_misa_test_data is development-only. DEBUG is false.")
    with transaction.atomic():
        User.objects.filter(email__in=SEED_EMAILS).delete()
        Category.objects.filter(slug__startswith="misa-demo-").filter(brands__isnull=True).delete()
    media = settings.MEDIA_ROOT / "misa-demo"
    if media.exists():
        shutil.rmtree(media)


def collect_summary() -> dict:
    users = User.objects.filter(email__in=SEED_EMAILS)
    brands = Brand.objects.filter(owner__in=users)
    projects = VideoProject.objects.filter(owner__in=users)
    characters = Character.objects.filter(owner__in=users)
    storyboards = projects.filter(scenes__isnull=False).distinct()
    reviews = projects.exclude(qa_results={})
    return {
        "brands": brands.count(),
        "brand_name": BRAND_NAME,
        "producer": PRODUCER_EMAIL,
        "categories": Category.objects.filter(slug__startswith="misa-demo-").count(),
        "products": Product.objects.filter(brand__in=brands).count(),
        "characters": characters.count(),
        "references": CharacterReferenceImage.objects.filter(character__in=characters).count(),
        "styles": StyleRecipe.objects.filter(owner__in=users).count(),
        "videos": projects.count(),
        "configs": VideoCharacterConfig.objects.filter(project__in=projects).count(),
        "legacy": projects.filter(creative_brief__legacy=True).count(),
        "storyboards": storyboards.count(),
        "scenes": Scene.objects.filter(project__in=projects).count(),
        "reviews": reviews.count(),
        "archived": characters.filter(status=CharacterStatus.ARCHIVED).count(),
        "bulk": projects.filter(creative_brief__bulk=True).count(),
    }


def validate_dataset() -> list[str]:
    errors = []
    demo = _brand(PRODUCER_EMAIL, BRAND_NAME)
    other = _brand(PRODUCER_B_EMAIL, BRAND_B_NAME)
    if not demo or not other:
        return ["Demo brands were not created."]
    active = Character.objects.filter(brand=demo, status=CharacterStatus.ACTIVE)
    if active.filter(brand__isnull=True).exists():
        errors.append("An active character has no brand.")
    if CharacterReferenceImage.objects.filter(character__brand=demo, character__isnull=True).exists():
        errors.append("A reference image has no character.")
    for config in VideoCharacterConfig.objects.filter(project__product__brand=demo):
        if config.character_id is None:
            errors.append(f"Config {config.pk} has no character.")
        elif config.character.brand_id != demo.id and config.character.brand_id != other.id:
            errors.append(f"Config {config.pk} points at the wrong brand.")
        if not config.appearance_snapshot and not config.reference_snapshot:
            errors.append(f"Config {config.pk} has no frozen appearance or references.")
        if not config.voice_id or not config.language or not config.tone:
            errors.append(f"Config {config.pk} is missing voice, language, or tone.")
    if Product.objects.filter(brand=demo, brand__owner__email=PRODUCER_B_EMAIL).exists():
        errors.append("A demo product is owned by the other producer.")
    if Character.objects.filter(brand=other, owner__email=PRODUCER_EMAIL).exists():
        errors.append("Brand B characters are owned by Brand A.")
    legacy = VideoProject.objects.filter(owner__email=PRODUCER_EMAIL, creative_brief__legacy=True)
    if legacy.count() < 2:
        errors.append("Expected two legacy presenter videos.")
    for project in legacy:
        if VideoCharacterConfig.objects.filter(project=project).exists():
            errors.append(f"Legacy video {project.creative_brief.get('seed_key')} has a character config.")
    sarah = Character.objects.filter(brand=demo, name="Sarah").first()
    bulk = VideoProject.objects.filter(owner__email=PRODUCER_EMAIL, creative_brief__bulk=True)
    if sarah and bulk.count() >= 10:
        ids = set(bulk.values_list("character_config__character_id", flat=True))
        if ids != {sarah.pk}:
            errors.append(f"Bulk videos do not all use Sarah ({ids}).")
    else:
        errors.append("Bulk videos or Sarah are missing.")
    if sarah and sarah.default_language != LanguageChoice.ENGLISH:
        errors.append("Sarah's default language changed.")
    if sarah and sarah.default_tone != StyleChoice.WARM:
        errors.append("Sarah's default tone changed.")
    if sarah and sarah.default_voice_id != resolve_voice(LanguageChoice.ENGLISH, GenderChoice.FEMALE)["voice_id"]:
        errors.append("Sarah's default voice changed.")
    override = VideoProject.objects.filter(creative_brief__seed_key="misa-test-generate-blender").first()
    if override and sarah:
        config = getattr(override, "character_config", None)
        if not config or config.language != LanguageChoice.MANDARIN_MY or config.tone != StyleChoice.LUXURY:
            errors.append("Sarah's blender video did not keep its override snapshot.")
        if config and config.voice_id == sarah.default_voice_id:
            errors.append("Sarah's override video reused her default voice id.")
    archived = Character.objects.filter(brand=demo, name="Archived Demo Character").first()
    if not archived or archived.status != CharacterStatus.ARCHIVED:
        errors.append("Archived demo character is missing.")
    elif not VideoCharacterConfig.objects.filter(character=archived).exists():
        errors.append("Archived character has no historical video config.")
    variant = Character.objects.filter(brand=demo, name="Sarah — Premium Variant").first()
    if not variant or not sarah or variant.pk == sarah.pk:
        errors.append("Sarah's duplicate was not created as a separate character.")
    return errors


def _seed() -> bool:
    categories = {name: _category(name, slug) for name, slug in CATEGORIES}
    producer, password_set = _producer(
        PRODUCER_EMAIL,
        "misa_producer",
        "MISA Demo Producer",
    )
    producer_b, _ = _producer(
        PRODUCER_B_EMAIL,
        "misa_producer_b",
        "MISA Demo Producer B",
    )
    brand = _ensure_brand(producer, BRAND_NAME, categories["Home & Office"], "Home and office products for local studio testing.")
    brand_b = _ensure_brand(producer_b, BRAND_B_NAME, categories["Technology"], "Second brand for isolation tests.")
    products = {item["slug"]: _ensure_product(brand, item) for item in PRODUCTS}
    _ensure_product(
        brand_b,
        {
            "slug": "brand-b-router",
            "name": "MISA Demo B Router",
            "price": "249.00",
            "description": "Home router used only for Brand B isolation tests.",
            "benefit": "A spare router for the second brand.",
            "offer": "",
            "offer_days": None,
            "images": 1,
            "claims": ["Dual-band home router"],
        },
    )
    _ensure_product(
        brand_b,
        {
            "slug": "brand-b-keyboard",
            "name": "MISA Demo B Keyboard",
            "price": "179.00",
            "description": "Compact keyboard used only for Brand B isolation tests.",
            "benefit": "A spare keyboard for the second brand.",
            "offer": "",
            "offer_days": None,
            "images": 1,
            "claims": ["Compact keyboard"],
        },
    )
    characters = {item["key"]: _ensure_character(producer, brand, item) for item in CHARACTERS}
    characters["archived"] = _ensure_character(
        producer,
        brand,
        {
            "key": "archived",
            "name": "Archived Demo Character",
            "gender": GenderChoice.NEUTRAL,
            "description": "Retired presenter kept for historical videos.",
            "appearance": "Professional presenter in a grey jacket. Archived test identity.",
            "personality": "Calm and clear.",
            "wardrobe": "Grey jacket.",
            "language": LanguageChoice.ENGLISH,
            "tone": StyleChoice.CALM,
            "views": ("front",),
        },
    )
    _ensure_duplicate(producer, brand, characters["sarah"])
    _ensure_character(
        producer_b,
        brand_b,
        {
            "key": "b-aisha",
            "name": "Brand B Aisha",
            "gender": GenderChoice.FEMALE,
            "description": "Brand B presenter. Must not be visible to Brand A.",
            "appearance": "Malaysian woman, short hair, navy jacket.",
            "personality": "Direct and clear.",
            "wardrobe": "Navy jacket.",
            "language": LanguageChoice.ENGLISH,
            "tone": StyleChoice.WARM,
            "views": ("front",),
        },
    )
    _ensure_character(
        producer_b,
        brand_b,
        {
            "key": "b-wei",
            "name": "Brand B Wei",
            "gender": GenderChoice.MALE,
            "description": "Brand B presenter. Must not be visible to Brand A.",
            "appearance": "Malaysian man, short hair, white shirt.",
            "personality": "Steady and practical.",
            "wardrobe": "White shirt.",
            "language": LanguageChoice.CHINESE,
            "tone": StyleChoice.CALM,
            "views": ("front",),
        },
    )
    _preference(producer, characters["sarah"])
    _preference(producer_b, Character.objects.get(brand=brand_b, name="Brand B Aisha"))
    for spec in WORKFLOW:
        _ensure_project(producer, products, characters, spec)
    for index, product in enumerate(PRODUCTS):
        _ensure_project(
            producer,
            products,
            characters,
            {
                "key": f"misa-test-bulk-{index + 1:02d}",
                "product": product["slug"],
                "character": "sarah",
                "stage": "brief",
                "duration": 30,
                "language": BULK_LANGUAGES[index],
                "tone": BULK_TONES[index % len(BULK_TONES)],
                "bulk": True,
                "style_key": "misa-demo-premium-product",
            },
        )
    _ensure_project(
        producer_b,
        {
            "brand-b-router": Product.objects.get(brand=brand_b, name="MISA Demo B Router"),
        },
        {
            "b-aisha": Character.objects.get(brand=brand_b, name="Brand B Aisha"),
        },
        {
            "key": "misa-test-b-brief",
            "product": "brand-b-router",
            "character": "b-aisha",
            "stage": "brief",
            "duration": 30,
            "language": "english",
            "tone": "warm",
        },
    )
    _ensure_styles(producer)
    archived = characters["archived"]
    archived.status = CharacterStatus.ARCHIVED
    archived.save(update_fields=["status", "updated_at"])
    return password_set


def _producer(email: str, username: str, name: str) -> tuple[User, bool]:
    user = User.objects.filter(email__iexact=email).first()
    if user:
        return user, False
    user = User.objects.create_user(
        username=username,
        email=email,
        password=PASSWORD,
        name=name,
        mobile="0100000000",
        location="Kuala Lumpur",
        role=User.Role.PRODUCER,
    )
    return user, email == PRODUCER_EMAIL


def _category(name: str, slug: str) -> Category:
    found = Category.objects.filter(slug=slug).first()
    if found:
        return found
    if Category.objects.filter(name=name).exists():
        name = f"MISA Demo {name}"
    return Category.objects.create(name=name, slug=slug)


def _ensure_brand(owner, name: str, category: Category, description: str) -> Brand:
    brand = Brand.objects.filter(owner=owner, name=name).first()
    if brand:
        return brand
    return Brand.objects.create(
        owner=owner,
        category=category,
        name=name,
        description=description,
        location="Kuala Lumpur",
        website="https://misa-demo.test",
        status=Brand.Status.ACTIVE,
    )


def _ensure_product(brand: Brand, spec: dict) -> Product:
    url = f"https://misa-demo.test/products/{spec['slug']}"
    today = timezone.localdate()
    expiry = None
    if spec.get("offer_days") is not None:
        expiry = today + timedelta(days=spec["offer_days"])
    product = Product.objects.filter(brand=brand, product_url=url).first()
    fields = {
        "name": spec["name"],
        "description": spec["description"],
        "price": Decimal(spec["price"]),
        "offer": spec.get("offer") or "",
        "offer_expiry": expiry,
        "approved_claims": spec.get("claims") or [],
        "prohibited_claims": ["Cures disease", "Guaranteed results"],
        "materials": spec.get("materials") or "",
        "dimensions": spec.get("dimensions") or "",
        "shipping_conditions": "Ships within Malaysia.",
    }
    if product:
        for key, value in fields.items():
            setattr(product, key, value)
        product.save()
    else:
        product = Product.objects.create(brand=brand, product_url=url, **fields)
    for index in range(spec.get("images") or 1):
        label = "front" if index == 0 else f"angle-{index + 1}"
        _ensure_product_image(product, spec["slug"], label, index)
    return product


def _ensure_character(owner, brand: Brand, spec: dict) -> Character:
    voice = resolve_voice(spec["language"], spec["gender"])
    character = Character.objects.filter(brand=brand, name=spec["name"]).first()
    if not character:
        character = Character(owner=owner, brand=brand, name=spec["name"], gender=spec["gender"])
    character.owner = owner
    character.description = spec["description"]
    character.gender = spec["gender"]
    character.appearance_description = spec["appearance"]
    character.personality_description = spec["personality"]
    character.wardrobe_description = spec["wardrobe"]
    character.default_language = spec["language"]
    character.default_tone = spec["tone"]
    character.default_voice_provider = voice["voice_provider"]
    character.default_voice_id = voice["voice_id"]
    character.default_voice_name = voice["voice_name"]
    if character.name != "Archived Demo Character":
        character.status = CharacterStatus.ACTIVE
    character.save()
    for index, view in enumerate(spec["views"]):
        _ensure_character_image(character, spec["key"], view, index)
    return character


def _ensure_duplicate(owner, brand: Brand, sarah: Character) -> Character:
    voice = resolve_voice(LanguageChoice.ENGLISH, GenderChoice.FEMALE, _alternate_voice(LanguageChoice.ENGLISH, GenderChoice.FEMALE))
    spec = {
        "key": "sarah-premium",
        "name": "Sarah — Premium Variant",
        "gender": GenderChoice.FEMALE,
        "description": "Independent duplicate of Sarah for archive and default tests.",
        "appearance": sarah.appearance_description,
        "personality": "More reserved than Sarah.",
        "wardrobe": "Ivory blazer.",
        "language": LanguageChoice.ENGLISH,
        "tone": StyleChoice.LUXURY,
        "views": (),
    }
    character = _ensure_character(owner, brand, spec)
    character.default_voice_provider = voice["voice_provider"]
    character.default_voice_id = voice["voice_id"]
    character.default_voice_name = voice["voice_name"]
    character.save(update_fields=["default_voice_provider", "default_voice_id", "default_voice_name", "updated_at"])
    for ref in sarah.references.all():
        clone = CharacterReferenceImage.objects.filter(character=character, view_type=ref.view_type).first()
        if not clone:
            clone = CharacterReferenceImage(character=character, view_type=ref.view_type, sort_order=ref.sort_order)
        clone.image.name = ref.image.name
        clone.sort_order = ref.sort_order
        clone.save()
    return character


def _preference(user, character: Character) -> None:
    MerchantPreference.objects.update_or_create(
        user=user,
        defaults={
            "language": character.default_language,
            "speaking_style": character.default_tone,
            "speaker_gender": character.gender,
            "voice_name": character.default_voice_id,
        },
    )


def _ensure_project(owner, products: dict, characters: dict, spec: dict) -> VideoProject:
    product = products[spec["product"]]
    character = characters.get(spec["character"]) if spec.get("character") else None
    project = VideoProject.objects.filter(owner=owner, creative_brief__seed_key=spec["key"]).first()
    if not project:
        project = VideoProject(owner=owner, product=product)
    language = spec["language"]
    tone = spec["tone"]
    gender = character.gender if character else GenderChoice.FEMALE
    voice = resolve_voice(language, gender, _voice_id_for(spec, language, gender, character))
    status, progress, label = _stage_status(spec["stage"])
    project.product = product
    project.language = language
    project.speaking_style = tone
    project.speaker_gender = gender
    project.duration_seconds = spec["duration"]
    project.status = status
    project.progress = progress
    project.stage_label = label
    project.error_message = ""
    project.google_operation = ""
    project.provider_request_id = ""
    project.product_snapshot = product_snapshot(product)
    project.creative_brief = _brief(spec, product, character, voice)
    project.merchant_instructions = (
        "MISA demo seed. Database fixture only. No generation job was queued."
    )
    if spec["stage"] == "approved":
        project.approved_at = timezone.now()
        project.qa_status = QAStatus.PASSED
    elif spec.get("qa"):
        project.qa_status = QAStatus.FAILED if spec["qa"] not in {"pass", "captions_unchecked"} else QAStatus.PASSED
        if spec["qa"] == "captions_unchecked":
            project.qa_status = ""
    else:
        project.qa_status = ""
        project.approved_at = None
    project.save()
    project.scenes.all().delete()
    if spec["stage"] in {"concepts", "storyboard", "planning", "generating", "review", "approved"}:
        _write_concepts(project, spec, character)
    if spec["stage"] in {"storyboard", "planning", "generating", "review", "approved"}:
        _write_scenes(project, spec, character)
    if character and character.name != "Archived Demo Character":
        sync_project_character(
            project,
            character.pk,
            language=language,
            tone=tone,
            gender=gender,
            voice_id=voice["voice_id"],
        )
    elif character:
        _write_archived_config(project, character, language, tone, gender, voice)
    else:
        VideoCharacterConfig.objects.filter(project=project).delete()
        _legacy_presenter(project, spec)
    if spec.get("qa"):
        _write_qa(project, spec["qa"])
    else:
        project.qa_results = {}
        project.save(update_fields=["qa_results", "updated_at"])
    if spec["stage"] == "approved":
        VideoProjectVersion.objects.update_or_create(
            project=project,
            version=1,
            defaults={"note": "misa-demo seed snapshot", "snapshot": {"seed_key": spec["key"], "status": project.status}},
        )
    return project


def _brief(spec: dict, product: Product, character: Character | None, voice: dict) -> dict:
    offer = product.offer or ""
    price = f"{product.price:.2f}"
    return {
        "schema_version": 2,
        "seed_key": spec["key"],
        "seed_marker": SEED_MARKER,
        "bulk": bool(spec.get("bulk")),
        "legacy": bool(spec.get("legacy")),
        "objective": "buy",
        "customer": "Malaysian shoppers comparing a practical purchase.",
        "main_benefit": spec.get("benefit") or _product_spec(product)["benefit"],
        "original_price": price,
        "offer_price": price if offer else "",
        "offer_text": offer,
        "offer": offer,
        "price": price,
        "must_remain_exact": ["product_appearance", "product_name", "price", "presenter"],
        "must_not_show": "Invented discounts, medical claims, or a different product.",
        "language": spec["language"],
        "market": "Malaysia",
        "platform": "tiktok",
        "duration": spec["duration"],
        "location": _location(product),
        "style_key": spec.get("style_key") or "",
        "character_id": character.pk if character else None,
        "presenter": _presenter_brief(spec, character),
        "product_truth": {
            "name": product.name,
            "price": price,
            "offer": offer,
            "approved_claims": product.approved_claims,
            "prohibited_claims": product.prohibited_claims,
        },
        "voice_preference": {
            "provider": voice["voice_provider"],
            "voice_id": voice["voice_id"],
            "voice_name": voice["voice_name"],
            "role": "preference",
        },
    }


def _presenter_brief(spec: dict, character: Character | None) -> dict:
    if spec.get("legacy"):
        return {
            "ethnicity": "malay",
            "ethnicity_label": "Malay",
            "ethnicity_custom": "",
            "gender": "female" if spec["key"].endswith("1") else "male",
            "look": "Legacy presenter photograph. Not a Character record.",
            "mode": "upload",
        }
    if not character:
        return {}
    return {
        "ethnicity": "",
        "ethnicity_label": "",
        "ethnicity_custom": "",
        "gender": character.gender,
        "look": character.appearance_description,
        "mode": "upload" if character.references.exists() else "generated",
        "character_id": character.pk,
    }


def _write_concepts(project: VideoProject, spec: dict, character: Character | None) -> None:
    name = project.product.name
    titles = ("Straightforward demo", "Offer first", "Day-in-the-life")
    concepts = []
    for index, title in enumerate(titles, start=1):
        concepts.append(
            {
                "id": f"{spec['key']}-concept-{index}",
                "title": title,
                "style": spec["tone"],
                "strategy": f"{title} for {name}.",
                "hook": f"Start with {name}.",
                "narrative": project.creative_brief.get("main_benefit") or name,
                "cta": f"Buy {name} for RM{project.product.price:.2f}.",
                "template_id": "product-demo",
                "scenes": [],
            }
        )
    project.creative_directions = concepts
    project.selected_concept_id = concepts[0]["id"] if spec["stage"] != "concepts" else ""
    project.save(update_fields=["creative_directions", "selected_concept_id", "updated_at"])


def _write_scenes(project: VideoProject, spec: dict, character: Character | None) -> None:
    count = max(4, min(8, int(spec["duration"]) // 8))
    each = round(spec["duration"] / count, 2)
    shots = [
        ("Wide product reveal", "Walks toward the product", "slow push-in", "wide", True),
        ("Medium presenter shot", "Touches the product controls", "tracking", "medium", True),
        ("Product close-up", "", "locked", "close-up", True),
        ("Feature demonstration", "Points to the main feature", "slow pan", "medium close-up", False),
        ("Lifestyle beat", "Stands beside the product", "handheld", "medium", True),
        ("Detail insert", "", "macro push-in", "macro", False),
        ("Offer card", "Holds the product toward camera", "static", "medium", True),
        ("Product, presenter, and CTA", "Looks to camera and asks for the purchase", "gentle push-in", "wide", True),
    ]
    chosen = list(shots[: count - 1]) + [shots[-1]]
    orders = list(range(1, count + 1))
    if spec.get("reorder") and count >= 3:
        orders[1], orders[2] = orders[2], orders[1]
    cursor = 0.0
    price = f"{project.product.price:.2f}"
    incomplete = spec.get("qa") == "incomplete_cta"
    for index, shot in enumerate(chosen):
        title, action, movement, framing, captioned = shot
        is_last = index == len(chosen) - 1
        narration = f"Meet {project.product.name}." if index == 0 else (project.creative_brief.get("main_benefit") or "")
        if is_last and not incomplete:
            narration = f"Buy {project.product.name} for RM{price} today."
            caption = narration
        elif is_last and incomplete:
            narration = "Learn more soon."
            caption = "Learn more soon."
        elif captioned:
            caption = project.product.name
        else:
            caption = ""
        if not action:
            caption = caption
        meta = {
            "shot_description": f"{title} of {project.product.name}.",
            "presenter_action": action,
            "camera_framing": framing,
            "camera_movement": movement,
            "lighting": "soft daylight",
            "location": _location(project.product),
            "background": _location(project.product),
            "pace": "steady",
            "transition": "cut",
            "start_time": cursor,
            "end_time": cursor + each,
            "voice_over": narration,
            "on_screen_caption": caption,
            "benefit": project.creative_brief.get("main_benefit") or "",
            "approved": bool(spec["stage"] == "approved" or (spec.get("reorder") and index in {0, count - 1})),
            "status": "approved" if spec["stage"] == "approved" else "ready",
            "seed_marker": SEED_MARKER,
        }
        if character:
            meta["character_id"] = character.pk
            meta["character_name"] = character.name
            meta["primary_character"] = True
        Scene.objects.create(
            project=project,
            scene_key=f"scene-{index + 1}",
            order=orders[index],
            title=title,
            visual=meta["shot_description"],
            narration=narration,
            caption=caption,
            duration=each,
            metadata=meta,
        )
        cursor += each


def _write_archived_config(project, character, language, tone, gender, voice) -> None:
    VideoCharacterConfig.objects.update_or_create(
        project=project,
        defaults={
            "character": character,
            "language": language,
            "tone": tone,
            "gender": gender,
            "voice_provider": voice["voice_provider"],
            "voice_id": voice["voice_id"],
            "voice_name": voice["voice_name"],
            "appearance_snapshot": character.appearance_description,
            "identity_snapshot": _identity_snapshot(character),
            "reference_snapshot": _reference_snapshot(character),
        },
    )


def _legacy_presenter(project: VideoProject, spec: dict) -> None:
    label = "LEGACY PRESENTER A" if spec["key"].endswith("1") else "LEGACY PRESENTER B"
    storage = f"misa-demo/presenters/{spec['key']}-front.png"
    _ensure_bytes(storage, _png([ "MISA TEST PRESENTER", label, "FRONT" ], (70, 90, 120)))
    asset = project.assets.filter(metadata__seed_asset=f"{spec['key']}-presenter").first()
    if not asset:
        asset = VideoAsset(project=project, kind=VideoAsset.Kind.IMAGE, prompt="presenter-reference")
    asset.metadata = {
        "seed_marker": SEED_MARKER,
        "seed_asset": f"{spec['key']}-presenter",
        "presenter_reference": True,
        "presenter_photo": True,
        "presenter_identity": True,
        "angle": "front",
    }
    asset.file.name = storage
    asset.save()


def _write_qa(project: VideoProject, kind: str) -> None:
    passed = QAStatus.PASSED
    failed = QAStatus.FAILED
    checks = [
        _check("product", passed, "The product name matches the product record."),
        _check("claims", passed, "No prohibited claims were found."),
        _check("narration", passed, "Narration text is present on the scenes."),
        _check("scene_completeness", passed, "The storyboard has the expected scenes."),
        _check(
            "character_consistency",
            "not_checked",
            "Character consistency was not compared with the reference images in this run.",
            checked=False,
            verified=False,
            qa_category="character",
        ),
        _check(
            "presenter_visual_consistency",
            "not_checked",
            "Presenter photos were not compared with a generated frame.",
            checked=False,
            verified=False,
        ),
    ]
    if kind == "pass":
        checks.extend(
            [
                _check("price", passed, "The approved price is present."),
                _check("visible_captions", passed, "Captions are present."),
                _check("audio_silent", passed, "Fixture records speech as present. No audio file was generated."),
                _check("assembled_audio", passed, "Fixture records an audio result. No file was muxed."),
                _check("product_visual_consistency", passed, "Fixture records a product visual pass. No frame comparison ran in this seed."),
                _check("caption_visual", passed, "Fixture records readable captions."),
                _check("cta_complete", passed, "The ending names the product, price, and a purchase action."),
            ]
        )
    elif kind == "price_fail":
        checks.extend(
            [
                _check("price", failed, "The spoken price does not match the approved price."),
                _check("visible_captions", passed, "Captions are present."),
                _check("audio_silent", passed, "Fixture records speech as present."),
                _check("assembled_audio", passed, "Fixture records an audio result."),
                _check("cta_complete", passed, "The ending asks for a purchase."),
            ]
        )
    elif kind == "missing_audio":
        checks.extend(
            [
                _check("price", passed, "The approved price is present."),
                _check("visible_captions", passed, "Captions are present."),
                _check("audio_silent", failed, "No audio stream was found. Approval stays blocked."),
                _check("assembled_audio", failed, "Assembled audio is missing."),
                _check("cta_complete", passed, "The ending asks for a purchase."),
            ]
        )
    elif kind == "visual_mismatch":
        checks.extend(
            [
                _check("price", passed, "The approved price is present."),
                _check("visible_captions", passed, "Captions are present."),
                _check("audio_silent", passed, "Fixture records speech as present."),
                _check("assembled_audio", passed, "Fixture records an audio result."),
                _check(
                    "product_visual_consistency",
                    failed,
                    "The product in the scene does not match the approved photograph.",
                    source="multimodal",
                    checked=True,
                    verified=False,
                ),
                _check("cta_complete", passed, "The ending asks for a purchase."),
            ]
        )
    elif kind == "caption_fail":
        checks.extend(
            [
                _check("price", passed, "The approved price is present."),
                _check("visible_captions", failed, "A caption is missing or unreadable."),
                _check("caption_visual", failed, "Caption text failed the visual check.", source="OCR", checked=True),
                _check("audio_silent", passed, "Fixture records speech as present."),
                _check("assembled_audio", passed, "Fixture records an audio result."),
                _check("cta_complete", passed, "The ending asks for a purchase."),
            ]
        )
    elif kind == "incomplete_cta":
        checks.extend(
            [
                _check("price", passed, "The approved price is on the product record."),
                _check("visible_captions", passed, "A caption is present, but it is not a complete offer."),
                _check("audio_silent", passed, "Fixture records speech as present."),
                _check("assembled_audio", passed, "Fixture records an audio result."),
                _check("cta_complete", failed, "The ending CTA is missing the product name, approved price, or a purchase action."),
            ]
        )
    elif kind == "captions_unchecked":
        checks.extend(
            [
                _check("price", passed, "The approved price is present."),
                _check("audio_silent", passed, "Fixture records speech as present."),
                _check("assembled_audio", passed, "Fixture records an audio result."),
                _check("cta_complete", passed, "The ending asks for a purchase."),
            ]
        )
    elif kind == "expired_offer":
        checks.extend(
            [
                _check("price", passed, "The monthly price is present."),
                _check("expired_offer", failed, "The approved offer has expired. Remove or update it before publishing."),
                _check("visible_captions", passed, "Captions are present."),
                _check("audio_silent", passed, "Fixture records speech as present."),
                _check("assembled_audio", passed, "Fixture records an audio result."),
                _check("cta_complete", passed, "The ending asks for a purchase."),
            ]
        )
    blocking = release_blocking_issues(checks, has_preview=False)
    status = QAStatus.FAILED if any(item.get("status") == QAStatus.FAILED for item in checks) else QAStatus.PASSED
    project.qa_results = {
        "status": status,
        "summary": "MISA demo seed QA fixture. These checks were not produced by Omni or a visual model.",
        "checks": checks,
        "release_blocking": blocking,
        "layers": {},
        "disclaimer": "Seed fixture only. Character consistency was not compared with a generated frame.",
    }
    project.qa_status = status
    project.save(update_fields=["qa_results", "qa_status", "updated_at"])


def _ensure_styles(owner) -> None:
    source = VideoProject.objects.filter(owner=owner, creative_brief__seed_key="misa-test-story-lamp").first()
    for key, name, description in STYLES:
        recipe, _created = StyleRecipe.objects.update_or_create(
            owner=owner,
            key=key,
            defaults={
                "name": name,
                "source_project": source,
                "recipe": {
                    "seed_marker": SEED_MARKER,
                    "description": description,
                    "language": LanguageChoice.ENGLISH,
                    "speaking_style": StyleChoice.LUXURY if "premium" in key or "technology" in key else StyleChoice.WARM,
                    "speaker_gender": GenderChoice.FEMALE,
                    "duration_seconds": 30,
                    "location": "Malaysian home interior",
                    "lighting": "soft daylight",
                    "style_title": name,
                    "must_remain_exact": ["product_appearance", "product_name", "price"],
                    "objective": "buy",
                    "platform": "tiktok",
                    "presenter": {},
                    "scene_blueprint": [
                        {
                            "order": 1,
                            "title": "Product open",
                            "scene_role": "hook",
                            "duration": 8,
                            "camera_framing": "wide",
                            "camera_movement": "slow push-in",
                            "location": "Malaysian home interior",
                            "presenter_action": "Enter and reveal the product.",
                        },
                        {
                            "order": 2,
                            "title": "Product detail",
                            "scene_role": "detail",
                            "duration": 8,
                            "camera_framing": "close-up",
                            "camera_movement": "locked",
                            "presenter_action": "",
                        },
                        {
                            "order": 3,
                            "title": "Offer close",
                            "scene_role": "hero_cta",
                            "duration": 8,
                            "camera_framing": "medium",
                            "camera_movement": "static",
                            "presenter_action": "Invite the purchase.",
                        },
                    ],
                },
            },
        )
        storage = f"misa-demo/styles/{key}.png"
        _ensure_bytes(storage, _png(["MISA TEST STYLE", name], (40, 70, 90)))
        if source:
            asset = source.assets.filter(metadata__seed_asset=key).first()
            if not asset:
                asset = VideoAsset(project=source, kind=VideoAsset.Kind.IMAGE, prompt="style-reference")
            asset.metadata = {"seed_marker": SEED_MARKER, "seed_asset": key, "style_reference": True, "style_key": recipe.key}
            asset.file.name = storage
            asset.save()


def _stage_status(stage: str) -> tuple[str, int, str]:
    if stage == "planning":
        return VideoProjectStatus.PLANNING, 36, "MISA test fixture — planning. No job is queued."
    if stage == "generating":
        return VideoProjectStatus.GENERATING_VIDEO, 62, "MISA test fixture — not a live render."
    if stage == "review":
        return VideoProjectStatus.READY_FOR_REVIEW, 100, "Ready for review"
    if stage == "approved":
        return VideoProjectStatus.APPROVED, 100, "Approved"
    return VideoProjectStatus.DRAFT, 0, "Draft"


def _check(name: str, status: str, detail: str, **extra) -> dict:
    row = {
        "name": name,
        "status": status,
        "detail": detail,
        "checked": status not in {"not_checked", "skipped"},
        "verified": False,
    }
    row.update(extra)
    return row


def _voice_id_for(spec: dict, language: str, gender: str, character: Character | None) -> str:
    if not spec.get("override"):
        return ""
    primary = resolve_voice(language, gender)["voice_id"]
    if character and primary == character.default_voice_id:
        return _alternate_voice(language, gender)
    return primary


def _alternate_voice(language: str, gender: str) -> str:
    """Another real catalog id for this language, when one exists."""
    primary = resolve_voice(language, gender)["voice_id"]
    other_gender = GenderChoice.MALE if gender != GenderChoice.MALE else GenderChoice.FEMALE
    try:
        other = resolve_voice(language, gender, resolve_voice(language, other_gender)["voice_id"])
    except Exception:
        return primary
    return other["voice_id"]


def _ensure_character_image(character: Character, key: str, view: str, order: int) -> None:
    storage = f"misa-demo/characters/misa-test-character-{key}-{view}.png"
    _ensure_bytes(
        storage,
        _png(["MISA TEST CHARACTER", character.name.upper(), view.upper()], (30, 70, 110)),
    )
    ref = CharacterReferenceImage.objects.filter(character=character, view_type=view).first()
    if not ref:
        ref = CharacterReferenceImage(character=character, view_type=view if view in CharacterView.values else CharacterView.OTHER)
    ref.sort_order = order
    ref.image.name = storage
    ref.save()


def _ensure_product_image(product: Product, slug: str, label: str, order: int) -> None:
    storage = f"misa-demo/products/misa-test-product-{slug}-{label}.jpg"
    _ensure_bytes(storage, _png(["MISA TEST PRODUCT", product.name, label.upper()], (90, 60, 40), kind="JPEG"))
    existing = ProductImage.objects.filter(product=product, image=storage).first()
    if existing:
        return
    image = ProductImage(product=product)
    image.image.name = storage
    image.save()
    del order


def _ensure_bytes(storage: str, payload: bytes) -> None:
    path = settings.MEDIA_ROOT / storage
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(payload)


def _png(lines: list[str], color: tuple[int, int, int], kind: str = "PNG") -> bytes:
    image = Image.new("RGB", (640, 800), color)
    draw = ImageDraw.Draw(image)
    font = _font(36)
    y = 220
    for line in lines:
        draw.text((40, y), line[:42], fill=(255, 255, 255), font=font)
        y += 64
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG" if kind == "JPEG" else "PNG")
    return buffer.getvalue()


def _font(size: int):
    for path in ("C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _location(product: Product) -> str:
    name = product.name.lower()
    if "coffee" in name or "fryer" in name or "blender" in name:
        return "Modern kitchen"
    if "chair" in name or "lamp" in name:
        return "Home office"
    if "skincare" in name:
        return "Bright bathroom"
    if "backpack" in name:
        return "Apartment hallway"
    if "restaurant" in name or "hotel" in name:
        return "Reception counter"
    return "Clean studio table"


def _product_spec(product: Product) -> dict:
    slug = product.product_url.rstrip("/").split("/")[-1]
    for item in PRODUCTS:
        if item["slug"] == slug:
            return item
    return {"benefit": product.description[:120]}


def _brand(email: str, name: str) -> Brand | None:
    return Brand.objects.filter(owner__email=email, name=name).first()
