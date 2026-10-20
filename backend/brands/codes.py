from django.apps import apps
from django.utils.crypto import get_random_string


def public_code_exists(code: str) -> bool:
    from brands.models import ProductShareLink

    if ProductShareLink.objects.filter(code=code).exists():
        return True
    if apps.is_installed("commerce"):
        TrackingLink = apps.get_model("commerce", "TrackingLink")
        return TrackingLink.objects.filter(code=code).exists()
    return False


def allocate_public_code(length: int = 10) -> str:
    while True:
        code = get_random_string(length)
        if not public_code_exists(code):
            return code
