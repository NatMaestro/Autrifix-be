"""
PostgreSQL configuration — Neon (serverless) or local Docker.

Prefer ``DATABASE_URL`` (copy from Neon dashboard; includes ``sslmode=require``).
If unset, ``POSTGRES_*`` variables are used (local / CI).
"""
from __future__ import annotations

from environ import Env

from .base import env


def get_databases(*, conn_max_age: int = 0, connect_timeout: int = 10) -> dict:
    """Return Django ``DATABASES`` dict."""
    database_url = env("DATABASE_URL", default=None)
    if database_url:
        cfg = Env.db_url_config(database_url)
    else:
        cfg = {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("POSTGRES_DB", default="autrifix"),
            "USER": env("POSTGRES_USER", default="autrifix"),
            "PASSWORD": env("POSTGRES_PASSWORD", default="autrifix"),
            "HOST": env("POSTGRES_HOST", default="localhost"),
            "PORT": env("POSTGRES_PORT", default="5432"),
        }

    host = (cfg.get("HOST") or "").lower()
    opts = cfg.setdefault("OPTIONS", {})
    if ".neon.tech" in host or ".neon.build" in host:
        opts.setdefault("sslmode", "require")

    if connect_timeout is not None:
        opts.setdefault(
            "connect_timeout",
            env.int("POSTGRES_CONNECT_TIMEOUT", default=connect_timeout),
        )

    cfg["CONN_MAX_AGE"] = env.int("POSTGRES_CONN_MAX_AGE", default=conn_max_age)

    return {"default": cfg}
