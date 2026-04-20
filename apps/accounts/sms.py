"""SMS delivery for OTP codes with pluggable providers."""

from __future__ import annotations

import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings

logger = logging.getLogger(__name__)


def _send_console(phone_e164: str, body: str) -> None:
    logger.warning("SMS [%s] %s", phone_e164, body)


def _send_twilio(phone_e164: str, body: str) -> None:
    sid = getattr(settings, "TWILIO_ACCOUNT_SID", None)
    token = getattr(settings, "TWILIO_AUTH_TOKEN", None)
    from_num = getattr(settings, "TWILIO_FROM_NUMBER", None)
    if not all([sid, token, from_num]):
        logger.error("Twilio not configured; SMS not sent.")
        raise RuntimeError("Twilio SMS provider is not configured")
    try:
        from twilio.rest import Client  # type: ignore[import-untyped]

        Client(sid, token).messages.create(to=phone_e164, from_=from_num, body=body)
    except ImportError as exc:
        raise RuntimeError("Install twilio package for SMS_PROVIDER=twilio") from exc


def _send_termii(phone_e164: str, body: str) -> None:
    api_key = getattr(settings, "TERMII_API_KEY", None)
    sender_id = getattr(settings, "TERMII_SENDER_ID", None)
    channel = getattr(settings, "TERMII_CHANNEL", "generic")
    sms_type = getattr(settings, "TERMII_SMS_TYPE", "plain")
    if not api_key or not sender_id:
        logger.error("Termii not configured; SMS not sent.")
        raise RuntimeError("Termii SMS provider is not configured")

    payload = {
        "api_key": api_key,
        "to": phone_e164.lstrip("+"),
        "from": sender_id,
        "sms": body,
        "type": sms_type,
        "channel": channel,
    }
    req = Request(
        "https://api.ng.termii.com/api/sms/send",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            if resp.status >= 400:
                logger.error("Termii SMS failed (%s): %s", resp.status, raw)
                raise RuntimeError("Termii SMS request failed")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        logger.error("Termii HTTP error (%s): %s", exc.code, detail)
        raise RuntimeError("Termii SMS request failed") from exc
    except URLError as exc:
        logger.error("Termii network error: %s", exc)
        raise RuntimeError("Could not reach Termii SMS service") from exc


def send_otp_sms(phone_e164: str, code: str) -> None:
    """
    Send OTP via SMS.
    Supported providers via ``SMS_PROVIDER``: ``console``, ``twilio``, ``termii``.
    Default ``console`` logs the message (and always logs at WARNING in DEBUG).
    """
    body = f"Your AutriFix code is {code}. Valid for 5 minutes. Do not share this code."
    provider = getattr(settings, "SMS_PROVIDER", "console").lower()

    if provider == "console":
        _send_console(phone_e164, body)
        return

    if settings.DEBUG:
        _send_console(phone_e164, body)

    if provider == "twilio":
        _send_twilio(phone_e164, body)
        return
    if provider == "termii":
        try:
            _send_termii(phone_e164, body)
        except RuntimeError:
            # Dev fallback: keep OTP flow testable even when Termii onboarding/config is incomplete.
            if settings.DEBUG:
                logger.warning("Termii failed in DEBUG; falling back to console OTP delivery.")
                _send_console(phone_e164, body)
                return
            raise
        return

    raise RuntimeError(f"Unsupported SMS provider: {provider}")
