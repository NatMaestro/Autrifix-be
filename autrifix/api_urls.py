from django.urls import path

from apps.accounts.views import (
    HealthView,
    LoginView,
    LogoutView,
    MeView,
    RefreshTokenAliasView,
    RegisterView,
    SendOTPView,
    TokenObtainPairAliasView,
    TokenRefreshLegacyView,
    VerifyOTPView,
)
from apps.ai.views import DiagnosticsView, IssueRouteView, MatchingPreviewView
from apps.chat.views import ChatMessageCreateView, ChatRoomDetailView, ChatRoomListView
from apps.drivers.views import DriverProfileDetailView, VehicleDetailView, VehicleListCreateView
from apps.jobs.views import (
    JobAcceptView,
    JobDetailView,
    JobListView,
    NearbyOpenRequestsView,
    RequestCreateView,
    ServiceCategoryListView,
    ServiceRequestDetailView,
    ServiceRequestListCreateView,
    ServicesNearbyView,
)
from apps.mechanics.views import (
    MechanicProfileDetailView,
    MechanicServiceOfferingDetailView,
    MechanicServiceOfferingListCreateView,
)
from apps.notifications.views import NotificationListView, NotificationMarkReadView
from apps.reviews.views import ReviewListCreateView

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("auth/send-otp/", SendOTPView.as_view(), name="auth-send-otp"),
    path("auth/verify-otp/", VerifyOTPView.as_view(), name="auth-verify-otp"),
    path("auth/register/", RegisterView.as_view(), name="register"),
    path("auth/login/", LoginView.as_view(), name="login"),
    path("auth/logout/", LogoutView.as_view(), name="logout"),
    path("auth/token/", TokenObtainPairAliasView.as_view(), name="token_obtain_pair"),
    path("auth/token/refresh/", TokenRefreshLegacyView.as_view(), name="token_refresh"),
    path("auth/refresh-token/", RefreshTokenAliasView.as_view(), name="refresh-token"),
    path("me/", MeView.as_view(), name="me"),
    path("services/nearby/", ServicesNearbyView.as_view(), name="services-nearby"),
    path("requests/create/", RequestCreateView.as_view(), name="request-create"),
    # Drivers
    path("drivers/profile/", DriverProfileDetailView.as_view(), name="driver-profile"),
    path("drivers/vehicles/", VehicleListCreateView.as_view(), name="vehicle-list"),
    path("drivers/vehicles/<uuid:id>/", VehicleDetailView.as_view(), name="vehicle-detail"),
    # Mechanics
    path("mechanics/profile/", MechanicProfileDetailView.as_view(), name="mechanic-profile"),
    path("mechanics/services/", MechanicServiceOfferingListCreateView.as_view(), name="mechanic-services"),
    path("mechanics/services/<uuid:id>/", MechanicServiceOfferingDetailView.as_view(), name="mechanic-service-detail"),
    # Jobs — specific paths before ``jobs/`` list
    path("jobs/categories/", ServiceCategoryListView.as_view(), name="service-categories"),
    path("jobs/requests/", ServiceRequestListCreateView.as_view(), name="service-requests"),
    path("jobs/requests/<uuid:id>/", ServiceRequestDetailView.as_view(), name="service-request-detail"),
    path(
        "jobs/requests/nearby/",
        NearbyOpenRequestsView.as_view(),
        name="service-requests-nearby",
    ),
    path("jobs/requests/<uuid:request_id>/accept/", JobAcceptView.as_view(), name="job-accept"),
    path("jobs/<uuid:id>/", JobDetailView.as_view(), name="job-detail"),
    path("jobs/", JobListView.as_view(), name="job-list"),
    # Reviews
    path("reviews/", ReviewListCreateView.as_view(), name="reviews"),
    # Notifications
    path("notifications/", NotificationListView.as_view(), name="notifications"),
    path("notifications/<uuid:pk>/read/", NotificationMarkReadView.as_view(), name="notification-read"),
    # Chat — ``chat/jobs/...`` before ``chat/``
    path("chat/jobs/<uuid:job_id>/", ChatRoomDetailView.as_view(), name="chat-room"),
    path("chat/jobs/<uuid:job_id>/messages/", ChatMessageCreateView.as_view(), name="chat-messages"),
    path("chat/", ChatRoomListView.as_view(), name="chat-list"),
    # AI
    path("ai/diagnostics/", DiagnosticsView.as_view(), name="ai-diagnostics"),
    path("ai/matching/preview/", MatchingPreviewView.as_view(), name="ai-matching-preview"),
    path("ai/route-issue/", IssueRouteView.as_view(), name="ai-route-issue"),
]
