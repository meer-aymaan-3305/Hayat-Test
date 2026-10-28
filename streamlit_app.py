"""Internal-only Streamlit client for exercising the public API."""

import os
import re
import uuid
import requests
import streamlit as st


def _legacy_initial_actions(locale: str) -> list[dict[str, str]]:
    if locale == "ar":
        return [
            {"action_id": "medical_treatment", "label": "علاج طبي", "payload": "I am interested in medical treatment."},
            {"action_id": "wellness_programme", "label": "برنامج عافية", "payload": "I am interested in a wellness programme."},
        ]
    return [
        {"action_id": "medical_treatment", "label": "Medical treatment", "payload": "I am interested in medical treatment."},
        {"action_id": "wellness_programme", "label": "Wellness programme", "payload": "I am interested in a wellness programme."},
    ]


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


st.set_page_config(page_title="Hayat internal tester")
st.title("Hayat internal tester")
base_url = st.text_input("API URL", os.getenv("HAYAT_API_URL", "http://127.0.0.1:8000"))

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

st.session_state.locale = st.selectbox("Language", ["en", "ar"], format_func=lambda value: "English" if value == "en" else "العربية")
with st.expander("Restore an existing guest conversation"):
    restore_session_id = st.text_input("Session ID", key="restore_session_id")
    restore_token = st.text_input("Session token", type="password", key="restore_token")
    restore_conversation_id = st.text_input("Conversation ID", key="restore_conversation_id")
    if st.button("Restore conversation"):
        headers = {"X-Session-ID": restore_session_id, "X-Session-Token": restore_token}
        response = requests.get(
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
            st.rerun()
        else:
            st.error("Could not restore that conversation.")

if st.button("Start guest session"):
    # Clean previous conversation state to prevent cross-session leakage
    st.session_state.profile_summary = {}
    st.session_state.consultation_progress = None
    st.session_state.consultation_details = {}
    st.session_state.lead_saved = False
    st.session_state.phone_verified = False
    st.session_state.consent_recorded = False
    st.session_state.otp_challenge_id = None
    st.session_state.consultation_request = None
    st.session_state.messages = []
    st.session_state.suggestions = []

    response = requests.post(
        f"{base_url}/v1/sessions/guest",
        json={"locale": st.session_state.locale},
        timeout=10,
    )
    if response.ok:
        data = response.json()
        st.session_state.session_id = data["session_id"]
        st.session_state.token = data["session_token"]
        conversation = requests.post(
            f"{base_url}/v1/conversations",
            headers={"X-Session-Token": st.session_state.token},
            json={"guest_session_id": st.session_state.session_id},
            timeout=10,
        )
        if conversation.ok:
            conversation_data = conversation.json()
            st.session_state.conversation_id = conversation_data["id"]
            greeting_message = conversation_data.get("greeting")
            if greeting_message:
                st.session_state.messages = [greeting_message]
            else:
                history = requests.get(
                    f"{base_url}/v1/conversations/{st.session_state.conversation_id}/messages",
                    headers={
                        "X-Session-ID": st.session_state.session_id,
                        "X-Session-Token": st.session_state.token,
                    },
                    timeout=10,
                )
                st.session_state.messages = (
                    history.json().get("messages", []) if history.ok else []
                )
            st.session_state.suggestions = conversation_data.get(
                "suggested_actions",
                conversation_data.get("suggestions", [])
                or _legacy_initial_actions(st.session_state.locale),
            )
        else:
            st.error(f"Could not create conversation: {_validation_detail(conversation)}")
    else:
        st.error(f"Could not start a test session: {_validation_detail(response)}")

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.write(_clean_content(message["content"]))

if st.session_state.conversation_id:
    latest_progress = st.session_state.get("consultation_progress")
    if latest_progress and latest_progress.get("missing_fields") is not None:
        collected = len(latest_progress.get("collected_fields", []))
        total = len(latest_progress.get("required_fields", []))
        st.caption(f"Consultation progress: {collected}/{total} required details collected")
    if st.session_state.suggestions:
        st.caption("Suggested next steps" if st.session_state.locale == "en" else "الخطوات المقترحة")
        for suggestion in st.session_state.suggestions:
            if st.button(suggestion["label"], key=f"suggestion_{suggestion['action_id']}"):
                st.session_state.pending_prompt = suggestion["payload"]

    facts = _fact_values(st.session_state.get("profile_summary"))
    progress = st.session_state.get("consultation_progress") or {}
    with st.expander("Consultation profile", expanded=False):
        st.caption(
            "Hayat populates this profile from the conversation. Continue speaking "
            "naturally; no manual form is required."
        )
        if facts:
            for field, value in facts.items():
                st.write(f"**{field.replace('_', ' ').title()}:** {value}")
        else:
            st.caption("No consultation facts have been collected yet.")
        if progress:
            st.caption(
                f"Collected {len(progress.get('collected_fields', []))} of "
                f"{len(progress.get('required_fields', []))} required details"
            )
            if progress.get("missing_fields"):
                st.caption("Still needed: " + ", ".join(progress["missing_fields"]))
            st.write(
                f"Phone verified: {'yes' if progress.get('phone_verified') else 'no'}; "
                f"Consent: {'yes' if progress.get('consent_granted') else 'no'}"
            )

        if facts.get("phone_number") and not progress.get("phone_verified"):
            if st.button("Start phone verification", key="start_phone_verification"):
                otp_response = requests.post(
                    f"{base_url}/v1/consultations/otp/start",
                    headers=_headers(),
                    json={
                        "conversation_id": st.session_state.conversation_id,
                        "phone_number": str(facts["phone_number"]),
                    },
                    timeout=15,
                )
                if otp_response.ok:
                    st.session_state.otp_challenge_id = otp_response.json()["challenge_id"]
                    st.info("Verification started. Enter the code sent by the configured provider.")
                else:
                    st.error(f"Could not start verification: {_validation_detail(otp_response)}")

        if st.session_state.otp_challenge_id and not st.session_state.phone_verified:
            code = st.text_input("Verification code", type="password", key="verification_code")
            if st.button("Verify phone", key="verify_phone"):
                verify_response = requests.post(
                    f"{base_url}/v1/consultations/otp/verify",
                    headers=_headers(),
                    json={
                        "conversation_id": st.session_state.conversation_id,
                        "challenge_id": st.session_state.otp_challenge_id,
                        "code": code,
                    },
                    timeout=15,
                )
                if verify_response.ok:
                    st.session_state.phone_verified = True
                    st.success("Phone verified.")
                    st.rerun()
                else:
                    st.error(f"Phone verification failed: {_validation_detail(verify_response)}")

        if progress.get("request_status"):
            st.info(
                f"Consultation request status: {progress['request_status']}. "
                "Only an authorized coordinator can confirm an appointment."
            )

prompt = st.chat_input("Message Hayat" if st.session_state.locale == "en" else "اكتب رسالتك إلى حياة")
prompt = prompt or st.session_state.pop("pending_prompt", None)
if prompt and st.session_state.conversation_id:
    headers = {
        "X-Session-ID": st.session_state.session_id,
        "X-Session-Token": st.session_state.token,
    }
    payload = {
        "conversation_id": st.session_state.conversation_id,
        "message": prompt,
        "client_message_id": str(uuid.uuid4()),
    }
    response = requests.post(
        f"{base_url}/v1/chat",
        headers=headers,
        json=payload,
        timeout=30,
    )
    if response.status_code == 422 and "client_message_id" in _validation_detail(response):
        response = requests.post(
            f"{base_url}/v1/chat",
            headers=headers,
            json={key: value for key, value in payload.items() if key != "client_message_id"},
            timeout=30,
        )
    if response.ok:
        data = response.json()
        clean_reply = _clean_content(data.get("reply") or data.get("answer", ""))
        st.session_state.messages.extend(
            [{"role": "user", "content": prompt}, {"role": "assistant", "content": clean_reply}]
        )
        st.session_state.suggestions = data.get(
            "suggested_actions", data.get("suggestions", [])
        )
        st.session_state.consultation_progress = data.get("consultation_progress")
        st.session_state.profile_summary = data.get("persona_profile") or data.get("profile_summary", {})
        if data["escalation_required"]:
            st.warning(f"Human follow-up recommended: {data['escalation_reason']}")
        st.rerun()
    else:
        st.error(f"Could not send message: {_validation_detail(response)}")
