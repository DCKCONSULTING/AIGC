from rest_framework.authtoken.models import Token

from .serializers import UserSerializer


def auth_payload(user):
    token, _ = Token.objects.get_or_create(user=user)
    return {
        "token": token.key,
        "user": UserSerializer(user).data,
    }
