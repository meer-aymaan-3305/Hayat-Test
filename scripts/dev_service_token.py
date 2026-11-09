"""Mint a local-development X-Service-Token for direct Hayat API testing.

The backend only trusts requests carrying a JWT signed with
JWT_SYSTEM_SECRET (the same secret trawellcare-bff uses). This script
exists so developers can exercise the API without standing up the BFF.

Usage:
    python scripts/dev_service_token.py [--ttl 3600]

Prints a token to stdout. In production the BFF mints these per request;
never expose a service token to a browser.
"""

from __future__ import annotations

import argparse
import time

import jwt

from hayat_backend.config import get_settings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ttl", type=int, default=3600, help="token lifetime in seconds")
    args = parser.parse_args()

    settings = get_settings()
    secret = settings.jwt_system_secret
    if secret is None:
        print("JWT_SYSTEM_SECRET is not set — add it to .env first.")
        return 1
    token = jwt.encode(
        {"sub": "system:dev-cli", "exp": int(time.time()) + args.ttl},
        secret.get_secret_value(),
        algorithm="HS256",
    )
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
