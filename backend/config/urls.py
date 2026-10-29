from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView
from rest_framework.routers import SimpleRouter

from core import identity_views as identity
from core.views import LiveView, ReadyView

router = SimpleRouter()
router.register("users", identity.UserViewSet, basename="users")
router.register("departments", identity.DepartmentViewSet, basename="departments")
router.register("groups", identity.GroupViewSet, basename="groups")
router.register("memberships", identity.MembershipViewSet, basename="memberships")
router.register("settings/domains", identity.DomainViewSet, basename="domains")

urlpatterns = [
    path("api/v1/", include(router.urls)),
    path("api/v1/auth/csrf/", identity.CsrfView.as_view()),
    path("api/v1/auth/register/", identity.RegisterView.as_view()),
    path("api/v1/auth/confirm/", identity.ConfirmView.as_view()),
    path("api/v1/auth/resend/", identity.ResendView.as_view()),
    path("api/v1/auth/login/", identity.LoginView.as_view()),
    path("api/v1/auth/forgot/", identity.ForgotView.as_view()),
    path("api/v1/auth/reset/", identity.ResetView.as_view()),
    path("api/v1/auth/me/", identity.MeView.as_view()),
    path("api/v1/auth/logout/", identity.SessionActionView.as_view()),
    path("api/v1/auth/revoke/", identity.SessionActionView.as_view(action="revoke")),
    path("api/v1/auth/email/", identity.EmailChangeView.as_view()),
    path("api/v1/auth/confirm-email/", identity.ConfirmEmailView.as_view()),
    path("api/v1/auth/mfa/setup/", identity.MfaSetupView.as_view()),
    path("api/v1/auth/mfa/verify/", identity.MfaVerifyView.as_view()),
    path("api/v1/auth/mfa/replace/", identity.MfaReplaceView.as_view()),
    path("api/v1/auth/mfa/replace/confirm/", identity.MfaReplaceConfirmView.as_view()),
    path("api/v1/health/live/", LiveView.as_view()),
    path("api/v1/health/ready/", ReadyView.as_view()),
    path("api/v1/schema/", SpectacularAPIView.as_view()),
]
