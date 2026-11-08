"""Proof that a request came through trawellcare-bff, this API's only client.

Same system token trawellcare-admin-be trusts: short-lived, signed with the
shared JWT_SYSTEM_SECRET, and carrying no permissions of its own.
"""

from __future__ import annotations

import jwt

# Paths that never require the BFF service token.
OPEN_PATHS = frozenset({"/health"})

# Interactive API documentation. Exposed without a token in local development
# only; staging and production require the service token like every other route.
DOCS_PATHS = frozenset({"/docs", "/openapi.json", "/redoc"})


def is_service_token(token: str | None, secret: str | None) -> bool:
    """Fail closed: no secret or no token means no access."""
    if not token or not secret:
        return False
    try:
        claims = jwt.decode(token, secret, algorithms=["HS256"], options={"require": ["exp", "sub"]})
    except jwt.InvalidTokenError:
        return False
    return str(claims["sub"]).startswith("system:")
