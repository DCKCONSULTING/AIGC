from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from brands.views import ProductShareRedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/agents/", include("agents.urls")),
    path("api/brands/", include("brands.urls")),
    path("api/ai/", include("ai.urls")),
    path("api/commerce/", include("commerce.urls")),
    path("s/<str:code>/", ProductShareRedirectView.as_view(), name="product-share-redirect"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
