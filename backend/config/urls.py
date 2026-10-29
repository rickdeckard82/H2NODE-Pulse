from django.urls import path
from drf_spectacular.views import SpectacularAPIView

from core.views import LiveView, ReadyView

urlpatterns = [
    path("api/v1/health/live/", LiveView.as_view()),
    path("api/v1/health/ready/", ReadyView.as_view()),
    path("api/v1/schema/", SpectacularAPIView.as_view()),
]
