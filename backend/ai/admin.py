from django.contrib import admin

from .models import (
    BulkGeneration,
    BulkGenerationItem,
    Character,
    CharacterMasterReference,
    CharacterReferenceImage,
    MerchantPreference,
    Scene,
    SocialPost,
    StyleRecipe,
    UsageRecord,
    VideoAsset,
    VideoCharacterConfig,
    VideoProject,
    VideoProjectVersion,
)


@admin.register(MerchantPreference)
class MerchantPreferenceAdmin(admin.ModelAdmin):
    list_display = ("user", "language", "speaking_style", "updated_at")
    search_fields = ("user__username", "user__email")


class SceneInline(admin.TabularInline):
    model = Scene
    extra = 0


@admin.register(VideoProject)
class VideoProjectAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "owner", "status", "qa_status", "version", "created_at")
    list_filter = ("status", "qa_status", "language")
    search_fields = ("product__name", "owner__username")
    inlines = [SceneInline]


@admin.register(Scene)
class SceneAdmin(admin.ModelAdmin):
    list_display = ("id", "project", "scene_key", "order", "title")
    search_fields = ("scene_key", "title", "project__product__name")
    list_filter = ("order",)


@admin.register(VideoAsset)
class VideoAssetAdmin(admin.ModelAdmin):
    list_display = ("id", "project", "kind", "created_at")
    list_filter = ("kind",)
    search_fields = ("project__product__name",)


@admin.register(VideoProjectVersion)
class VideoProjectVersionAdmin(admin.ModelAdmin):
    list_display = ("project", "version", "note", "created_at")


@admin.register(UsageRecord)
class UsageRecordAdmin(admin.ModelAdmin):
    list_display = ("owner", "provider", "operation", "status", "created_at")
    list_filter = ("provider", "status")
    search_fields = ("owner__username", "operation")


@admin.register(SocialPost)
class SocialPostAdmin(admin.ModelAdmin):
    list_display = ("project", "platform", "status", "authorized", "created_at")
    list_filter = ("platform", "status")


@admin.register(StyleRecipe)
class StyleRecipeAdmin(admin.ModelAdmin):
    list_display = ("key", "name", "owner", "updated_at")
    search_fields = ("key", "name", "owner__username")


class CharacterReferenceInline(admin.TabularInline):
    model = CharacterReferenceImage
    extra = 0


class CharacterMasterInline(admin.TabularInline):
    model = CharacterMasterReference
    extra = 0


@admin.register(Character)
class CharacterAdmin(admin.ModelAdmin):
    list_display = ("name", "brand", "owner", "gender", "master_reference_status", "master_reference_version", "status", "updated_at")
    list_filter = ("status", "gender", "master_reference_status")
    search_fields = ("name", "owner__username", "brand__name")
    inlines = [CharacterReferenceInline, CharacterMasterInline]


@admin.register(VideoCharacterConfig)
class VideoCharacterConfigAdmin(admin.ModelAdmin):
    list_display = ("project", "character", "language", "tone", "gender")


class BulkItemInline(admin.TabularInline):
    model = BulkGenerationItem
    extra = 0


@admin.register(BulkGeneration)
class BulkGenerationAdmin(admin.ModelAdmin):
    list_display = ("id", "mode", "product", "owner", "status", "requested_count", "created_at")
    list_filter = ("mode", "status")
    search_fields = ("title", "product__name", "owner__username")
    inlines = [BulkItemInline]


@admin.register(BulkGenerationItem)
class BulkGenerationItemAdmin(admin.ModelAdmin):
    list_display = ("id", "bulk", "sequence", "title", "status", "video_project")
    list_filter = ("status",)

