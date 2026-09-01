from django.urls import path

from apps.accounts.views import (
    GoogleAuthView,
    HealthView,
    LoginView,
    LogoutView,
    MeView,
    RefreshTokenAliasView,
    RegisterView,
    SendOTPView,
    TokenObtainPairAliasView,
    TokenRefreshLegacyView,
    VerifyMyPhoneView,
    VerifyOTPView,
)
from apps.ai.views import DiagnosticsView, IssueRouteView, MatchingPreviewView
from apps.chat.views import ChatMessageCreateView, ChatRoomDetailView, ChatRoomListView
from apps.customers.views import CustomerProfileDetailView, VehicleDetailView, VehicleListCreateView
from apps.jobs.views import (
    JobAcceptView,
    JobDetailView,
    JobQuoteListCreateView,
    JobListView,
    QuoteRespondView,
    NearbyOpenRequestsView,
    RequestCreateView,
    ServiceCategoryListView,
    ServiceRequestCancelView,
    ServiceRequestDetailView,
    ServiceRequestListCreateView,
    ServicesNearbyView,
)
from apps.administration.views import (
    AdminJobListView,
    AdminStatsView,
    AdminUserListView,
    AdminVerificationListView,
    AdminVerificationReviewView,
)
from apps.providers.agency_views import (
    AgencyCreateView,
    AgencyDetailView,
    AgencyMemberDetailView,
    AgencyMemberListCreateView,
    MembershipRespondView,
    MyMembershipListView,
)
from apps.providers.views import (
    ProviderProfileDetailView,
    ProviderServiceOfferingDetailView,
    ProviderServiceOfferingListCreateView,
    ProviderVerificationView,
)
from apps.notifications.views import (
    NotificationListView,
    NotificationMarkReadView,
    NotificationUnreadCountView,
)
from apps.reviews.views import ReviewListCreateView

urlpatterns = [
    # Administration — SPEC-012. Gated on `IsAdmin`, which existed but was applied to
    # nothing until now.
    path("admin/stats/", AdminStatsView.as_view(), name="admin-stats"),
    path("admin/users/", AdminUserListView.as_view(), name="admin-users"),
    path("admin/jobs/", AdminJobListView.as_view(), name="admin-jobs"),
    path(
        "admin/verifications/",
        AdminVerificationListView.as_view(),
        name="admin-verifications",
    ),
    path(
        "admin/verifications/<uuid:id>/review/",
        AdminVerificationReviewView.as_view(),
        name="admin-verification-review",
    ),
    path("health/", HealthView.as_view(), name="health"),
    path("auth/send-otp/", SendOTPView.as_view(), name="auth-send-otp"),
    path("auth/verify-otp/", VerifyOTPView.as_view(), name="auth-verify-otp"),
    path("auth/register/", RegisterView.as_view(), name="register"),
    path("auth/google/", GoogleAuthView.as_view(), name="auth-google"),
    path("auth/login/", LoginView.as_view(), name="login"),
    path("auth/logout/", LogoutView.as_view(), name="logout"),
    path("auth/token/", TokenObtainPairAliasView.as_view(), name="token_obtain_pair"),
    path("auth/token/refresh/", TokenRefreshLegacyView.as_view(), name="token_refresh"),
    path("auth/refresh-token/", RefreshTokenAliasView.as_view(), name="refresh-token"),
    path("me/", MeView.as_view(), name="me"),
    path("me/verify-phone/", VerifyMyPhoneView.as_view(), name="me-verify-phone"),
    path("services/nearby/", ServicesNearbyView.as_view(), name="services-nearby"),
    path("requests/create/", RequestCreateView.as_view(), name="request-create"),
    # Drivers
    path("customers/profile/", CustomerProfileDetailView.as_view(), name="customer-profile"),
    path("customers/vehicles/", VehicleListCreateView.as_view(), name="vehicle-list"),
    path("customers/vehicles/<uuid:id>/", VehicleDetailView.as_view(), name="vehicle-detail"),
    # Mechanics
    # Agencies — SPEC-017. `memberships/` sits outside `agencies/` because an invitee is
    # not yet a member, so their invitation cannot live behind an agency-scoped lookup.
    path("providers/agencies/", AgencyCreateView.as_view(), name="agency-create"),
    path("providers/agencies/<uuid:id>/", AgencyDetailView.as_view(), name="agency-detail"),
    path(
        "providers/agencies/<uuid:id>/members/",
        AgencyMemberListCreateView.as_view(),
        name="agency-members",
    ),
    path(
        "providers/agencies/<uuid:id>/members/<uuid:membership_id>/",
        AgencyMemberDetailView.as_view(),
        name="agency-member-detail",
    ),
    path("providers/memberships/", MyMembershipListView.as_view(), name="my-memberships"),
    path(
        "providers/memberships/<uuid:id>/respond/",
        MembershipRespondView.as_view(),
        name="membership-respond",
    ),
    path("providers/profile/", ProviderProfileDetailView.as_view(), name="provider-profile"),
    path(
        "providers/verification/",
        ProviderVerificationView.as_view(),
        name="provider-verification",
    ),
    path("providers/services/", ProviderServiceOfferingListCreateView.as_view(), name="provider-services"),
    path("providers/services/<uuid:id>/", ProviderServiceOfferingDetailView.as_view(), name="provider-service-detail"),
    # Jobs — specific paths before ``jobs/`` list
    path("jobs/categories/", ServiceCategoryListView.as_view(), name="service-categories"),
    path("jobs/requests/", ServiceRequestListCreateView.as_view(), name="service-requests"),
    path("jobs/requests/<uuid:id>/", ServiceRequestDetailView.as_view(), name="service-request-detail"),
    path(
        "jobs/requests/nearby/",
        NearbyOpenRequestsView.as_view(),
        name="service-requests-nearby",
    ),
    path(
        "jobs/requests/<uuid:id>/cancel/",
        ServiceRequestCancelView.as_view(),
        name="service-request-cancel",
    ),
    path("jobs/requests/<uuid:request_id>/accept/", JobAcceptView.as_view(), name="job-accept"),
    path(
        "jobs/<uuid:job_id>/quotes/",
        JobQuoteListCreateView.as_view(),
        name="job-quotes",
    ),
    path(
        "jobs/<uuid:job_id>/quotes/<uuid:quote_id>/respond/",
        QuoteRespondView.as_view(),
        name="job-quote-respond",
    ),
    path("jobs/<uuid:id>/", JobDetailView.as_view(), name="job-detail"),
    path("jobs/", JobListView.as_view(), name="job-list"),
    # Reviews
    path("reviews/", ReviewListCreateView.as_view(), name="reviews"),
    # Notifications
    path("notifications/", NotificationListView.as_view(), name="notifications"),
    path(
        "notifications/unread-count/",
        NotificationUnreadCountView.as_view(),
        name="notification-unread-count",
    ),
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
