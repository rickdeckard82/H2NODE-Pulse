from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView
from rest_framework.routers import SimpleRouter

from core import identity_views as identity
from core.chat_events import ChatEventsView
from core.chat_settings import ChatSettingsView
from core.company_settings import CompanySettingsView
from core.smtp_settings import SmtpSettingsView
from core.views import LiveView, ReadyView
from tickets import reports
from tickets import views as tickets
from tickets.attachments import AttachmentView, DownloadView
from tickets.audit_log import AuditLogView
from tickets.notification_views import (
    InboxClearView,
    InboxView,
    IntegrationTestView,
    NotificationDiagnosticsView,
    NotificationRetryView,
)
from tickets.retention import RetentionSettingsView
from wiki import views as wiki

router = SimpleRouter()
router.register("users", identity.UserViewSet, basename="users")
router.register("departments", identity.DepartmentViewSet, basename="departments")
router.register("groups", identity.GroupViewSet, basename="groups")
router.register("memberships", identity.MembershipViewSet, basename="memberships")
router.register("settings/domains", identity.DomainViewSet, basename="domains")
router.register("tickets", tickets.TicketViewSet, basename="tickets")
router.register("categories", tickets.CategoryViewSet, basename="categories")
router.register("settings/reopen-policies", tickets.ReopenPolicyViewSet, basename="reopen-policies")
router.register("settings/sla-policies", reports.SlaPolicyViewSet, basename="sla-policies")

urlpatterns = [
    path("api/v1/integrations/google-chat/events/", ChatEventsView.as_view()),
    path("api/v1/wiki/", wiki.PageListView.as_view()),
    path("api/v1/wiki/<uuid:page_id>/", wiki.PageView.as_view()),
    path("api/v1/settings/chat/", ChatSettingsView.as_view()),
    path("api/v1/settings/company/", CompanySettingsView.as_view()),
    path("api/v1/settings/audit/", AuditLogView.as_view()),
    path("api/v1/settings/retention/", RetentionSettingsView.as_view()),
    path("api/v1/settings/smtp/", SmtpSettingsView.as_view()),
    path("api/v1/settings/notifications/", NotificationDiagnosticsView.as_view()),
    path("api/v1/notifications/", InboxView.as_view()),
    path("api/v1/notifications/clear/", InboxClearView.as_view()),
    path("api/v1/settings/notifications/test/", IntegrationTestView.as_view()),
    path(
        "api/v1/settings/notifications/<int:delivery_id>/retry/",
        NotificationRetryView.as_view(),
    ),
    path("api/v1/tickets/<uuid:ticket_id>/attachments/", AttachmentView.as_view()),
    path(
        "api/v1/tickets/<uuid:ticket_id>/attachments/<uuid:attachment_id>/download/",
        DownloadView.as_view(),
    ),
    path("api/v1/reports/summary/", reports.SummaryView.as_view()),
    path("api/v1/reports/exports/", reports.ExportView.as_view()),
    path("api/v1/reports/exports/<uuid:export_id>/", reports.ExportDownloadView.as_view()),
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
    path("api/v1/auth/forget-device/", identity.SessionActionView.as_view(action="forget_device")),
    path("api/v1/auth/revoke/", identity.SessionActionView.as_view(action="revoke")),
    path("api/v1/auth/password/", identity.PasswordChangeView.as_view()),
    path("api/v1/auth/mfa/enable/", identity.MfaEnableView.as_view()),
    path("api/v1/auth/mfa/enable/confirm/", identity.MfaEnableConfirmView.as_view()),
    path("api/v1/auth/mfa/disable/", identity.MfaDisableView.as_view()),
    path("api/v1/auth/mfa/verify/", identity.MfaVerifyView.as_view()),
    path("api/v1/auth/mfa/replace/", identity.MfaReplaceView.as_view()),
    path("api/v1/auth/mfa/replace/confirm/", identity.MfaReplaceConfirmView.as_view()),
    path("api/v1/health/live/", LiveView.as_view()),
    path("api/v1/health/ready/", ReadyView.as_view()),
    path("api/v1/schema/", SpectacularAPIView.as_view()),
]
