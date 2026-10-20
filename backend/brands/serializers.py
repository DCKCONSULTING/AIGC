from accounts.authentication import acting_brand_id
from accounts.models import User
from accounts.serializers import AccountRegisterSerializer
from rest_framework import serializers

from .models import Brand, Category, Product, ProductDemoVideo, ProductImage, ProductShareLink


def primary_brand_for(user, request=None):
    brands = Brand.objects.filter(owner=user).select_related("category")
    if request is not None:
        acting = acting_brand_id(request)
        if acting:
            brand = brands.filter(pk=acting).first()
            if brand is not None:
                return brand
    return brands.order_by("created_at", "id").first()


def normalize_website(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    return serializers.URLField().run_validation(value)


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ("id", "name", "slug")
        read_only_fields = fields


class BrandSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    website = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = Brand
        fields = (
            "id",
            "category",
            "category_name",
            "name",
            "website",
            "description",
            "location",
            "created_at",
        )
        read_only_fields = ("id", "category_name", "created_at")
        extra_kwargs = {"category": {"required": True, "allow_null": False}}

    def validate_category(self, category: Category) -> Category:
        if category is None:
            raise serializers.ValidationError("Select a category.")
        return category

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError("Enter a brand or company name.")
        return value

    def validate_website(self, value: str) -> str:
        return normalize_website(value or "")


def parse_json_list(value):
    if value in (None, "", []):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            import json

            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                raise serializers.ValidationError("Enter a valid list.") from exc
            return parse_json_list(parsed)
        return [part.strip() for part in text.split(",") if part.strip()]
    raise serializers.ValidationError("Enter a valid list.")


class ProductImageSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = ProductImage
        fields = ("id", "url")
        read_only_fields = fields

    def get_url(self, obj: ProductImage) -> str:
        if not obj.image:
            return ""
        return obj.image.url


class ProductDemoVideoSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = ProductDemoVideo
        fields = ("id", "url")
        read_only_fields = fields

    def get_url(self, obj: ProductDemoVideo) -> str:
        if not obj.video:
            return ""
        return obj.video.url


class ProductSerializer(serializers.ModelSerializer):
    brand_name = serializers.CharField(source="brand.name", read_only=True)
    category = serializers.IntegerField(source="brand.category_id", read_only=True)
    category_name = serializers.CharField(source="brand.category.name", read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)
    demo_videos = ProductDemoVideoSerializer(many=True, read_only=True)
    photos = serializers.ListField(
        child=serializers.ImageField(),
        write_only=True,
        required=False,
    )
    videos = serializers.ListField(
        child=serializers.FileField(),
        write_only=True,
        required=False,
    )
    variants = serializers.JSONField(required=False)
    approved_claims = serializers.JSONField(required=False)
    prohibited_claims = serializers.JSONField(required=False)
    certifications = serializers.JSONField(required=False)
    evidence = serializers.JSONField(required=False)
    known_mistakes = serializers.JSONField(required=False)
    prohibited_representations = serializers.JSONField(required=False)
    share_count = serializers.SerializerMethodField()
    open_count = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = (
            "id",
            "brand",
            "brand_name",
            "category",
            "category_name",
            "name",
            "description",
            "product_url",
            "price",
            "commission",
            "commission_amount",
            "variants",
            "dimensions",
            "materials",
            "offer",
            "offer_expiry",
            "approved_claims",
            "prohibited_claims",
            "certifications",
            "evidence",
            "shipping_conditions",
            "known_mistakes",
            "prohibited_representations",
            "images",
            "demo_videos",
            "photos",
            "videos",
            "share_count",
            "open_count",
            "created_at",
        )
        read_only_fields = (
            "id",
            "brand_name",
            "category",
            "category_name",
            "images",
            "demo_videos",
            "share_count",
            "open_count",
            "created_at",
        )

    def validate_brand(self, brand: Brand) -> Brand:
        request = self.context.get("request")
        if request and brand.owner_id != request.user.id:
            raise serializers.ValidationError("Choose one of your brands.")
        return brand

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError("Enter a product name.")
        return value

    def validate_product_url(self, value: str) -> str:
        return normalize_website(value or "")

    def validate_price(self, value):
        if value is None or value < 0:
            raise serializers.ValidationError("Enter a valid product price.")
        return value

    def validate_commission(self, value):
        if value is None or value < 0 or value > 100:
            raise serializers.ValidationError("Commission must be between 0 and 100.")
        return value

    def validate_commission_amount(self, value):
        if value is None or value < 0:
            raise serializers.ValidationError("Fixed commission must be zero or greater.")
        return value

    def validate_variants(self, value):
        return parse_json_list(value)

    def validate_approved_claims(self, value):
        return parse_json_list(value)

    def validate_prohibited_claims(self, value):
        return parse_json_list(value)

    def validate_certifications(self, value):
        return parse_json_list(value)

    def validate_evidence(self, value):
        return parse_json_list(value)

    def validate_known_mistakes(self, value):
        return parse_json_list(value)

    def validate_prohibited_representations(self, value):
        return parse_json_list(value)

    def validate_offer_expiry(self, value):
        if value in ("", None):
            return None
        return value

    def get_share_count(self, obj: Product) -> int:
        try:
            return obj.share_link.share_count
        except ProductShareLink.DoesNotExist:
            return 0

    def get_open_count(self, obj: Product) -> int:
        try:
            return obj.share_link.open_count
        except ProductShareLink.DoesNotExist:
            return 0

    def _collect_files(self, validated_data, field, upload_name):
        files = list(validated_data.pop(field, []) or [])
        request = self.context.get("request")
        if not files and request is not None:
            files = request.FILES.getlist(upload_name)
        return files

    def create(self, validated_data):
        photos = self._collect_files(validated_data, "photos", "photos")
        videos = self._collect_files(validated_data, "videos", "videos")
        product = Product.objects.create(**validated_data)
        for photo in photos:
            ProductImage.objects.create(product=product, image=photo)
        for video in videos:
            ProductDemoVideo.objects.create(product=product, video=video)
        return product

    def update(self, instance, validated_data):
        photos = self._collect_files(validated_data, "photos", "photos")
        videos = self._collect_files(validated_data, "videos", "videos")
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        for photo in photos:
            ProductImage.objects.create(product=instance, image=photo)
        for video in videos:
            ProductDemoVideo.objects.create(product=instance, video=video)
        return instance


class BrandRegisterSerializer(AccountRegisterSerializer):
    role = User.Role.PRODUCER
    company_name = serializers.CharField()
    company_website = serializers.CharField(required=False, allow_blank=True)
    company_description = serializers.CharField()

    class Meta(AccountRegisterSerializer.Meta):
        fields = AccountRegisterSerializer.Meta.fields + (
            "company_name",
            "company_website",
            "company_description",
        )

    def validate_company_name(self, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError("Enter your company name.")
        return value

    def validate_company_website(self, value: str) -> str:
        return normalize_website(value or "")

    def validate_company_description(self, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise serializers.ValidationError(
                "Tell us a bit more about what your company sells."
            )
        return value

    def create(self, validated_data):
        company_name = validated_data.pop("company_name")
        company_website = validated_data.pop("company_website", "")
        company_description = validated_data.pop("company_description")
        user = super().create(validated_data)
        category = Category.objects.order_by("id").first()
        Brand.objects.create(
            owner=user,
            category=category,
            name=company_name,
            website=company_website,
            description=company_description,
            location=user.location,
        )
        return user


class BrandOwnerSerializer(serializers.ModelSerializer):
    brands = BrandSerializer(many=True, read_only=True)
    company = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "name",
            "email",
            "mobile",
            "location",
            "role",
            "company",
            "brands",
        )
        read_only_fields = fields

    def get_company(self, user):
        brand = primary_brand_for(user, self.context.get("request"))
        if brand is None:
            return None
        return BrandSerializer(brand).data
