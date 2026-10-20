from django.contrib import admin

from .models import AgentProfile


@admin.register(AgentProfile)
class AgentProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("user__username", "user__email", "user__name")
