"""Hayat chat client for Streamlit.

Only the conversation is shown. Everything else (the intake flow, guardrails, the signup
handoff, storage) happens in the backend. Add ?debug=1 to the page address to reveal a small
connection check for the project team.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import jwt
import requests
import streamlit as st

from hayat_backend.config import get_settings

st.set_page_config(
    page_title="Hayat",
    page_icon="💬",
    layout="centered",
    initial_sidebar_state="collapsed",
)
st.markdown(
    """
    <style>
      header[data-testid="stHeader"], #MainMenu, footer,
      [data-testid="stToolbar"], [data-testid="stDecoration"],
      [data-testid="stSidebar"], [data-testid="collapsedControl"] { display: none !important; }
      .block-container { padding-top: 1.2rem; max-width: 760px; }
    </style>
    """,
    unsafe_allow_html=True,
)

base_url = os.getenv("HAYAT_API_URL", "http://127.0.0.1:2005")


def _demo_client() -> requests.Session:
    """The API only accepts service callers, so this page signs in as one."""
    session = requests.Session()
    secret = get_settings().jwt_system_secret
    if secret:
        claims = {"sub": "system:streamlit-demo", "exp": datetime.now(UTC) + timedelta(hours=12)}
        session.headers["X-Service-Token"] = jwt.encode(claims, secret.get_secret_value(), algorithm="HS256")
    return session


api = _demo_client()


def _detail(response: requests.Response) -> str:
    try:
        detail = response.json().get("detail", "The service returned a safe error.")
        return "; ".join(str(item.get("msg", item)) for item in detail) if isinstance(detail, list) else str(detail)
    except ValueError:
        return "The service returned a safe error."


def _headers() -> dict[str, str]:
    return {"X-Session-ID": st.session_state.session_id, "X-Session-Token": st.session_state.token}


def _visitor_hour() -> int:
    """Hour of day from the visitor's browser, used only to pick the greeting."""
    try:
        return datetime.now(ZoneInfo(st.context.timezone)).hour
    except Exception:
        return datetime.now().hour


for key, default in {
    "session_id": None, "token": None, "conversation_id": None, "messages": [],
    "pending_audio": None, "mic_round": 0,
}.items():
    st.session_state.setdefault(key, default)


def _start_session() -> None:
    response = api.post(f"{base_url}/v1/sessions/guest", json={"locale": "en"}, timeout=15)
    if not response.ok:
        st.error(f"Could not start the chat: {_detail(response)}")
        return
    data = response.json()
    st.session_state.session_id, st.session_state.token = data["session_id"], data["session_token"]
    conversation = api.post(
        f"{base_url}/v1/conversations",
        headers={"X-Session-Token": st.session_state.token, "X-Client-Hour": str(_visitor_hour())},
        json={"guest_session_id": st.session_state.session_id},
        timeout=15,
    )
    if not conversation.ok:
        st.error(f"Could not start the chat: {_detail(conversation)}")
        return
    body = conversation.json()
    st.session_state.conversation_id = body["id"]
    st.session_state.messages = [body["greeting"]] if body.get("greeting") else []
    st.rerun()


if st.session_state.conversation_id is None:
    _start_session()
    st.stop()

# ---- the conversation ------------------------------------------------------------------------
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.write(message["content"])

if st.session_state.pending_audio:
    st.audio(st.session_state.pending_audio, format="audio/wav", autoplay=True)
    st.session_state.pending_audio = None

# Voice: speech is turned into text and then goes through the normal chat path.
recording = st.audio_input("🎤", key=f"mic_{st.session_state.mic_round}", label_visibility="collapsed")
if recording is not None:
    transcribed = api.post(
        f"{base_url}/v1/voice/transcribe",
        headers=_headers(),
        files={"file": ("voice.wav", recording.getvalue(), "audio/wav")},
        data={"conversation_id": st.session_state.conversation_id},
        timeout=60,
    )
    st.session_state.mic_round += 1  # a fresh recorder for the next message
    if transcribed.ok and transcribed.json().get("transcript"):
        st.session_state.pending_prompt = transcribed.json()["transcript"]
        st.session_state.voice_turn = True
        st.rerun()
    elif transcribed.ok:
        st.warning("I could not hear anything in that recording. Please try again.")
    else:
        st.error(f"Could not process the recording: {_detail(transcribed)}")

prompt = st.chat_input("Message Hayat")
prompt = prompt or st.session_state.pop("pending_prompt", None)

if prompt:
    payload = {
        "conversation_id": st.session_state.conversation_id,
        "message": prompt,
        "client_message_id": str(uuid.uuid4()),
    }
    response = api.post(f"{base_url}/v1/chat", headers=_headers(), json=payload, timeout=60)
    if response.ok:
        data = response.json()
        reply = data.get("reply") or data.get("answer", "")
        st.session_state.messages.extend(
            [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}]
        )
        if st.session_state.pop("voice_turn", False):
            message_id = (data.get("assistant_message") or {}).get("id")
            if message_id:
                spoken = api.post(
                    f"{base_url}/v1/voice/synthesize",
                    headers=_headers(),
                    json={"conversation_id": st.session_state.conversation_id, "message_id": message_id},
                    timeout=60,
                )
                if spoken.ok:
                    st.session_state.pending_audio = spoken.content
        if data.get("ai_status") == "unavailable":
            st.session_state.ai_notice = True
        st.rerun()
    else:
        st.error(f"Could not send the message: {_detail(response)}")

if st.session_state.pop("ai_notice", False):
    st.caption("Hayat's AI service is busy or unavailable right now. Please try again in a minute.")

# ---- for the project team only: ?debug=1 -----------------------------------------------------
if st.query_params.get("debug") == "1" and os.getenv("HAYAT_CLOUD") == "1":
    with st.expander("AI connection check"):
        if st.button("Check now"):
            from hayat_backend.cloud_bootstrap import check_ai_connection

            for label, ok, detail in check_ai_connection():
                st.write(f"{'✅' if ok else '❌'} {label}: {detail}")
