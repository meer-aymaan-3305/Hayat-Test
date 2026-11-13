"""Groq's per-minute token limit is shared by every model on the account, so hopping to another
Groq model after a "rate limited" answer only fails again. A short wait does not: the window
is usually back in a few seconds. This module keeps one shared clock for that.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

MAX_WAIT = 12.0  # the longest a visitor waits for a limit window to reopen
_bucket_free_at = 0.0  # monotonic time at which the shared token window reopens

_DURATION = re.compile(r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m(?!s))?(?:(\d+(?:\.\d+)?)s)?(?:(\d+(?:\.\d+)?)ms)?")


def _seconds(text: str) -> float:
    match = _DURATION.fullmatch(text.strip())
    if not match or not any(match.groups()):
        return 0.0
    hours, minutes, seconds, millis = (float(g) if g else 0.0 for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def retry_wait(exc: Any, default: float = 20.0) -> float:
    """How long the provider says to wait, from the rate limit error's headers."""
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    for name in ("retry-after", "x-ratelimit-reset-tokens"):
        value = headers.get(name)
        if value:
            try:
                return float(value)
            except ValueError:
                seconds = _seconds(str(value))
                if seconds:
                    return seconds
    return default


def note_limited(wait: float) -> None:
    global _bucket_free_at
    _bucket_free_at = max(_bucket_free_at, time.monotonic() + min(wait, 3600.0))


def short_wait_left() -> float:
    """Seconds until the shared window reopens, when that is short enough to wait for; else 0."""
    left = _bucket_free_at - time.monotonic()
    return left if 0 < left <= MAX_WAIT else 0.0


async def wait_for_window() -> None:
    left = short_wait_left()
    if left:
        await asyncio.sleep(left + 0.2)


def reset() -> None:  # for tests
    global _bucket_free_at
    _bucket_free_at = 0.0
