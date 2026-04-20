"""Normalize phone numbers to E.164-style (international with leading +)."""

from __future__ import annotations

import re


def normalize_phone(raw: str) -> str:
    """
    Strip spaces/dashes; ensure a single leading + and digits after.
    Ghana local numbers starting with 0 are mapped to +233 (Accra / GH rollout default).
    """
    if not raw or not str(raw).strip():
        raise ValueError("Phone number is required.")

    s = str(raw).strip()
    # Keep + only at start, digits elsewhere
    digits = re.sub(r"\D", "", s)
    if s.startswith("+"):
        return "+" + digits
    # Ghana: 0XX... -> +233...
    if digits.startswith("0") and len(digits) >= 9:
        return "+233" + digits[1:]
    if digits.startswith("233"):
        return "+" + digits
    # Assume already country code without +
    if len(digits) >= 9:
        return "+" + digits
    raise ValueError("Invalid phone number format.")
