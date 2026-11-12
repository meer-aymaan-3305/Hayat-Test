"""Readable enquiry reference numbers.

A visitor or coordinator needs something short they can read out, not a UUID. The
reference is built from the day the chat started and five digits taken from the
conversation id, so it can be recomputed at any time and nothing has to be stored:

    HYT-251112-48213     (HYT, year month day, five digits)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def enquiry_reference(conversation: Any) -> str:
    messages = getattr(conversation, "messages", None) or []
    started = getattr(messages[0], "created_at", None) if messages else None
    if not isinstance(started, datetime):
        started = datetime.now(UTC)
    digits = int(getattr(conversation, "id").int) % 100_000
    return f"HYT-{started:%y%m%d}-{digits:05d}"
