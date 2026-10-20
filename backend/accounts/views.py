from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.permissions import IsSuperuser
from brands.models import Brand

from .serializers import UserSerializer


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)


class WorkspaceBrandListView(APIView):
    permission_classes = [IsSuperuser]

    def get(self, request):
        brands = Brand.objects.select_related("owner", "category").order_by("name")
        return Response(
            [
                {
                    "id": brand.id,
                    "name": brand.name,
                    "location": brand.location,
                    "category_name": brand.category.name if brand.category_id else "",
                    "owner_id": brand.owner_id,
                    "owner_name": brand.owner.name or brand.owner.username,
                    "owner_email": brand.owner.email,
                    "owner_username": brand.owner.username,
                }
                for brand in brands
            ]
        )


class WorkspaceAgentListView(APIView):
    permission_classes = [IsSuperuser]

    def get(self, request):
        agents = (
            User.objects.filter(role=User.Role.AGENT, is_active=True, is_superuser=False)
            .order_by("name", "username")
        )
        return Response(
            [
                {
                    "id": agent.id,
                    "name": agent.name or agent.username,
                    "username": agent.username,
                    "email": agent.email,
                    "mobile": agent.mobile,
                    "location": agent.location,
                }
                for agent in agents
            ]
        )
