"""WebSocket consumer behavior — SPEC-009 §15, SPEC-006 REQ-5, SPEC-010 REQ-6.

These were the largest untested surface after the first remediation slice: three consumers
covered only indirectly through their REST siblings.

Async consumers are driven from synchronous tests via ``drive()`` rather than adding
``pytest-asyncio``. ``transaction=True`` is required because the consumers reach the database
from worker threads, which cannot see pytest-django's usual wrapping transaction.
"""

import asyncio

import pytest
from channels.testing import WebsocketCommunicator
from rest_framework_simplejwt.tokens import RefreshToken

from apps.chat.models import ChatMessage
from apps.providers.models import ProviderProfile
from autrifix.asgi import application
from tests.conftest import ACCRA_LAT, ACCRA_LNG, FAR_LAT, FAR_LNG

pytestmark = pytest.mark.django_db(transaction=True)

CONNECT_TIMEOUT = 5


def drive(coro):
    """Run a coroutine to completion from a synchronous test."""
    return asyncio.run(coro)


def token_for(user) -> str:
    return str(RefreshToken.for_user(user).access_token)


async def open_socket(path: str, token: str | None = None):
    """Connect and return ``(communicator, connected)``. Caller must disconnect.

    ``token`` must be minted in the synchronous part of the test: ``RefreshToken.for_user``
    touches the database, which Django forbids from an async context.
    """
    url = f"{path}?token={token}" if token else path
    communicator = WebsocketCommunicator(application, url)
    connected, _subprotocol = await communicator.connect(timeout=CONNECT_TIMEOUT)
    return communicator, connected


@pytest.fixture
def customer_user_token(customer_user):
    return token_for(customer_user)


@pytest.fixture
def other_customer_user_token(other_customer_user):
    return token_for(other_customer_user)


@pytest.fixture
def provider_user_token(provider_user):
    return token_for(provider_user)


# --- chat: ws/jobs/<job_id>/chat/ --------------------------------------------------


def test_participant_can_connect_to_job_chat(customer_user, job, customer_user_token):
    async def scenario():
        comm, connected = await open_socket(f"/ws/jobs/{job.id}/chat/", customer_user_token)
        await comm.disconnect()
        return connected

    assert drive(scenario()) is True


def test_assigned_provider_can_connect_to_job_chat(provider_user, job, provider_user_token):
    async def scenario():
        comm, connected = await open_socket(f"/ws/jobs/{job.id}/chat/", provider_user_token)
        await comm.disconnect()
        return connected

    assert drive(scenario()) is True


def test_non_participant_is_rejected_from_job_chat(other_customer_user, job, other_customer_user_token):
    """The WebSocket equivalent of SPEC-009 CONFLICT-009-A."""

    async def scenario():
        comm, connected = await open_socket(f"/ws/jobs/{job.id}/chat/", other_customer_user_token)
        await comm.disconnect()
        return connected

    assert drive(scenario()) is False


def test_anonymous_is_rejected_from_job_chat(job):
    async def scenario():
        comm, connected = await open_socket(f"/ws/jobs/{job.id}/chat/")
        await comm.disconnect()
        return connected

    assert drive(scenario()) is False


def test_invalid_token_is_rejected_from_job_chat(job):
    async def scenario():
        comm = WebsocketCommunicator(application, f"/ws/jobs/{job.id}/chat/?token=not-a-jwt")
        connected, _ = await comm.connect(timeout=CONNECT_TIMEOUT)
        await comm.disconnect()
        return connected

    assert drive(scenario()) is False


def test_unknown_job_is_rejected(customer_user, customer_user_token):
    import uuid

    async def scenario():
        comm, connected = await open_socket(f"/ws/jobs/{uuid.uuid4()}/chat/", customer_user_token)
        await comm.disconnect()
        return connected

    assert drive(scenario()) is False


def test_message_sent_over_socket_is_persisted_and_broadcast(customer_user, provider_user, job, customer_user_token, provider_user_token):
    async def scenario():
        customer, _ = await open_socket(f"/ws/jobs/{job.id}/chat/", customer_user_token)
        provider, _ = await open_socket(f"/ws/jobs/{job.id}/chat/", provider_user_token)

        await customer.send_json_to({"body": "I am by the petrol station"})
        received = await provider.receive_json_from(timeout=CONNECT_TIMEOUT)

        await customer.disconnect()
        await provider.disconnect()
        return received

    frame = drive(scenario())

    # Same envelope the REST path publishes (SPEC-009 §10).
    assert frame["kind"] == "chat.message"
    assert frame["data"]["body"] == "I am by the petrol station"
    assert frame["data"]["sender"] == str(customer_user.id)

    message = ChatMessage.objects.get()
    assert message.body == "I am by the petrol station"
    assert message.sender_id == customer_user.id


def test_blank_body_returns_an_error_frame_and_persists_nothing(customer_user, job, customer_user_token):
    async def scenario():
        comm, _ = await open_socket(f"/ws/jobs/{job.id}/chat/", customer_user_token)
        await comm.send_json_to({"body": "   "})
        frame = await comm.receive_json_from(timeout=CONNECT_TIMEOUT)
        await comm.disconnect()
        return frame

    frame = drive(scenario())
    assert frame["kind"] == "error"
    assert not ChatMessage.objects.exists()


def test_oversized_body_is_rejected(customer_user, job, customer_user_token):
    async def scenario():
        comm, _ = await open_socket(f"/ws/jobs/{job.id}/chat/", customer_user_token)
        await comm.send_json_to({"body": "x" * 4001})
        frame = await comm.receive_json_from(timeout=CONNECT_TIMEOUT)
        await comm.disconnect()
        return frame

    assert drive(scenario())["kind"] == "error"
    assert not ChatMessage.objects.exists()


def test_typing_frames_fan_out_without_persisting(customer_user, provider_user, job, customer_user_token, provider_user_token):
    async def scenario():
        customer, _ = await open_socket(f"/ws/jobs/{job.id}/chat/", customer_user_token)
        provider, _ = await open_socket(f"/ws/jobs/{job.id}/chat/", provider_user_token)

        await customer.send_json_to({"kind": "typing", "is_typing": True})
        frame = await provider.receive_json_from(timeout=CONNECT_TIMEOUT)

        await customer.disconnect()
        await provider.disconnect()
        return frame

    frame = drive(scenario())
    assert frame["kind"] == "typing"
    assert frame["is_typing"] is True
    assert frame["sender"] == str(customer_user.id)
    assert not ChatMessage.objects.exists()


# --- presence: ws/providers/nearby/ ------------------------------------------------


def test_customer_can_subscribe_and_receives_a_snapshot(customer_user, provider_profile, customer_user_token):
    async def scenario():
        comm, connected = await open_socket("/ws/providers/nearby/", customer_user_token)
        await comm.send_json_to(
            {"kind": "subscribe", "lat": ACCRA_LAT, "lng": ACCRA_LNG, "radius_km": 25}
        )
        frame = await comm.receive_json_from(timeout=CONNECT_TIMEOUT)
        await comm.disconnect()
        return connected, frame

    connected, frame = drive(scenario())
    assert connected is True
    assert frame["kind"] == "snapshot"
    assert frame["nearby_providers_count"] == 1
    assert frame["providers"][0]["business_name"] == "Kofi Auto Works"


def test_provider_is_rejected_from_presence_socket(provider_user, provider_user_token):
    async def scenario():
        comm, connected = await open_socket("/ws/providers/nearby/", provider_user_token)
        await comm.disconnect()
        return connected

    assert drive(scenario()) is False


def test_anonymous_is_rejected_from_presence_socket():
    async def scenario():
        comm, connected = await open_socket("/ws/providers/nearby/")
        await comm.disconnect()
        return connected

    assert drive(scenario()) is False


def test_subscribe_rejects_out_of_range_coordinates(customer_user, customer_user_token):
    async def scenario():
        comm, _ = await open_socket("/ws/providers/nearby/", customer_user_token)
        await comm.send_json_to({"kind": "subscribe", "lat": 999, "lng": 0})
        frame = await comm.receive_json_from(timeout=CONNECT_TIMEOUT)
        await comm.disconnect()
        return frame

    assert drive(scenario())["kind"] == "error"


def test_subscribe_requires_numeric_coordinates(customer_user, customer_user_token):
    async def scenario():
        comm, _ = await open_socket("/ws/providers/nearby/", customer_user_token)
        await comm.send_json_to({"kind": "subscribe", "lat": "here"})
        frame = await comm.receive_json_from(timeout=CONNECT_TIMEOUT)
        await comm.disconnect()
        return frame

    assert drive(scenario())["kind"] == "error"


def test_nearby_provider_update_reaches_a_subscribed_customer(customer_user, provider_profile, customer_user_token):
    """The provider is at the subscriber's own coordinate, so the update must arrive."""

    async def scenario():
        from channels.db import database_sync_to_async

        comm, _ = await open_socket("/ws/providers/nearby/", customer_user_token)
        await comm.send_json_to(
            {"kind": "subscribe", "lat": ACCRA_LAT, "lng": ACCRA_LNG, "radius_km": 25}
        )
        await comm.receive_json_from(timeout=CONNECT_TIMEOUT)  # snapshot

        @database_sync_to_async
        def touch_profile():
            profile = ProviderProfile.objects.get(pk=provider_profile.pk)
            profile.bio = "Now open late"
            profile.save()

        await touch_profile()
        frame = await comm.receive_json_from(timeout=CONNECT_TIMEOUT)
        await comm.disconnect()
        return frame

    frame = drive(scenario())
    assert frame["kind"] == "provider_update"
    assert frame["provider"]["id"] == str(provider_profile.id)
    assert frame["provider"]["distance_km"] == 0.0


def test_distant_provider_update_is_filtered_out(customer_user, provider_user, make_provider_profile, customer_user_token):
    """SECGAP-008-3: updates used to be broadcast platform-wide with no radius filter."""

    async def scenario():
        from channels.db import database_sync_to_async

        @database_sync_to_async
        def create_far_mechanic():
            return make_provider_profile(provider_user, lat=FAR_LAT, lng=FAR_LNG)

        far = await create_far_mechanic()

        comm, _ = await open_socket("/ws/providers/nearby/", customer_user_token)
        await comm.send_json_to(
            {"kind": "subscribe", "lat": ACCRA_LAT, "lng": ACCRA_LNG, "radius_km": 25}
        )
        snapshot = await comm.receive_json_from(timeout=CONNECT_TIMEOUT)

        @database_sync_to_async
        def touch_profile():
            profile = ProviderProfile.objects.get(pk=far.pk)
            profile.bio = "Still far away"
            profile.save()

        await touch_profile()
        leaked = await comm.receive_nothing(timeout=1)
        await comm.disconnect()
        return snapshot, leaked

    snapshot, nothing_received = drive(scenario())
    assert snapshot["nearby_providers_count"] == 0
    assert nothing_received is True


# --- notifications: ws/notifications/ ----------------------------------------------


def test_authenticated_user_can_open_notification_socket(customer_user, customer_user_token):
    async def scenario():
        comm, connected = await open_socket("/ws/notifications/", customer_user_token)
        await comm.disconnect()
        return connected

    assert drive(scenario()) is True


def test_anonymous_is_rejected_from_notification_socket():
    async def scenario():
        comm, connected = await open_socket("/ws/notifications/")
        await comm.disconnect()
        return connected

    assert drive(scenario()) is False


def test_notification_is_delivered_to_its_owner(customer_user, customer_user_token):
    from apps.notifications.models import NotificationKind

    async def scenario():
        from channels.db import database_sync_to_async

        from apps.notifications.services import notify

        comm, _ = await open_socket("/ws/notifications/", customer_user_token)

        @database_sync_to_async
        def produce():
            notify(customer_user, kind=NotificationKind.JOB_COMPLETED, title="Job completed")

        await produce()
        frame = await comm.receive_json_from(timeout=CONNECT_TIMEOUT)
        await comm.disconnect()
        return frame

    frame = drive(scenario())
    assert frame["kind"] == "notification"
    assert frame["data"]["kind"] == NotificationKind.JOB_COMPLETED
    assert frame["data"]["read_at"] is None


def test_notification_does_not_leak_to_another_user(customer_user, other_customer_user, other_customer_user_token):
    """The group name is derived from the authenticated user, never from client input."""
    from apps.notifications.models import NotificationKind

    async def scenario():
        from channels.db import database_sync_to_async

        from apps.notifications.services import notify

        comm, _ = await open_socket("/ws/notifications/", other_customer_user_token)

        @database_sync_to_async
        def produce():
            notify(customer_user, kind=NotificationKind.JOB_ACTIVE, title="Started")

        await produce()
        nothing = await comm.receive_nothing(timeout=1)
        await comm.disconnect()
        return nothing

    assert drive(scenario()) is True
