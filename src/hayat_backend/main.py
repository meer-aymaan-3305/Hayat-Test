"""FastAPI application entry point for Hayat."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from uuid import UUID

from .config import SettingsError, get_settings
from .chat_service import ChatService, greeting
from .llm import create_chat_model
from .memory_store import MemoryStore
from .supabase_store import SupabaseStore, create_store
from .otp import (
    FirebaseAdminTokenVerifier, FirebaseOTPProvider, OTPProvider, OTPProviderError,
    UnavailableOTPProvider,
)
from .schemas import (
    ChatRequest, ConsentCreate, ConsultationCreate, ConsultationDetails,
    ConsultationResponse, ConversationCreate, OTPStartRequest, OTPStartResponse,
    OTPVerifyRequest, GuestSessionCreate,
)

logger = logging.getLogger("hayat")


class IntakeValidationRequest(BaseModel):
    procedure_code: str | None = None
    complexity_band: str | None = None
    urgency: str | None = None
    payer_type: str | None = None
    consent_given: bool = False


def _services() -> tuple[MemoryStore | SupabaseStore, ChatService]:
    store = create_store(get_settings())
    return store, ChatService(store, create_chat_model(get_settings()))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Validate local configuration before serving requests."""
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())
    if settings.missing_integrations:
        logger.warning(
            "Optional integrations are not configured for %s: %s",
            settings.app_env,
            ", ".join(settings.missing_integrations),
        )
    yield


def create_app(
    otp_provider: OTPProvider | None = None,
    store: MemoryStore | SupabaseStore | None = None,
    chat_service: ChatService | None = None,
) -> FastAPI:
    """Create the FastAPI application."""
    settings = get_settings()
    app = FastAPI(title="Hayat API", version="0.1.0", lifespan=lifespan)
    if chat_service is not None:
        if store is None:
            store = chat_service.store
    elif store is None:
        store, chat_service = _services()
    else:
        chat_service = ChatService(store, create_chat_model(settings))
    if otp_provider is not None:
        otp = otp_provider
    elif settings.firebase_api_key:
        otp = FirebaseOTPProvider(settings)
    else:
        otp = UnavailableOTPProvider()
    firebase_verifier = None
    if settings.firebase_service_account_json:
        try:
            firebase_verifier = FirebaseAdminTokenVerifier(settings)
        except OTPProviderError:
            logger.exception("Firebase Admin verification is unavailable")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=bool(settings.allowed_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        started = perf_counter()
        try:
            response = await call_next(request)
        except SettingsError:
            response = JSONResponse(
                status_code=503,
                content={"detail": "Application configuration is unavailable."},
            )
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-Ms"] = f"{(perf_counter() - started) * 1000:.2f}"
        return response

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, object]:
        """Return a safe liveness/readiness summary without exposing secrets."""
        current = get_settings()
        missing = current.missing_integrations
        return {
            "status": "ok" if not missing else "degraded",
            "service": "hayat-api",
            "environment": current.app_env,
            "integrations": {
                "groq": "configured" if "GROQ_API_KEY" not in missing else "not_configured",
                "supabase": (
                    "configured"
                    if not any(name.startswith("SUPABASE_") for name in missing)
                    else "not_configured"
                ),
            },
        }

    def authorized_session(
        session_id: UUID,
        x_session_token: str = Header(..., alias="X-Session-Token"),
    ):
        try:
            return store.authorize(session_id, x_session_token)
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail="Invalid or expired session.") from exc

    @app.post("/v1/sessions/guest", tags=["sessions"])
    async def create_guest_session(payload: GuestSessionCreate | None = None) -> dict[str, object]:
        session, token = store.create_guest_session((payload or GuestSessionCreate()).locale)
        return {"session_id": session.id, "session_token": token, "expires_at": session.expires_at}

    @app.post("/v1/conversations", tags=["conversations"])
    async def create_conversation(
        payload: ConversationCreate,
        x_session_token: str = Header(..., alias="X-Session-Token"),
    ):
        try:
            store.authorize(payload.guest_session_id, x_session_token)
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail="Invalid or expired session.") from exc
        conversation = store.create_conversation(payload.guest_session_id)
        session = store.get_session(payload.guest_session_id)
        greeting_message = store.append_message(
            conversation, "assistant", greeting(session.locale), session.locale
        )
        actions = chat_service.initial_actions(session.locale)
        return {
            "id": conversation.id,
            "session_id": conversation.session_id,
            "state": conversation.state,
            "language": session.locale,
            "greeting": greeting_message,
            "suggestions": actions,
            "suggested_actions": actions,
        }

    @app.post("/v1/chat", tags=["chat"])
    async def chat(
        payload: ChatRequest,
        x_session_id: UUID = Header(..., alias="X-Session-ID"),
        x_session_token: str = Header(..., alias="X-Session-Token"),
    ):
        try:
            store.authorize(x_session_id, x_session_token)
            conversation = store.get_conversation(x_session_id, payload.conversation_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="Conversation access denied.") from exc
        result = await chat_service.respond(
            conversation, payload.message, payload.client_message_id
        )
        return {
            "conversation_id": conversation.id,
            "message_id": result["assistant_message"].id,
            "reply": result["assistant_message"].content,
            "language": result["language"],
            "escalation_required": result["escalation_required"],
            "escalation_reason": result["escalation_reason"],
            "sources": result["sources"],
            "conversation_state": result["conversation_state"],
            "next_action": result["next_action"],
            "suggestions": result["suggestions"],
            "suggested_actions": result["suggested_actions"],
            "persona_profile": result["persona_profile"],
            "consultation_progress": result["consultation_progress"],
            "profile_summary": result["persona_profile"],
            "escalated": result["next_action"] == "escalate",
            "answer": result["answer"],
            "follow_up_question": result["follow_up_question"],
            "follow_up_target": result["follow_up_target"],
            "profile_updates": result["profile_updates"],
            "missing_required_fields": result["missing_required_fields"],
            "submission_status": result["submission_status"],
            "consultation": result["consultation"],
        }

    @app.get("/v1/conversations/{conversation_id}/messages", tags=["conversations"])
    async def messages(
        conversation_id: UUID,
        x_session_id: UUID = Header(..., alias="X-Session-ID"),
        x_session_token: str = Header(..., alias="X-Session-Token"),
    ):
        try:
            store.authorize(x_session_id, x_session_token)
            conversation = store.get_conversation(x_session_id, conversation_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="Conversation access denied.") from exc
        actions = (
            chat_service.initial_actions(store.get_session(x_session_id).locale)
            if not any(message.role == "user" for message in conversation.messages)
            else []
        )
        return {
            "messages": conversation.messages,
            "conversation_state": conversation.state,
            "suggested_actions": actions,
            "persona_profile": store.persona_profile(conversation),
            "consultation_progress": store.consultation_progress(conversation),
        }

    @app.get("/v1/conversations/{conversation_id}/export.json", tags=["conversations"])
    async def export_conversation(
        conversation_id: UUID,
        x_session_id: UUID = Header(..., alias="X-Session-ID"),
        x_session_token: str = Header(..., alias="X-Session-Token"),
    ):
        try:
            store.authorize(x_session_id, x_session_token)
            conversation = store.get_conversation(x_session_id, conversation_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="Conversation access denied.") from exc
        return store.export_conversation(conversation)

    @app.post("/v1/consent", tags=["consent"])
    async def consent(
        payload: ConsentCreate,
        x_session_token: str = Header(..., alias="X-Session-Token"),
    ):
        try:
            store.authorize(payload.guest_session_id, x_session_token)
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail="Invalid or expired session.") from exc
        return store.record_consent(payload.guest_session_id, payload.model_dump(mode="json"))

    @app.post("/v1/leads", tags=["consultations"])
    async def save_lead(
        conversation_id: UUID,
        payload: ConsultationDetails,
        x_session_id: UUID = Header(..., alias="X-Session-ID"),
        x_session_token: str = Header(..., alias="X-Session-Token"),
    ):
        try:
            store.authorize(x_session_id, x_session_token)
            conversation = store.get_conversation(x_session_id, conversation_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="Conversation access denied.") from exc
        lead = store.upsert_lead(conversation.id, payload)
        return {"lead_id": lead.id, "phone_verified": lead.phone_verified}

    @app.post("/v1/consultations/otp/start", response_model=OTPStartResponse, tags=["consultations"])
    async def start_otp(
        payload: OTPStartRequest,
        x_session_id: UUID = Header(..., alias="X-Session-ID"),
        x_session_token: str = Header(..., alias="X-Session-Token"),
    ):
        try:
            store.authorize(x_session_id, x_session_token)
            conversation = store.get_conversation(x_session_id, payload.conversation_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="Conversation access denied.") from exc
        lead = store.lead_for(conversation.id)
        if not lead or lead.details.phone_number != payload.phone_number:
            raise HTTPException(status_code=400, detail="Save the lead phone number before verification.")
        try:
            challenge_id = await otp.start(payload.phone_number, payload.recaptcha_token)
        except OTPProviderError as exc:
            raise HTTPException(status_code=503, detail="Phone verification is unavailable.") from exc
        store.create_otp_challenge(conversation.id, challenge_id)
        store.set_conversation_state(conversation, "awaiting_verification")
        return OTPStartResponse(challenge_id=challenge_id)

    @app.post("/v1/consultations/otp/verify", tags=["consultations"])
    async def verify_otp(
        payload: OTPVerifyRequest,
        x_session_id: UUID = Header(..., alias="X-Session-ID"),
        x_session_token: str = Header(..., alias="X-Session-Token"),
    ):
        try:
            store.authorize(x_session_id, x_session_token)
            conversation = store.get_conversation(x_session_id, payload.conversation_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="Conversation access denied.") from exc
        if not store.valid_otp_challenge(conversation.id, payload.challenge_id):
            raise HTTPException(status_code=400, detail="Invalid verification challenge.")
        if settings.firebase_api_key:
            if firebase_verifier is None:
                raise HTTPException(status_code=503, detail="Phone verification is unavailable.")
            if not payload.firebase_id_token:
                raise HTTPException(status_code=400, detail="Firebase ID token is required.")
            lead = store.lead_for(conversation.id)
            if not lead:
                raise HTTPException(status_code=400, detail="Save the lead before verification.")
            try:
                claims = firebase_verifier.verify(
                    payload.firebase_id_token, lead.details.phone_number
                )
                valid = True
            except OTPProviderError as exc:
                raise HTTPException(status_code=400, detail="Phone verification failed.") from exc
        else:
            if not payload.code:
                raise HTTPException(status_code=400, detail="Verification code is required.")
            try:
                valid = await otp.verify(payload.challenge_id, payload.code)
            except OTPProviderError as exc:
                raise HTTPException(status_code=503, detail="Phone verification is unavailable.") from exc
        if not valid:
            raise HTTPException(status_code=400, detail="Invalid verification code.")
        store.set_phone_verified(
            conversation.id,
            claims.get("uid") if settings.firebase_api_key and firebase_verifier is not None else None,
        )
        return {"verified": True}

    @app.post("/v1/consultations", response_model=ConsultationResponse, tags=["consultations"])
    async def create_consultation(
        payload: ConsultationCreate,
        x_session_id: UUID = Header(..., alias="X-Session-ID"),
        x_session_token: str = Header(..., alias="X-Session-Token"),
    ):
        try:
            store.authorize(x_session_id, x_session_token)
            conversation = store.get_conversation(x_session_id, payload.conversation_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="Conversation access denied.") from exc
        if not store.has_valid_consent(x_session_id, "consultation_processing"):
            raise HTTPException(status_code=400, detail="Consultation consent is required.")
        if not payload.preferred_dates_times or not payload.timezone:
            raise HTTPException(
                status_code=400,
                detail="Preferred dates, times, and timezone are required.",
            )
        try:
            consultation = store.create_consultation(
                conversation,
                ConsultationDetails.model_validate(
                    payload.model_dump(exclude={"conversation_id", "consent_policy_version"})
                ),
                payload.consent_policy_version,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return ConsultationResponse(
            **payload.model_dump(),
            id=consultation.id,
            status=consultation.status,
            phone_verified=True,
            submitted_at=consultation.submitted_at,
        )

    @app.post("/v1/intake/validate", tags=["intake"])
    async def validate_intake(payload: IntakeValidationRequest):
        required = ("procedure_code", "complexity_band", "urgency", "payer_type")
        missing = [field for field in required if getattr(payload, field) is None]
        if not payload.consent_given:
            missing.append("purpose_specific_consent")
        return {"valid": not missing, "missing_inputs": missing}

    return app


app = create_app()


def run() -> None:
    """Run the API with Uvicorn."""
    import uvicorn

    uvicorn.run("hayat_backend.main:app", host="127.0.0.1", port=8000, reload=False)
