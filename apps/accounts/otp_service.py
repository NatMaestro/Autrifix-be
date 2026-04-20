"""Issue / verify phone OTP using ``PhoneOTP`` (hashed at rest)."""

from __future__ import annotations

import secrets

from django.conf import settings

from apps.accounts.models import PhoneOTP


def otp_ttl_seconds() -> int:
    return int(getattr(settings, "OTP_TTL_SECONDS", 300))


def issue_otp(phone: str) -> str:
    code = f"{secrets.randbelow(900000) + 100000:06d}"
    PhoneOTP.issue(phone, code, ttl_seconds=otp_ttl_seconds())
    return code


def verify_otp(phone: str, code: str) -> bool:
    return PhoneOTP.verify_and_consume(phone, code)
