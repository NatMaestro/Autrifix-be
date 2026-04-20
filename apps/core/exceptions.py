import logging

from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is not None:
        if response.status_code >= 500:
            logger.exception("API 5xx: %s", exc, extra={"context": context})
        return response
    logger.exception("Unhandled exception: %s", exc, extra={"context": context})
    from rest_framework.response import Response
    from rest_framework import status

    return Response(
        {"detail": "An unexpected error occurred."},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
