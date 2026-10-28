import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from hayat_backend.schemas import (
    CaseFacts,
    ConversationCreate,
    PersonaResult,
    PlansResult,
)

ROOT = Path(__file__).parents[1]


def _example(name: str) -> dict:
    return json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))


def test_examples_validate_against_public_contracts():
    CaseFacts.model_validate(_example("caseFacts.example.json"))
    ConversationCreate.model_validate(_example("conversation.example.json"))
    PersonaResult.model_validate(_example("personaResult.example.json"))
    PlansResult.model_validate(_example("plansResult.example.json"))


def test_schema_package_has_stable_public_exports():
    import hayat_backend.schemas as schemas

    assert set(schemas.__all__) == {
        "CaseFacts", "ChatAction", "ChatMessage", "ChatRequest", "ChatResponse", "ConsentCreate",
        "ConsentRecord", "ConsentType", "Conversation", "ConversationCreate",
        "ConversationStatus", "GuestSession", "GuestSessionCreate", "IntakeData",
        "MessageRole", "PersonaResult", "Plan", "PlansResult", "SourceReference",
        "ConsultationCreate", "ConsultationDetails", "ConsultationResponse",
        "ConsultationStatus", "OTPStartRequest", "OTPStartResponse",
        "OTPVerifyRequest", "PreferredContactMethod",
    }
    assert all(hasattr(schemas, name) for name in schemas.__all__)


def test_contracts_reject_oversized_chat_and_unknown_fields():
    from hayat_backend.schemas import ChatRequest

    with pytest.raises(ValidationError):
        ChatRequest.model_validate(
            {
                "conversation_id": "00000000-0000-0000-0000-000000000001",
                "message": "x" * 8_001,
            }
        )
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(
            {
                "conversation_id": "00000000-0000-0000-0000-000000000001",
                "message": "hello",
                "unexpected": True,
            }
        )
