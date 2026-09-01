import logging

from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


class Conflict(APIException):
    """409 — the request is valid but conflicts with the current state of the resource.

    Used for lost races (two providers accepting one request), duplicate resources
    (a second review for the same job), and invalid state transitions.
    """

    status_code = status.HTTP_409_CONFLICT
    default_detail = "This action conflicts with the current state of the resource."
    default_code = "conflict"


class VerificationRequired(APIException):
    """403 — the actor is authenticated and correctly-rolled, but not yet entitled.

    The payload names the current and required level so a client can render the next step
    rather than a dead end: the whole point of letting unverified providers browse is that
    they can see what verification unlocks.
    """

    status_code = status.HTTP_403_FORBIDDEN
    default_code = "verification_required"

    def __init__(self, *, current_level: str, required_level: str, action: str = "accept jobs"):
        super().__init__(
            {
                "detail": f"Your account must be verified to {action}.",
                "code": self.default_code,
                "current_level": current_level,
                "required_level": required_level,
                "verification_url": "/api/v1/providers/verification/",
            }
        )


def custom_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is not None:
        if response.status_code >= 500:
            logger.exception("API 5xx: %s", exc, extra={"context": context})
        return response
    logger.exception("Unhandled exception: %s", exc, extra={"context": context})
    from rest_framework.response import Response

    return Response(
        {"detail": "An unexpected error occurred."},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
