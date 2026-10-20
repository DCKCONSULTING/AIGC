from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = (
        "username",
        "name",
        "email",
        "role",
        "mobile",
        "location",
        "is_staff",
    )
    list_filter = ("role", "is_staff", "is_superuser", "is_active")
    search_fields = ("username", "name", "email", "mobile", "location")
    ordering = ("username",)

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Profile", {"fields": ("name", "email", "mobile", "location", "role")}),
        (
            "Permissions",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "username",
                    "name",
                    "email",
                    "mobile",
                    "location",
                    "role",
                    "password1",
                    "password2",
                ),
            },
        ),
    )
