"""Chat authorization — SPEC-009 CONFLICT-009-A.

Before the fix, ``GET /chat/jobs/{job_id}/`` and ``POST .../messages/`` used an
unfiltered queryset: any authenticated user holding a job id could read a private
conversation or inject a message into it.
"""

import pytest
from django.urls import reverse

from apps.chat.models import ChatMessage

pytestmark = pytest.mark.django_db


def room_url(job):
    return reverse("chat-room", kwargs={"job_id": job.id})


def messages_url(job):
    return reverse("chat-messages", kwargs={"job_id": job.id})


# --- participants -----------------------------------------------------------------


def test_customer_can_read_own_room(as_user, customer_user, job):
    response = as_user(customer_user).get(room_url(job))
    assert response.status_code == 200
    assert response.data["job"] == job.id


def test_assigned_provider_can_read_room(as_user, provider_user, job):
    assert as_user(provider_user).get(room_url(job)).status_code == 200


def test_customer_can_post_message(as_user, customer_user, job):
    response = as_user(customer_user).post(messages_url(job), {"body": "I'm by the petrol station"}, format="json")
    assert response.status_code == 201
    message = ChatMessage.objects.get()
    assert message.sender_id == customer_user.id
    assert message.room.job_id == job.id


# --- non-participants -------------------------------------------------------------


def test_unrelated_customer_cannot_read_room(as_user, other_customer_user, job):
    assert as_user(other_customer_user).get(room_url(job)).status_code == 404


def test_unrelated_provider_cannot_read_room(as_user, other_provider_user, other_provider_profile, job):
    assert as_user(other_provider_user).get(room_url(job)).status_code == 404


def test_unrelated_customer_cannot_post_message(as_user, other_customer_user, job):
    response = as_user(other_customer_user).post(messages_url(job), {"body": "hello"}, format="json")
    assert response.status_code == 404
    assert not ChatMessage.objects.exists()


def test_unrelated_provider_cannot_post_message(
    as_user, other_provider_user, other_provider_profile, job
):
    response = as_user(other_provider_user).post(messages_url(job), {"body": "hi"}, format="json")
    assert response.status_code == 404
    assert not ChatMessage.objects.exists()


def test_anonymous_cannot_read_room(api, job):
    assert api.get(room_url(job)).status_code == 401


def test_chat_list_only_returns_own_rooms(as_user, other_customer_user, job):
    response = as_user(other_customer_user).get(reverse("chat-list"))
    assert response.status_code == 200
    assert response.data["count"] == 0


def test_chat_list_returns_participant_room_with_last_message(as_user, customer_user, job):
    ChatMessage.objects.create(room=job.chat_room, sender=customer_user, body="On my way?")
    response = as_user(customer_user).get(reverse("chat-list"))
    assert response.data["count"] == 1
    row = response.data["results"][0]
    assert row["last_message"] == "On my way?"
    assert row["contact_name"] == "Kofi Auto Works"
    assert row["job_status"] == job.status


def test_provider_sees_customer_display_name_as_contact(as_user, provider_user, job):
    row = as_user(provider_user).get(reverse("chat-list")).data["results"][0]
    assert row["contact_name"] == "Ama K."


# --- validation -------------------------------------------------------------------


def test_blank_message_is_rejected(as_user, customer_user, job):
    response = as_user(customer_user).post(messages_url(job), {"body": "   "}, format="json")
    assert response.status_code == 400


def test_message_for_job_without_room_is_404(as_user, customer_user, service_request, provider_profile):
    from apps.jobs.models import Job

    roomless = Job.objects.create(service_request=service_request, provider=provider_profile)
    response = as_user(customer_user).post(messages_url(roomless), {"body": "hi"}, format="json")
    assert response.status_code == 404
