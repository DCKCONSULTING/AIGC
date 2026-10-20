from django.contrib import admin

from .models import (
    Brand,
    Campaign,
    Category,
    JoinRequest,
    Product,
    ProductDemoVideo,
    ProductImage,
    ProductShareLink,
    Team,
    TeamInvitation,
    TeamMembership,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "owner", "status", "location", "created_at")
    search_fields = ("name", "owner__username", "owner__email", "location")
    list_filter = ("category", "status", "created_at")


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1


class ProductDemoVideoInline(admin.TabularInline):
    model = ProductDemoVideo
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "brand", "price", "commission", "commission_amount", "created_at")
    search_fields = ("name", "brand__name")
    list_filter = ("created_at",)
    inlines = [ProductImageInline, ProductDemoVideoInline]


@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "created_at")
    search_fields = ("product__name",)


@admin.register(ProductDemoVideo)
class ProductDemoVideoAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "created_at")
    search_fields = ("product__name",)


@admin.register(ProductShareLink)
class ProductShareLinkAdmin(admin.ModelAdmin):
    list_display = ("code", "product", "share_count", "open_count", "created_at")
    search_fields = ("code", "product__name")


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "brand", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("name", "brand__name")


@admin.register(TeamMembership)
class TeamMembershipAdmin(admin.ModelAdmin):
    list_display = ("agent", "team", "status", "joined_at")
    list_filter = ("status",)
    search_fields = ("agent__username", "team__name")


@admin.register(TeamInvitation)
class TeamInvitationAdmin(admin.ModelAdmin):
    list_display = ("agent", "team", "status", "invited_by", "created_at", "expires_at")
    list_filter = ("status",)
    search_fields = ("agent__username", "team__name")


@admin.register(JoinRequest)
class JoinRequestAdmin(admin.ModelAdmin):
    list_display = ("agent", "team", "status", "reviewed_by", "created_at")
    list_filter = ("status",)
    search_fields = ("agent__username", "team__name")


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ("name", "brand", "product", "team", "content", "status", "start_at", "end_at")
    list_filter = ("status",)
    search_fields = ("name", "brand__name")
