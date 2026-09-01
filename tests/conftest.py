"""Shared fixtures.

Coordinates used throughout are around Accra (5.60, -0.19), matching the platform's
Ghana-first phone normalization.
"""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User, UserRole
from apps.chat.models import ChatRoom
from apps.customers.models import CustomerProfile, Vehicle
from apps.jobs.models import Job, JobStatus, ServiceCategory, ServiceRequest, ServiceRequestStatus
from apps.providers.models import ProviderProfile

ACCRA_LAT = 5.6037
ACCRA_LNG = -0.1870
# ~1.1 km north of the base point.
NEARBY_LAT = 5.6137
NEARBY_LNG = -0.1870
# Kumasi — ~200 km away.
FAR_LAT = 6.6885
FAR_LNG = -1.6244


@pytest.fixture(autouse=True)
def clear_throttle_cache():
    """Throttle counters live in the cache, which outlives a test.

    Without this, one test's login attempts count against the next test's budget and the
    suite fails differently depending on execution order.
    """
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api():
    return APIClient()


def _auth(client, user):
    from rest_framework_simplejwt.tokens import RefreshToken

    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


@pytest.fixture
def as_user():
    """Return an APIClient authenticated as the given user.

    A **fresh client per call**, deliberately. It used to re-authenticate one shared
    instance, which meant holding two references — `customer = as_user(a)` and
    `provider = as_user(b)` — silently gave you the same client authed as whoever was passed
    last. Every existing test happened to call this inline and so never noticed; the first
    test that bound both up front spent its time debugging a 403 that had nothing to do with
    the code under test.
    """

    def _inner(user):
        return _auth(APIClient(), user)

    return _inner


@pytest.fixture
def make_user(db):
    counter = {"n": 0}

    def _inner(role=UserRole.CUSTOMER, **kwargs):
        counter["n"] += 1
        n = counter["n"]
        defaults = {
            "phone": f"+2335400000{n:02d}",
            "email": f"user{n}@example.com",
            "role": role,
        }
        defaults.update(kwargs)
        user = User(**defaults)
        user.set_password("TestPass123!")
        user.save()
        return user

    return _inner


@pytest.fixture
def customer_user(make_user):
    return make_user(UserRole.CUSTOMER)


@pytest.fixture
def other_customer_user(make_user):
    return make_user(UserRole.CUSTOMER)


@pytest.fixture
def provider_user(make_user):
    return make_user(UserRole.PROVIDER)


@pytest.fixture
def other_provider_user(make_user):
    return make_user(UserRole.PROVIDER)


@pytest.fixture
def customer_profile(customer_user):
    return CustomerProfile.objects.create(user=customer_user, display_name="Ama K.")


@pytest.fixture
def other_customer_profile(other_customer_user):
    return CustomerProfile.objects.create(user=other_customer_user, display_name="Kojo B.")


@pytest.fixture
def make_provider_profile(db):
    def _inner(user, *, available=True, lat=ACCRA_LAT, lng=ACCRA_LNG, name=None, verified=True):
        """Verified by default: most scenarios need a provider who can actually work.

        Since SPEC-013 REQ-3, accepting a job requires ``PROVIDER_MIN_ACCEPT_LEVEL``. Pass
        ``verified=False`` for tests about the unverified experience.
        """
        from apps.providers.verification import VerificationLevel

        return ProviderProfile.objects.create(
            user=user,
            business_name=name or f"Workshop {user.pk.hex[:6]}",
            base_latitude=lat,
            base_longitude=lng,
            is_available=available,
            verification_level=(
                VerificationLevel.DOCUMENTS if verified else VerificationLevel.NONE
            ),
        )

    return _inner


@pytest.fixture
def provider_profile(provider_user, make_provider_profile):
    """A verified, working provider — exact locations unlocked and able to accept."""
    return make_provider_profile(provider_user, name="Kofi Auto Works")


#: Alias kept for tests that want the entitlement stated explicitly at the call site.
@pytest.fixture
def verified_provider_profile(provider_profile):
    return provider_profile


@pytest.fixture
def unverified_provider_profile(provider_user, make_provider_profile):
    """A provider at level ``none``: may browse (coarsened) but may not accept."""
    return make_provider_profile(provider_user, name="Kofi Auto Works", verified=False)


@pytest.fixture
def other_provider_profile(other_provider_user, make_provider_profile):
    return make_provider_profile(other_provider_user, name="Yaa Motors")


@pytest.fixture
def category(db):
    """Seeded by migration jobs/0002; fall back to creating one for safety."""
    existing = ServiceCategory.objects.filter(slug="battery-electrical").first()
    if existing:
        return existing
    return ServiceCategory.objects.create(
        name="Auto Electrical (Battery / Starter)",
        slug="battery-electrical",
        is_active=True,
    )


@pytest.fixture
def vehicle(customer_profile):
    return Vehicle.objects.create(
        customer=customer_profile, make="Toyota", model="Corolla", year=2014, color="Silver"
    )


@pytest.fixture
def make_service_request(db, category):
    def _inner(customer, *, lat=ACCRA_LAT, lng=ACCRA_LNG, status=ServiceRequestStatus.OPEN, **kwargs):
        return ServiceRequest.objects.create(
            customer=customer,
            category=kwargs.pop("category", category),
            description=kwargs.pop("description", "Car will not start"),
            latitude=lat,
            longitude=lng,
            status=status,
            **kwargs,
        )

    return _inner


@pytest.fixture
def service_request(customer_profile, make_service_request):
    return make_service_request(customer_profile)


@pytest.fixture
def make_job(db):
    def _inner(service_request, provider, *, status=JobStatus.PENDING_ACCEPT):
        job = Job.objects.create(
            service_request=service_request, provider=provider, status=status
        )
        ChatRoom.objects.get_or_create(job=job)
        return job

    return _inner


@pytest.fixture
def job(service_request, provider_profile, make_job):
    """A pending job, with its request already moved to ``matching``."""
    service_request.status = ServiceRequestStatus.MATCHING
    service_request.save(update_fields=["status"])
    return make_job(service_request, provider_profile)


@pytest.fixture
def completed_job(job):
    """A job the customer has confirmed, with the amount that was agreed.

    Completion carries money now (SPEC-015): a completed job without a ``final_amount``
    is not a state the application can reach, so the fixture does not pretend otherwise.
    """
    from decimal import Decimal

    from django.utils import timezone

    from apps.jobs.models import ServiceRequestStatus as SRS

    job.status = JobStatus.COMPLETED
    job.final_amount = Decimal("250.00")
    job.currency = "GHS"
    job.work_finished_at = timezone.now()
    job.completed_at = timezone.now()
    job.save(
        update_fields=[
            "status",
            "final_amount",
            "currency",
            "work_finished_at",
            "completed_at",
        ]
    )
    job.service_request.status = SRS.COMPLETED
    job.service_request.save(update_fields=["status"])
    return job


@pytest.fixture
def awaiting_confirmation_job(job):
    """Work finished, amount recorded, customer has not yet agreed."""
    from decimal import Decimal

    from django.utils import timezone

    from apps.jobs.models import ServiceRequestStatus as SRS

    job.status = JobStatus.AWAITING_CONFIRMATION
    job.accepted_at = timezone.now()
    job.work_finished_at = timezone.now()
    job.final_amount = Decimal("250.00")
    job.currency = "GHS"
    job.save(
        update_fields=[
            "status",
            "accepted_at",
            "work_finished_at",
            "final_amount",
            "currency",
        ]
    )
    job.service_request.status = SRS.ASSIGNED
    job.service_request.save(update_fields=["status"])
    return job
