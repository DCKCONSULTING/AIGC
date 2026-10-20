from django.urls import path

from commerce.views import ConversionIngestView, PlatformAnalyticsView, ShareConfirmedView

urlpatterns = [
    path("conversions/", ConversionIngestView.as_view(), name="commerce-conversions"),
    path("analytics/", PlatformAnalyticsView.as_view(), name="commerce-analytics"),
    path("share-confirmed/", ShareConfirmedView.as_view(), name="commerce-share-confirmed"),
]
