from __future__ import annotations

from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.authentication import JWTAuthentication


@database_sync_to_async
def _get_user_from_token(raw_token: str):
    jwt_auth = JWTAuthentication()
    validated = jwt_auth.get_validated_token(raw_token)
    return jwt_auth.get_user(validated)


class JwtQueryAuthMiddleware:
    """
    Authenticate websocket users via `?token=<jwt>` query param.

    Browser WebSocket API can't set arbitrary Authorization headers, so this
    middleware reads JWT from the query string and populates `scope["user"]`.
    """

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        try:
            query = parse_qs(scope.get("query_string", b"").decode("utf-8"))
            token = (query.get("token") or [None])[0]
            if token:
                scope["user"] = await _get_user_from_token(token)
            else:
                scope["user"] = AnonymousUser()
        except Exception:
            scope["user"] = AnonymousUser()
        return await self.inner(scope, receive, send)


def JwtQueryAuthMiddlewareStack(inner):
    return JwtQueryAuthMiddleware(inner)

