"""FastAPI application entry point for Hayat."""

from __future__ import annotations

import logging
from typing import Literal
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from time import perf_counter
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

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
    ChatRequest,
    ConsentCreate,
    ConsultationCreate,
    ConsultationDetails,
    ConsultationResponse,
    ConversationCreate,
    GuestSessionCreate,
    OTPStartRequest,
    OTPStartResponse,
    OTPVerifyRequest,
)
from .schemas.coordinator import (
    AppointmentConfirmationRequest,
    CoordinatorAssignRequest,
    CoordinatorHandoff,
    CoordinatorProgressRequest,
    HandoffStatusResponse,
)
from .coordinator_service import CoordinatorHandoffError, CoordinatorHandoffService
from .language import detect_language
from .programmes_catalog import PROGRAMMES_CATALOG, get_programme
from .schemas.programme import (
    ContactConsentStatus,
    EnquiryStatus,
    ProgrammeId,
    RegistrationStatus,
    SignatureProgrammeEnquiry,
    SignatureProgrammeEnquiryCreate,
    SignatureProgrammeEnquiryResponse,
    SignatureProgrammeEnquiryUpdate,
    SignatureProgrammeRegistrationRequest,
)
from .guardrails import redact_message
from .schemas.chat import RedactRequest
from .policy_engine import EF_SCRIPTS_EN, EF_SCRIPTS_AR
from .programme_service import assign_reference_code, registration_reply
from .service_auth import OPEN_PATHS, is_service_token
from .audit_logging import global_audit_store

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
    coordinator_service = CoordinatorHandoffService(store, settings=settings)
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

    system_secret = settings.jwt_system_secret.get_secret_value() if settings.jwt_system_secret else None

    # Everything except health and docs must arrive through trawellcare-bff.
    @app.middleware("http")
    async def require_service(request: Request, call_next):
        if (
            settings.app_env != "test"
            and request.url.path not in OPEN_PATHS
            and not is_service_token(request.headers.get("X-Service-Token"), system_secret)
        ):
            return JSONResponse(status_code=401, content={"detail": "Not authenticated."})
        return await call_next(request)

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

    @app.post("/v1/redact", tags=["chat"])
    async def redact(payload: RedactRequest) -> dict[str, str]:
        """Clean text a visitor wrote outside the chat, such as a chat title, before it's saved."""
        return {"text": redact_message(payload.text)}

    @app.post("/v1/chat", tags=["chat"])
    async def chat(
        payload: ChatRequest,
        x_session_id: UUID = Header(..., alias="X-Session-ID"),
        x_session_token: str = Header(..., alias="X-Session-Token"),
        x_visitor: Literal["guest", "customer"] | None = Header(default=None, alias="X-Visitor"),
        x_contact_consent: bool = Header(default=False, alias="X-Contact-Consent"),
        x_reply_language: Literal["en", "ar"] | None = Header(default=None, alias="X-Reply-Language"),
    ):
        try:
            store.authorize(x_session_id, x_session_token)
            conversation = store.get_conversation(x_session_id, payload.conversation_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="Conversation access denied.") from exc
        try:
            result = await chat_service.respond(
                conversation,
                payload.message,
                payload.client_message_id,
                x_visitor,
                # A promise of contact needs the customer's consent and Addendum 1.1.
                contactable=x_contact_consent and settings.policy_addendum_1_1_approved,
                reply_language=x_reply_language,
                # Website visitors get scripted replies until the AI passes
                # safety testing. See docs/HAYAT_POLICY_REGISTER.md.
                use_ai=x_visitor is None or settings.medical_ai_replies,
                # While the AI is off, shadow mode logs what it would have said.
                shadow_ai=settings.medical_ai_shadow,
            )
        except Exception as exc:
            # UH-6 & EF-8: Integration or database failure during turn
            logger.exception("Integration or database error during chat turn: %s", exc)
            language = detect_language(payload.message)
            scripts = EF_SCRIPTS_AR if language == "ar" else EF_SCRIPTS_EN
            ef8_reply = scripts["EF-8"]
            global_audit_store.log_fallback(
                session_id=conversation.session_id,
                conversation_id=conversation.id,
                rule_id="EF-8",
                trigger_type=f"database_integration_error:{type(exc).__name__}",
            )
            return {
                "conversation_id": conversation.id,
                "message_id": uuid4(),
                "reply": ef8_reply,
                "stored_message": redact_message(payload.message),
                "language": language,
                "escalation_required": True,
                "escalation_reason": "EF-8",
                "sources": [],
                "conversation_state": "escalated",
                "next_action": "escalate",
                "suggestions": [],
                "suggested_actions": [],
                "persona_profile": store.persona_profile(conversation),
                "consultation_progress": store.consultation_progress(conversation),
                "profile_summary": store.persona_profile(conversation),
                "escalated": True,
                "answer": ef8_reply,
                "follow_up_question": None,
                "follow_up_target": None,
                "profile_updates": [],
                "missing_required_fields": [],
                "submission_status": "failed",
                "consultation": None,
            }
        return {
            "conversation_id": conversation.id,
            "message_id": result["assistant_message"].id,
            "reply": result["assistant_message"].content,
            "stored_message": redact_message(payload.message),
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
            "coordinator_handoff": result.get("coordinator_handoff"),
            "programme_enquiry": (
                result["programme_enquiry"].model_dump(mode="json")
                if hasattr(result.get("programme_enquiry"), "model_dump")
                else result.get("programme_enquiry")
            ),
            "service_category": result.get("service_category", "international_medical_travel"),
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

    @app.get("/v1/conversations/{conversation_id}/handoff", response_model=HandoffStatusResponse, tags=["coordinator"])
    async def get_conversation_handoff(
        conversation_id: UUID,
        x_session_id: UUID = Header(..., alias="X-Session-ID"),
        x_session_token: str = Header(..., alias="X-Session-Token"),
    ):
        try:
            store.authorize(x_session_id, x_session_token)
            conversation = store.get_conversation(x_session_id, conversation_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="Conversation access denied.") from exc

        handoff = store.get_handoff_for_conversation(conversation.id)
        if not handoff:
            handoff = coordinator_service.initiate_handoff(conversation=conversation, session_id=x_session_id)

        return HandoffStatusResponse(
            id=handoff.id,
            conversation_id=handoff.conversation_id,
            status=handoff.status,
            assigned_coordinator_name=handoff.assigned_coordinator_name,
            coordinator_role=handoff.coordinator_role,
            appointment_confirmed=bool(handoff.appointment_details is not None),
            appointment_details=handoff.appointment_details,
            updated_at=handoff.updated_at,
        )

    @app.get("/v1/coordinator/handoffs/{handoff_id}", response_model=CoordinatorHandoff, tags=["coordinator"])
    async def get_coordinator_handoff(
        handoff_id: UUID,
        x_coordinator_role: str = Header(default="case_manager", alias="X-Coordinator-Role"),
    ):
        handoff = store.get_coordinator_handoff(handoff_id)
        if not handoff:
            raise HTTPException(status_code=404, detail="Handoff not found.")
        return handoff

    @app.post("/v1/coordinator/handoffs/{handoff_id}/assign", response_model=CoordinatorHandoff, tags=["coordinator"])
    async def assign_coordinator(
        handoff_id: UUID,
        payload: CoordinatorAssignRequest,
    ):
        try:
            return coordinator_service.assign_coordinator(
                handoff_id=handoff_id,
                coordinator_id=payload.coordinator_id,
                coordinator_name=payload.coordinator_name,
                role=payload.role,
                notes=payload.notes,
            )
        except CoordinatorHandoffError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/v1/coordinator/handoffs/{handoff_id}/progress", response_model=CoordinatorHandoff, tags=["coordinator"])
    async def update_coordinator_progress(
        handoff_id: UUID,
        payload: CoordinatorProgressRequest,
        x_coordinator_id: str = Header(default="coord_101", alias="X-Coordinator-ID"),
        x_coordinator_role: str = Header(default="case_manager", alias="X-Coordinator-Role"),
    ):
        try:
            return coordinator_service.update_progress(
                handoff_id=handoff_id,
                status=payload.status,
                coordinator_id=x_coordinator_id,
                coordinator_role=x_coordinator_role,
                notes=payload.notes,
                contact_channel_used=payload.contact_channel_used,
            )
        except CoordinatorHandoffError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/coordinator/handoffs/{handoff_id}/confirm-appointment", response_model=CoordinatorHandoff, tags=["coordinator"])
    async def confirm_appointment(
        handoff_id: UUID,
        payload: AppointmentConfirmationRequest,
    ):
        try:
            return coordinator_service.confirm_appointment(
                handoff_id=handoff_id,
                coordinator_id=payload.coordinator_id,
                coordinator_name=payload.coordinator_name,
                appointment_time=payload.appointment_time,
                provider_or_clinic=payload.provider_or_clinic,
                mode=payload.mode,
                notes=payload.notes,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except CoordinatorHandoffError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get(
        "/v1/coordinator/programme-enquiries/{identifier}",
        response_model=SignatureProgrammeEnquiry,
        tags=["coordinator"],
    )
    async def get_coordinator_programme_enquiry(
        identifier: str,
        x_coordinator_id: str = Header(default="coord_101", alias="X-Coordinator-ID"),
        x_coordinator_role: str = Header(default="case_manager", alias="X-Coordinator-Role"),
    ):
        """Allow authorized coordinators to retrieve a programme enquiry by ID or reference code."""
        enquiry = None
        try:
            enquiry = store.get_programme_enquiry(UUID(identifier))
        except (ValueError, AttributeError):
            pass

        if not enquiry and hasattr(store, "get_programme_enquiry_by_reference_code"):
            enquiry = store.get_programme_enquiry_by_reference_code(identifier)

        if not enquiry:
            raise HTTPException(status_code=404, detail=f"Programme enquiry '{identifier}' not found.")
        return enquiry

    # =========================================================================
    # Signature Wellness Programmes Endpoints (Separate Service Category)
    # =========================================================================

    @app.get("/v1/programmes", tags=["signature_programmes"])
    async def list_programmes():
        """List all official Trawellcare Signature Wellness Programmes."""
        return [prog.model_dump(mode="json") for prog in PROGRAMMES_CATALOG.values()]

    @app.get("/v1/programmes/{programme_id}", tags=["signature_programmes"])
    async def get_programme_detail(programme_id: str):
        """Get full details, themes, and FAQs for a specific signature programme."""
        prog = get_programme(programme_id)
        if not prog:
            raise HTTPException(status_code=404, detail=f"Programme '{programme_id}' not found.")
        return prog.model_dump(mode="json")

    @app.post("/v1/programmes/enquiries", response_model=SignatureProgrammeEnquiry, tags=["signature_programmes"])
    async def create_or_update_programme_enquiry(
        payload: SignatureProgrammeEnquiryCreate,
        x_session_id: UUID = Header(..., alias="X-Session-ID"),
        x_session_token: str = Header(..., alias="X-Session-Token"),
    ):
        """Create or update an enquiry preference record for Signature Programmes."""
        try:
            store.authorize(x_session_id, x_session_token)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="Session access denied.") from exc

        updates = payload.model_dump(exclude={"conversation_id", "session_id"}, exclude_unset=True)
        enquiry = store.upsert_programme_enquiry(
            conversation_id=payload.conversation_id,
            session_id=payload.session_id,
            updates=updates,
        )
        return enquiry

    @app.get("/v1/conversations/{conversation_id}/programme-enquiry", response_model=SignatureProgrammeEnquiry, tags=["signature_programmes"])
    async def get_conversation_programme_enquiry(
        conversation_id: UUID,
        x_session_id: UUID = Header(..., alias="X-Session-ID"),
        x_session_token: str = Header(..., alias="X-Session-Token"),
    ):
        """Retrieve the Signature Programme enquiry associated with a conversation."""
        try:
            store.authorize(x_session_id, x_session_token)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="Session access denied.") from exc

        enquiry = store.get_programme_enquiry_for_conversation(conversation_id)
        if not enquiry:
            raise HTTPException(status_code=404, detail="No programme enquiry found for conversation.")
        return enquiry

    @app.post("/v1/programmes/enquiries/{enquiry_id}/register-interest", response_model=SignatureProgrammeEnquiryResponse, tags=["signature_programmes"])
    async def register_programme_interest(
        enquiry_id: UUID,
        payload: SignatureProgrammeRegistrationRequest,
        x_session_id: UUID = Header(..., alias="X-Session-ID"),
        x_session_token: str = Header(..., alias="X-Session-Token"),
    ):
        """Register interest for a tailored Signature Programme retreat proposal with consent."""
        try:
            store.authorize(x_session_id, x_session_token)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="Session access denied.") from exc

        enquiry = store.get_programme_enquiry(enquiry_id)
        if not enquiry or enquiry.session_id != x_session_id:
            raise HTTPException(status_code=404, detail="Programme enquiry not found.")

        # Contact details are only kept once Policy Addendum 1.1 is approved.
        if settings.policy_addendum_1_1_approved:
            enquiry.lead_name = payload.full_name
            enquiry.lead_phone = payload.phone_number
            enquiry.lead_email = payload.email
            enquiry.preferred_contact_method = payload.preferred_contact_method
            enquiry.contact_consent_status = (
                ContactConsentStatus.GRANTED if payload.contact_consent else ContactConsentStatus.REFUSED
            )
        enquiry.registration_status = RegistrationStatus.INTEREST_REGISTERED
        enquiry.enquiry_status = EnquiryStatus.SUBMITTED
        enquiry.updated_at = datetime.now(UTC)
        assign_reference_code(enquiry)

        store.save_programme_enquiry(enquiry)

        return SignatureProgrammeEnquiryResponse(
            enquiry=enquiry,
            summary_text=registration_reply(enquiry, store.get_session(x_session_id).locale),
            coordinator_assigned=False,
        )

    return app


app = create_app()


def run() -> None:
    """Run the API with Uvicorn."""
    import uvicorn

    uvicorn.run("hayat_backend.main:app", host="127.0.0.1", port=2005, reload=False)
