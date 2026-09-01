"""Participant scoping for chat.

A chat room belongs to exactly two people: the customer who raised the service request and
the provider assigned to the job. Every read and write path — REST and WebSocket — must
resolve rooms through here.

Previously ``ChatRoomDetailView`` and ``ChatMessageCreateView`` used an unfiltered
queryset, so any authenticated user holding a job id could read or post into any
conversation (``specs/009-messaging.md`` CONFLICT-009-A).
"""

from __future__ import annotations

from django.db.models import Q

from apps.chat.models import ChatRoom

ROOM_SELECT_RELATED = (
    "job",
    "job__provider",
    "job__provider__user",
    "job__service_request",
    "job__service_request__customer",
    "job__service_request__customer__user",
)


def participant_rooms(user):
    """Chat rooms the user takes part in, as customer or as assigned provider."""
    if user is None or user.is_anonymous:
        return ChatRoom.objects.none()
    return (
        ChatRoom.objects.filter(
            Q(job__service_request__customer__user=user) | Q(job__provider__user=user)
        )
        .select_related(*ROOM_SELECT_RELATED)
        .distinct()
    )


def get_participant_room(user, job_id):
    """Return the room for ``job_id`` if ``user`` takes part in it, else ``None``."""
    return participant_rooms(user).filter(job_id=job_id).first()
