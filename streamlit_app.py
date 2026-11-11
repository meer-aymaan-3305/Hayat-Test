"""Hayat — Medical Travel & Signature Wellness Concierge Client.

Authoritative Specifications:
- HAYAT_Guardrail_Document_v1.docx (Version 1.0)
- docs/knowledge/signature_programmes.md (Signature Wellness Programmes)
"""

from __future__ import annotations

import os
import re
import uuid
from typing import Any
from datetime import UTC, datetime, timedelta

import jwt
import requests
import streamlit as st

from hayat_backend.config import get_settings


def _validation_detail(response: requests.Response) -> str:
    try:
        detail = response.json().get("detail", "The API returned a safe error.")
        if isinstance(detail, list):
            return "; ".join(
                f"{item.get('loc', ['request'])[-1]}: {item.get('msg', 'invalid value')}"
                for item in detail
            )
        return str(detail)
    except ValueError:
        return "The API returned a safe error."


def _demo_client() -> requests.Session:
    """The API only accepts service callers, so the local demo signs in as one."""
    session = requests.Session()
    secret = get_settings().jwt_system_secret
    if secret:
        claims = {"sub": "system:streamlit-demo", "exp": datetime.now(UTC) + timedelta(hours=12)}
        session.headers["X-Service-Token"] = jwt.encode(claims, secret.get_secret_value(), algorithm="HS256")
    return session


api = _demo_client()


def _headers() -> dict[str, str]:
    return {
        "X-Session-ID": st.session_state.session_id,
        "X-Session-Token": st.session_state.token,
    }


def _fact_values(profile: dict | None) -> dict[str, object]:
    return {
        fact["field_name"]: fact.get("value")
        for fact in (profile or {}).get("facts", [])
        if fact.get("value") not in (None, "")
    }


def _clean_content(text: str) -> str:
    cleaned = re.sub(r"^\s*\[?(?:Assistant|Hayat|Bot|User|Human)\]?:?\s*", "", str(text), flags=re.I)
    return cleaned.strip()


# Page setup
st.set_page_config(
    page_title="Hayat — Medical & Wellness Concierge",
    page_icon="🌿",
    layout="wide",
)

st.title("Hayat — Medical & Wellness Concierge")

base_url = st.sidebar.text_input("API URL", os.getenv("HAYAT_API_URL", "http://127.0.0.1:2005"))

# State initialization
if "session_id" not in st.session_state:
    st.session_state.session_id = None
    st.session_state.token = None
    st.session_state.conversation_id = None
    st.session_state.messages = []
    st.session_state.locale = "en"
    st.session_state.suggestions = []
    st.session_state.profile_summary = {}
    st.session_state.consultation_progress = None
    st.session_state.consultation_details = {}
    st.session_state.lead_saved = False
    st.session_state.phone_verified = False
    st.session_state.consent_recorded = False
    st.session_state.otp_challenge_id = None
    st.session_state.consultation_request = None
    st.session_state.coordinator_handoff = None
    st.session_state.programme_enquiry = None
    st.session_state.service_category = "signature_programmes"

st.session_state.locale = st.sidebar.selectbox(
    "Language",
    ["en", "ar"],
    format_func=lambda value: "English" if value == "en" else "العربية",
)

# Sidebar: Governance & Policy Information
with st.sidebar.expander("Governance & Policy Guardrails", expanded=True):
    st.info("Role: Intake & Routing Concierge only (CP-2)")
    st.caption("Policy Specification: HAYAT_Guardrail_Document_v1.docx v1.0")
    st.caption("Policy Addendum 1.1: Pending Formal Approval (In-Chat Contact Collection Disabled)")
    st.caption("Coordination: Authorized Human Coordinator Only (HB-8, CP-7)")

with st.sidebar.expander("Restore Guest Session"):
    restore_session_id = st.text_input("Session ID", key="restore_session_id")
    restore_token = st.text_input("Session token", type="password", key="restore_token")
    restore_conversation_id = st.text_input("Conversation ID", key="restore_conversation_id")
    if st.button("Restore conversation"):
        headers = {"X-Session-ID": restore_session_id, "X-Session-Token": restore_token}
        response = api.get(
            f"{base_url}/v1/conversations/{restore_conversation_id}/messages",
            headers=headers,
            timeout=10,
        )
        if response.ok:
            st.session_state.session_id = restore_session_id
            st.session_state.token = restore_token
            st.session_state.conversation_id = restore_conversation_id
            st.session_state.messages = response.json().get("messages", [])
            st.session_state.suggestions = response.json().get("suggested_actions", [])
            st.session_state.profile_summary = response.json().get("persona_profile", {})
            st.session_state.consultation_progress = response.json().get("consultation_progress")
            # Fetch handoff if available
            h_resp = api.get(
                f"{base_url}/v1/conversations/{restore_conversation_id}/handoff",
                headers=headers,
                timeout=10,
            )
            if h_resp.ok:
                st.session_state.coordinator_handoff = h_resp.json()
            # Fetch programme enquiry if available
            p_resp = api.get(
                f"{base_url}/v1/conversations/{restore_conversation_id}/programme-enquiry",
                headers=headers,
                timeout=10,
            )
            if p_resp.ok:
                st.session_state.programme_enquiry = p_resp.json()
                st.session_state.service_category = "signature_programmes"
            st.rerun()
        else:
            st.error("Could not restore that conversation.")

if st.sidebar.button("Start New Concierge Session", use_container_width=True):
    st.session_state.profile_summary = {}
    st.session_state.consultation_progress = None
    st.session_state.consultation_details = {}
    st.session_state.lead_saved = False
    st.session_state.phone_verified = False
    st.session_state.consent_recorded = False
    st.session_state.otp_challenge_id = None
    st.session_state.consultation_request = None
    st.session_state.coordinator_handoff = None
    st.session_state.programme_enquiry = None
    st.session_state.messages = []
    st.session_state.suggestions = []

    response = api.post(
        f"{base_url}/v1/sessions/guest",
        json={"locale": st.session_state.locale},
        timeout=10,
    )
    if response.ok:
        data = response.json()
        st.session_state.session_id = data["session_id"]
        st.session_state.token = data["session_token"]
        conversation = api.post(
            f"{base_url}/v1/conversations",
            headers={
                "X-Session-Token": st.session_state.token,
                "X-Client-Hour": str(datetime.now().hour),
            },
            json={"guest_session_id": st.session_state.session_id},
            timeout=10,
        )
        if conversation.ok:
            conversation_data = conversation.json()
            st.session_state.conversation_id = conversation_data["id"]
            greeting_message = conversation_data.get("greeting")
            if greeting_message:
                st.session_state.messages = [greeting_message]
            st.session_state.suggestions = conversation_data.get(
                "suggested_actions",
                conversation_data.get("suggestions", []),
            )
            st.rerun()
        else:
            st.error(f"Could not create conversation: {_validation_detail(conversation)}")
    else:
        st.error(f"Could not start session: {_validation_detail(response)}")


# =============================================================================
# Top Service Category Selection
# =============================================================================
service_tab = st.radio(
    "Select Service Category",
    ["Signature Wellness Programmes", "International Medical Travel & Consultations"],
    index=0 if st.session_state.service_category == "signature_programmes" else 1,
    horizontal=True,
    label_visibility="collapsed",
)
is_programme_mode = (service_tab == "Signature Wellness Programmes")


# =============================================================================
# Discovery Hero Cards (When in Signature Programmes Mode)
# =============================================================================
if is_programme_mode:
    st.caption("Official Trawellcare Signature Wellness Experiences — Individually curated 7-day retreats (5 retreat days + 2 travel days).")
    card_cols = st.columns(3)
    with card_cols[0]:
        with st.container(border=True):
            st.markdown("### HAYAT-100")
            st.caption("**Longevity & Healthy Ageing**")
            st.write("For adults across all life stages wanting to understand wellbeing and build healthier lifestyle habits.")
            st.markdown("*Philosophy:* It's not just living to 100 — it's making every year count.")
            if st.button("Explore HAYAT-100", key="hero_h100", use_container_width=True):
                st.session_state.pending_prompt = "I want healthy ageing and longevity."

    with card_cols[1]:
        with st.container(border=True):
            st.markdown("### AAfiya")
            st.caption("**Women's Fitness & Wellness**")
            st.write("For women of all fitness levels seeking restorative balance, pilates, yoga, nutrition, and self-care.")
            st.markdown("*Philosophy:* Your journey. Your wellbeing. Your way.")
            if st.button("Explore AAfiya", key="hero_aafiya", use_container_width=True):
                st.session_state.pending_prompt = "Tell me about AAfiya women's retreat."

    with card_cols[2]:
        with st.container(border=True):
            st.markdown("### FFounders")
            st.caption("**Executive Fitness & Wellness**")
            st.write("For founders, entrepreneurs, and corporate leaders to reset, build physical resilience, and optimize recovery.")
            st.markdown("*Philosophy:* Success should never come at the expense of health.")
            if st.button("Explore FFounders", key="hero_ffounders", use_container_width=True):
                st.session_state.pending_prompt = "Tell me about FFounders executive retreat."

    st.divider()


# =============================================================================
# Main Layout: 2 Columns (Conversation & Contextual Detail Panel)
# =============================================================================
col_chat, col_details = st.columns([3, 2])

# Left Column: Conversation
with col_chat:
    st.subheader("Chat with Hayat" if st.session_state.locale == "en" else "المحادثة مع حياة")

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.write(_clean_content(message["content"]))

    # Phone verification: appears when Hayat reaches the verification step.
    if st.session_state.get("next_action") == "verify_phone":
        _facts = _fact_values(st.session_state.get("profile_summary"))
        _phone = str(_facts.get("phone_number") or "")
        with st.container(border=True):
            st.markdown("**Verify your phone number**")
            st.caption(
                f"We will text a one time code to {_phone or 'your number'}. "
                "(Local testing: the code is 123456 and no SMS is sent.)"
            )
            if st.button("Send code", disabled=not _phone):
                _r = api.post(
                    f"{base_url}/v1/consultations/otp/start",
                    headers=_headers(),
                    json={"conversation_id": st.session_state.conversation_id, "phone_number": _phone},
                    timeout=15,
                )
                if _r.ok:
                    st.session_state.otp_challenge_id = _r.json()["challenge_id"]
                    st.success("Code sent.")
                else:
                    st.error(f"Could not send the code: {_validation_detail(_r)}")
            if st.session_state.get("otp_challenge_id"):
                _code = st.text_input("Enter the code", max_chars=10, key="otp_code_input")
                if st.button("Verify"):
                    _r = api.post(
                        f"{base_url}/v1/consultations/otp/verify",
                        headers=_headers(),
                        json={
                            "conversation_id": st.session_state.conversation_id,
                            "challenge_id": st.session_state.otp_challenge_id,
                            "code": _code,
                        },
                        timeout=15,
                    )
                    if _r.ok:
                        st.session_state.otp_challenge_id = None
                        st.session_state.next_action = None
                        st.session_state.pending_prompt = "I have verified my number"
                        st.rerun()
                    else:
                        st.error(f"Verification failed: {_validation_detail(_r)}")

    # Clean Suggested Next Steps
    if st.session_state.suggestions:
        st.caption("Suggested next steps" if st.session_state.locale == "en" else "الخطوات والمقترحات المتاحة")
        sug_cols = st.columns(min(len(st.session_state.suggestions), 4))
        for idx, suggestion in enumerate(st.session_state.suggestions[:4]):
            with sug_cols[idx]:
                if st.button(suggestion["label"], key=f"sug_{suggestion['action_id']}_{idx}", use_container_width=True):
                    st.session_state.pending_prompt = suggestion["payload"]

# Right Column: Contextual Details
with col_details:
    if st.session_state.conversation_id:
        if is_programme_mode:
            # -------------------------------------------------------------
            # Signature Programmes Enquiry Journey Panel
            # -------------------------------------------------------------
            enquiry = st.session_state.get("programme_enquiry")
            enq_dict = enquiry if isinstance(enquiry, dict) else (enquiry.model_dump() if hasattr(enquiry, "model_dump") else {})

            st.subheader("Retreat Enquiry Progress")

            with st.container(border=True):
                prog = enq_dict.get("primary_programme")
                stage = enq_dict.get("current_stage", "discovery")
                reg_status = enq_dict.get("registration_status", "unregistered")

                if prog:
                    st.markdown(f"**Selected Programme:** `{prog.replace('_', '-').upper()}`")
                else:
                    st.markdown("**Selected Programme:** *Exploring signature retreats*")

                dest = enq_dict.get("destination_preference")
                if dest:
                    st.markdown(f"**Preferred Destination:** `{dest}`")

                timing = enq_dict.get("preferred_travel_period") or enq_dict.get("preferred_month")
                if timing:
                    st.markdown(f"**Travel Timing:** `{timing}`")

                activities = enq_dict.get("activity_interests")
                if activities:
                    st.markdown(f"**Focus & Activities:** {', '.join(activities)}")

                group_pref = "Solo / Individual" if not enq_dict.get("group_participation") else f"Group ({enq_dict.get('group_size', 'Multiple')} participants)"
                if enq_dict.get("group_participation") is not None and (dest or timing):
                    st.markdown(f"**Participation:** `{group_pref}`")

                st.markdown(f"**Enquiry Stage:** `{stage.replace('_', ' ').title()}`")

                if reg_status == "interest_registered":
                    st.success(f"**Interest Registered!** Reference: `{enq_dict.get('reference_code') or 'ENQ-CONFIRMED'}`")
                    st.caption("Free & non-binding • A coordinator will prepare your tailored proposal.")
                else:
                    st.info("Registration is free and non-binding.")

                # Actionable modification buttons
                if prog:
                    st.caption("Adjust your enquiry details:")
                    btn_c1, btn_c2, btn_c3 = st.columns(3)
                    with btn_c1:
                        if st.button("Change destination", key="btn_edit_dest", use_container_width=True):
                            st.session_state.pending_prompt = "I would like to change my destination preference."
                    with btn_c2:
                        if st.button("Change timing", key="btn_edit_time", use_container_width=True):
                            st.session_state.pending_prompt = "I would like to change my travel timing."
                    with btn_c3:
                        if st.button("View summary", key="btn_edit_summary", use_container_width=True):
                            st.session_state.pending_prompt = "Please show me my preference summary."

            # Registration of interest action box
            if reg_status != "interest_registered" and prog:
                with st.container(border=True):
                    st.markdown("#### Ready to Register Interest?")
                    st.caption("Registering interest allows a wellness coordinator to review your preferences and share confirmed partner itineraries once dates are announced.")
                    if st.button("Register My Interest (Free & Non-Binding)", key="reg_interest_cta", use_container_width=True):
                        st.session_state.pending_prompt = "Yes, please register my interest."

            # Programme FAQs (Only relevant to active programme)
            with st.expander("Programme Frequently Asked Questions", expanded=False):
                if prog == "hayat_100":
                    st.markdown("**Q: Is HAYAT-100 a medical programme?**")
                    st.caption("No. It is a wellness and healthy-ageing retreat concept. Any included health assessments are non-clinical wellness reviews.")
                    st.markdown("**Q: Does HAYAT-100 guarantee living to 100?**")
                    st.caption("No. The name reflects an aspiration towards longevity; it does not promise a specific lifespan or health outcome.")
                    st.markdown("**Q: How much does it cost?**")
                    st.caption("All retreats are individually curated without a fixed package rate. Pricing depends on your preferred destination and customisation.")
                elif prog == "aafiya":
                    st.markdown("**Q: Is AAfiya exclusively for women?**")
                    st.caption("Yes. AAfiya is designed specifically as a women-focused retreat experience.")
                    st.markdown("**Q: Do I need to be physically fit?**")
                    st.caption("No particular fitness level is required; activities welcome all levels from beginners to active individuals.")
                    st.markdown("**Q: Are Pilates and yoga included?**")
                    st.caption("Pilates, yoga, and guided movement are proposed core activities, finalized based on retreat facility partners.")
                elif prog == "ffounders":
                    st.markdown("**Q: Is FFounders a business conference?**")
                    st.caption("No. It is primarily a fitness and wellness retreat for leaders, with curated peer connections as an organic secondary element.")
                    st.markdown("**Q: Can leadership teams attend together?**")
                    st.caption("Yes. Co-founders and corporate teams can express interest in participating together.")
                else:
                    st.markdown("**Q: How long does each programme last?**")
                    st.caption("Each signature programme is designed as a seven-day experience (five retreat days + two travel days).")
                    st.markdown("**Q: Where will the retreats take place?**")
                    st.caption("Potential destinations under exploration include Spain, Japan, the United States, the UAE, Singapore, and India.")
                    st.markdown("**Q: How is pricing determined?**")
                    st.caption("Each retreat is individually curated; there is no fixed package price.")

        else:
            # -------------------------------------------------------------
            # International Medical Travel Workflow Panel (Preserved)
            # -------------------------------------------------------------
            facts = _fact_values(st.session_state.get("profile_summary"))
            progress = st.session_state.get("consultation_progress") or {}
            handoff = st.session_state.get("coordinator_handoff")

            st.subheader("Medical Consultation Intake")

            with st.expander("Appendix A Preferences", expanded=True):
                st.caption("Non-clinical consultation preferences collected in this session.")
                if facts:
                    for k, v in facts.items():
                        if k not in ("contact", "name", "phone_number", "service_category"):
                            st.write(f"**{k.replace('_', ' ').title()}:** {v}")
                else:
                    st.caption("No medical preferences collected yet.")

            with st.expander("CP-5 Consent & Data Transmission Gate", expanded=True):
                st.caption("Transmission to CRM / matching engine occurs only with explicit affirmative confirmation.")
                consent_granted = progress.get("consent_granted", False)
                st.write(f"**CP-5 Consent Granted:** {'Yes' if consent_granted else 'Pending Review'}")
                if not consent_granted:
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("Confirm & Agree to Share", key="grant_cp5_med", use_container_width=True):
                            st.session_state.pending_prompt = "Yes, I confirm and agree to share these details with Trawellcare's CRM and matching engine."
                    with c2:
                        if st.button("Decline / Defer Consent", key="defer_cp5_med", use_container_width=True):
                            st.session_state.pending_prompt = "Not right now, I need to think about it first."

            with st.expander("Coordinator Handoff Status", expanded=True):
                current_status = handoff.get("status") if handoff else (progress.get("request_status") or "awaiting_intake")
                st.write(f"**Status:** `{current_status}`")
                if handoff and handoff.get("assigned_coordinator_name"):
                    st.write(f"**Coordinator:** {handoff['assigned_coordinator_name']} ({handoff.get('coordinator_role')})")
                if handoff and handoff.get("appointment_details"):
                    st.success(f"**Appointment:** {handoff['appointment_details'].get('appointment_time')} at {handoff['appointment_details'].get('provider_or_clinic')}")
                else:
                    st.info("No appointment is booked autonomously. Your coordinator handles all arrangements.")

            with st.expander("Policy Addendum 1.1 Notice", expanded=False):
                st.warning("Policy Addendum 1.1 Status: Awaiting Formal Sign-Off")
                st.caption("In-chat contact data collection is disabled for compliance.")


# =============================================================================
# Chat Input & Turn Execution
# =============================================================================
prompt = st.chat_input("Message Hayat" if st.session_state.locale == "en" else "اكتب رسالتك إلى حياة")
prompt = prompt or st.session_state.pop("pending_prompt", None)

if prompt and st.session_state.conversation_id:
    headers = _headers()
    payload = {
        "conversation_id": st.session_state.conversation_id,
        "message": prompt,
        "client_message_id": str(uuid.uuid4()),
    }
    response = api.post(f"{base_url}/v1/chat", headers=headers, json=payload, timeout=30)
    if response.status_code == 422 and "client_message_id" in _validation_detail(response):
        response = api.post(
            f"{base_url}/v1/chat",
            headers=headers,
            json={k: v for k, v in payload.items() if k != "client_message_id"},
            timeout=30,
        )
    if response.ok:
        data = response.json()
        clean_reply = _clean_content(data.get("reply") or data.get("answer", ""))
        st.session_state.messages.extend(
            [{"role": "user", "content": prompt}, {"role": "assistant", "content": clean_reply}]
        )
        st.session_state.suggestions = data.get("suggested_actions", data.get("suggestions", []))
        st.session_state.consultation_progress = data.get("consultation_progress")
        st.session_state.next_action = data.get("next_action")
        st.session_state.profile_summary = data.get("persona_profile") or data.get("profile_summary", {})
        if data.get("coordinator_handoff"):
            st.session_state.coordinator_handoff = data["coordinator_handoff"]
        if data.get("programme_enquiry"):
            st.session_state.programme_enquiry = data["programme_enquiry"]
        if data.get("service_category"):
            st.session_state.service_category = data["service_category"]
        if data.get("escalation_required"):
            st.warning(f"Human follow-up recommended: {data['escalation_reason']}")
        st.rerun()
    else:
        st.error(f"Could not send message: {_validation_detail(response)}")
