from rest_framework.permissions import BasePermission

from .models import User


class IsAgent(BasePermission):
    message = "This area is for agents only."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and (user.can_choose_account or user.role == User.Role.AGENT)
        )


class IsActiveAgent(IsAgent):
    message = "This agent account is suspended."

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        user = request.user
        if user.can_choose_account:
            return True
        profile = getattr(user, "agent_profile", None)
        if profile is None:
            return True
        return profile.status != "suspended"


class IsBrandOwner(BasePermission):
    message = "This area is for brand owners only."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and (user.can_choose_account or user.role == User.Role.PRODUCER)
        )


class IsSuperuser(BasePermission):
    message = "This area is for administrators only."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_superuser)


class IsBrandOwnerOrAdmin(BasePermission):
    message = "This area is for brand owners or administrators."

    def has_permission(self, request, view):
        return IsBrandOwner().has_permission(request, view) or IsSuperuser().has_permission(
            request, view
        )
