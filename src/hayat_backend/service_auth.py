"""Proof that a request came through trawellcare-bff, this API's only client.

Same system token trawellcare-admin-be trusts: short-lived, signed with the
shared JWT_SYSTEM_SECRET, and carrying no permissions of its own.
"""

from __future__ import annotations

import jwt

OPEN_PATHS = frozenset({"/health", "/docs", "/openapi.json"})


def is_service_token(token: str | None, secret: str | None) -> bool:
    """Fail closed: no secret or no token means no access."""
    if not token or not secret:
        return False
    try:
        claims = jwt.decode(token, secret, algorithms=["HS256"], options={"require": ["exp", "sub"]})
    except jwt.InvalidTokenError:
        return False
    return str(claims["sub"]).startswith("system:")
