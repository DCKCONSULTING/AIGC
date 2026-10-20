from django.urls import path

from .views import LogoutView, MeView, WorkspaceAgentListView, WorkspaceBrandListView

urlpatterns = [
    path("logout/", LogoutView.as_view(), name="logout"),
    path("me/", MeView.as_view(), name="me"),
    path("workspaces/brands/", WorkspaceBrandListView.as_view(), name="workspace-brands"),
    path("workspaces/agents/", WorkspaceAgentListView.as_view(), name="workspace-agents"),
]
