from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .models import User

_SKIP_PREFIXES = (
    "/api/auth/me/",
    "/api/auth/logout/",
    "/api/auth/workspaces/",
)


def acting_brand_id(request):
    raw = request.headers.get("X-Acting-Brand")
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


class TokenActingAuthentication(TokenAuthentication):
    """Let a superuser act as a chosen brand owner or agent for API calls."""

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, token = result
        path = request.path if request.path.endswith("/") else f"{request.path}/"
        if path.startswith(_SKIP_PREFIXES) or not user.is_superuser:
            return result
        acting_id = request.headers.get("X-Acting-User")
        if not acting_id:
            return result
        try:
            target_id = int(acting_id)
        except (TypeError, ValueError) as exc:
            raise AuthenticationFailed("That account is not available.") from exc
        target = User.objects.filter(pk=target_id, is_active=True).first()
        if target is None or target.is_superuser:
            raise AuthenticationFailed("That account is not available.")
        brand_id = request.headers.get("X-Acting-Brand")
        if brand_id:
            from brands.models import Brand

            try:
                brand_pk = int(brand_id)
            except (TypeError, ValueError) as exc:
                raise AuthenticationFailed("That company is not available.") from exc
            if not Brand.objects.filter(pk=brand_pk, owner=target).exists():
                raise AuthenticationFailed("That company is not available.")
        request.impersonator = user
        return (target, token)
