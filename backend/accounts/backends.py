from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class EmailOrUsernameBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        identifier = username or kwargs.get("email")
        if not identifier or password is None:
            return None

        users = User.objects.filter(
            Q(username__iexact=identifier) | Q(email__iexact=identifier)
        )
        user = users.first()
        if user is None:
            User().set_password(password)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
