"""SMS OTP boundary.

No provider is configured in this repository. Production therefore fails
closed; tests may inject the synthetic provider explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
import json
import httpx

from .config import Settings


class OTPProviderError(RuntimeError):
    """Raised when an SMS provider cannot start or verify a challenge."""


class OTPProvider(Protocol):
    async def start(self, phone_number: str, recaptcha_token: str | None = None) -> str: ...
    async def verify(self, challenge_id: str, code: str) -> bool: ...


class UnavailableOTPProvider:
    async def start(self, phone_number: str, recaptcha_token: str | None = None) -> str:
        raise OTPProviderError("No SMS verification provider is configured.")


class FirebaseOTPProvider:
    """Firebase Identity Toolkit phone verification adapter.

    Firebase requires the client to satisfy its anti-abuse checks. This
    adapter uses Firebase's documented send/verify REST endpoints and never
    stores the SMS code.
    """

    def __init__(self, settings: Settings) -> None:
        if not settings.firebase_api_key:
            raise OTPProviderError("FIREBASE_API_KEY is not configured.")
        self._api_key = settings.firebase_api_key.get_secret_value()
        self._client = httpx.AsyncClient(timeout=15)

    async def start(self, phone_number: str, recaptcha_token: str | None = None) -> str:
        if not recaptcha_token:
            raise OTPProviderError("Firebase reCAPTCHA token is required.")
        response = await self._client.post(
            "https://identitytoolkit.googleapis.com/v1/accounts:sendVerificationCode",
            params={"key": self._api_key},
            json={"phoneNumber": phone_number, "recaptchaToken": recaptcha_token},
        )
        if response.status_code >= 400:
            raise OTPProviderError("Firebase could not start phone verification.")
        data = response.json()
        session_info = data.get("sessionInfo")
        if not session_info:
            raise OTPProviderError("Firebase returned no verification session.")
        return session_info

    async def verify(self, challenge_id: str, code: str) -> bool:
        response = await self._client.post(
            "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPhoneNumber",
            params={"key": self._api_key},
            json={"sessionInfo": challenge_id, "code": code},
        )
        return response.status_code < 400 and bool(response.json().get("idToken"))


class FirebaseAdminTokenVerifier:
    """Verifies the ID token produced by Firebase Authentication server-side."""

    def __init__(self, settings: Settings) -> None:
        if not settings.firebase_service_account_json:
            raise OTPProviderError("Firebase Admin credentials are not configured.")
        try:
            import firebase_admin
            from firebase_admin import auth, credentials
            if not firebase_admin._apps:
                firebase_admin.initialize_app(
                    credentials.Certificate(
                        json.loads(settings.firebase_service_account_json.get_secret_value())
                    ),
                    {"projectId": settings.firebase_project_id} if settings.firebase_project_id else None,
                )
            self._auth = auth
        except (ValueError, TypeError, json.JSONDecodeError, ImportError) as exc:
            raise OTPProviderError("Firebase Admin verification is unavailable.") from exc

    def verify(self, token: str, expected_phone: str) -> dict[str, object]:
        try:
            claims = self._auth.verify_id_token(token, check_revoked=True)
        except (
            self._auth.InvalidIdTokenError,
            self._auth.ExpiredIdTokenError,
            self._auth.RevokedIdTokenError,
        ) as exc:
            raise OTPProviderError("Firebase ID token verification failed.") from exc
        phone_number = claims.get("phone_number")
        if not isinstance(phone_number, str) or phone_number != expected_phone:
            raise OTPProviderError("Verified phone number does not match the consultation.")
        return {
            "uid": claims.get("uid"),
            "phone_number": phone_number,
        }

@dataclass
class SyntheticOTPProvider:
    """Test-only provider; never select this from production configuration."""

    code: str = "123456"

    async def start(self, phone_number: str, recaptcha_token: str | None = None) -> str:
        return f"test-{phone_number[-4:]}"

    async def verify(self, challenge_id: str, code: str) -> bool:
        return code == self.code
