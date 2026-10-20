from django.apps import AppConfig
from django.core.exceptions import ImproperlyConfigured


class AiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ai"
    verbose_name = "AI studio"

    def ready(self) -> None:
        from django.conf import settings

        value = str(getattr(settings, "VIDEO_PROVIDER", "omni") or "omni").strip().lower()
        if value not in {"omni", "veo", "minimax", "seedance"}:
            raise ImproperlyConfigured(
                f"VIDEO_PROVIDER={value!r} is not supported. Use omni, veo, minimax, or seedance."
            )
