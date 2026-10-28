"""Validated API contracts for the Hayat persistence boundary."""

from .chat import ChatAction, ChatMessage, ChatRequest, ChatResponse, MessageRole
from .consent import ConsentCreate, ConsentRecord, ConsentType
from .conversation import Conversation, ConversationCreate, ConversationState, ConversationStatus
from .intake import (
    CaseFacts, ConsultationProgress, FactStatus, FactValue, IntakeData, PersonaReadyProfile,
)
from .results import PersonaResult, PlansResult, Plan
from .session import GuestSession, GuestSessionCreate
from .source import SourceReference
from .consultation import (
    ConsultationCreate, ConsultationDetails, ConsultationResponse, ConsultationStatus,
    OTPStartRequest, OTPStartResponse, OTPVerifyRequest, PreferredContactMethod,
)

__all__ = [
    "CaseFacts", "ChatAction", "ChatMessage", "ChatRequest", "ChatResponse", "ConsentCreate",
    "ConsentRecord", "ConsentType", "Conversation", "ConversationCreate",
    "ConversationStatus", "GuestSession", "GuestSessionCreate", "IntakeData",
    "MessageRole", "PersonaResult", "Plan", "PlansResult", "SourceReference",
    "ConsultationCreate", "ConsultationDetails", "ConsultationResponse",
    "ConsultationStatus", "OTPStartRequest", "OTPStartResponse",
    "OTPVerifyRequest", "PreferredContactMethod",
]
