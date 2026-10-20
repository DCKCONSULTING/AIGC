from accounts.models import User
from accounts.permissions import IsActiveAgent, IsAgent
from accounts.serializers import LoginSerializer
from accounts.services import auth_payload
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AgentProfile
from .serializers import AgentMeUpdateSerializer, AgentProfileSerializer, AgentRegisterSerializer


class AgentRegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = AgentRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(auth_payload(user), status=status.HTTP_201_CREATED)


class AgentLoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(
            data=request.data,
            context={"request": request, "expected_role": User.Role.AGENT},
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        profile = getattr(user, "agent_profile", None)
        if profile is not None and profile.status == AgentProfile.Status.SUSPENDED:
            return Response(
                {"detail": "This agent account is suspended."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(auth_payload(user))


class AgentMeView(APIView):
    def get_permissions(self):
        if self.request.method == "PATCH":
            return [IsActiveAgent()]
        return [IsAgent()]

    def get(self, request):
        profile, _ = AgentProfile.objects.get_or_create(user=request.user)
        return Response(AgentProfileSerializer(profile).data)

    def patch(self, request):
        profile, _ = AgentProfile.objects.get_or_create(user=request.user)
        serializer = AgentMeUpdateSerializer(
            request.user,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        profile.refresh_from_db()
        return Response(AgentProfileSerializer(profile).data)
