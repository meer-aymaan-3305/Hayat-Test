"""CRM / Matching Engine Webhook Client.

Transmits CP-5 confirmed structured intake payloads (and strictly the 20 permitted
Appendix A fields) to Trawellcare's downstream CRM / matching engine.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID
import httpx

from .schemas.appendix_a import AppendixAIntakePayload, PERMITTED_FIELD_NAMES
from .audit_logging import global_audit_store

logger = logging.getLogger("hayat.crm")


class CRMTransmissionError(RuntimeError):
    """Raised when structured payload dispatch to CRM / matching engine fails."""


class CRMWebhookClient:
    """Dispatches confirmed Appendix A payloads to configured CRM webhook."""

    def __init__(self, webhook_url: str | None = None, timeout_seconds: float = 10.0) -> None:
        self.webhook_url = webhook_url
        self.timeout = timeout_seconds

    async def transmit_confirmed_payload(
        self,
        *,
        session_id: UUID,
        conversation_id: UUID,
        payload: dict[str, Any],
        confirmation_timestamp: Any,
    ) -> bool:
        # Service-boundary authorization: transmission requires an explicit CP-5
        # confirmation timestamp. A simple affirmative in chat is not enough.
        if confirmation_timestamp is None:
            raise CRMTransmissionError("CRM transmission requires explicit CP-5 consent confirmation.")
        # Enforce Appendix A allowlist strictly before transmission
        sanitized = {k: v for k, v in payload.items() if k in PERMITTED_FIELD_NAMES and v not in (None, "")}
        # Validate through strict Pydantic model (extra='forbid')
        validated_model = AppendixAIntakePayload(**sanitized)
        outbound_data = validated_model.model_dump(exclude_none=True)

        if not self.webhook_url:
            # Mock / local test mode: log transmitted status locally without external call
            global_audit_store.log_structured_payload(
                session_id=session_id,
                conversation_id=conversation_id,
                confirmed_fields=outbound_data,
                cp5_confirmation_timestamp=confirmation_timestamp,
                destination_integration="crm",
                status="transmitted",
            )
            return True

        # Remote integration path
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.post(
                    self.webhook_url,
                    json={
                        "session_id": str(session_id),
                        "conversation_id": str(conversation_id),
                        "confirmed_at": confirmation_timestamp.isoformat(),
                        "appendix_a_payload": outbound_data,
                    },
                    headers={"Content-Type": "application/json"},
                )
                if res.status_code >= 400:
                    error_msg = f"CRM webhook responded with status {res.status_code}: {res.text[:200]}"
                    global_audit_store.log_structured_payload(
                        session_id=session_id,
                        conversation_id=conversation_id,
                        confirmed_fields=outbound_data,
                        cp5_confirmation_timestamp=confirmation_timestamp,
                        destination_integration="crm",
                        status="failed",
                        failure_reason=error_msg,
                    )
                    raise CRMTransmissionError(error_msg)

                global_audit_store.log_structured_payload(
                    session_id=session_id,
                    conversation_id=conversation_id,
                    confirmed_fields=outbound_data,
                    cp5_confirmation_timestamp=confirmation_timestamp,
                    destination_integration="crm",
                    status="transmitted",
                )
                return True
        except Exception as exc:
            if not isinstance(exc, CRMTransmissionError):
                error_msg = f"CRM connection failed: {exc}"
                global_audit_store.log_structured_payload(
                    session_id=session_id,
                    conversation_id=conversation_id,
                    confirmed_fields=outbound_data,
                    cp5_confirmation_timestamp=confirmation_timestamp,
                    destination_integration="crm",
                    status="failed",
                    failure_reason=error_msg,
                )
                raise CRMTransmissionError(error_msg) from exc
            raise
