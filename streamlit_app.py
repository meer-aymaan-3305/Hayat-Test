"""Hayat chat client for Streamlit.

A small, calm page: the conversation, the three signature programmes, next steps that follow
from what was just said, voice, and document upload. Everything else (the intake flow,
guardrails, the signup handoff, storage) happens in the backend. Add ?debug=1 to the page
address to reveal a connection check for the project team.
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

st.set_page_config(page_title="Hayat", page_icon="💬", layout="centered", initial_sidebar_state="collapsed")
st.markdown(
    """
    <style>
      header[data-testid="stHeader"], #MainMenu, footer, [data-testid="stToolbar"],
      [data-testid="stDecoration"], [data-testid="stSidebar"],
      [data-testid="collapsedControl"] { display: none !important; }
      .block-container { padding-top: 1.4rem; padding-bottom: 6rem; max-width: 740px; }
      .brand { font-size: 1.55rem; font-weight: 700; letter-spacing: -0.01em; color: #0f766e; line-height: 1.1; }
      .brand small { display: block; font-size: .8rem; font-weight: 400; color: #78716c; letter-spacing: 0; margin-top: .15rem; }
      .section-label { font-size: .72rem; text-transform: uppercase; letter-spacing: .08em; color: #a8a29e; margin: .9rem 0 .35rem; }
      /* pills */
      .stButton > button {
        border-radius: 999px; border: 1px solid #e7e5e4; background: #ffffff; color: #292524;
        padding: .28rem .95rem; font-size: .86rem; font-weight: 500; box-shadow: none; min-height: 0;
      }
      .stButton > button:hover { border-color: #0f766e; color: #0f766e; background: #f0fdfa; }
      /* messages */
      [data-testid="stChatMessage"] { background: transparent; border-radius: 18px; padding: .55rem .8rem; }
      [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) { background: #e6f4f1; }
      [data-testid="stChatMessage"] p { line-height: 1.55; margin-bottom: .2rem; }
      .ref { font-size: .8rem; color: #57534e; background: #f5f5f4; border-radius: 10px; padding: .35rem .7rem; display: inline-block; }
      [data-testid="stPopover"] button { border-radius: 999px; }
    </style>
    """,
    unsafe_allow_html=True,
)

base_url = os.getenv("HAYAT_API_URL", "http://127.0.0.1:2005")

PROGRAMMES = [
    ("HAYAT-100", "Longevity and healthy ageing", "Tell me about HAYAT-100"),
    ("AAfiya", "Women's fitness and wellness", "Tell me about AAfiya"),
    ("FFounders", "Executive fitness and wellness", "Tell me about FFounders"),
]


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
    "session_id": None, "token": None, "conversation_id": None, "messages": [], "chips": [],
    "reference": None, "pending_audio": None, "mic_round": 0, "documents": [], "seen_uploads": [],
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


def _speak(message_id: str | None) -> bytes | None:
    if not message_id:
        return None
    spoken = api.post(
        f"{base_url}/v1/voice/synthesize",
        headers=_headers(),
        json={"conversation_id": st.session_state.conversation_id, "message_id": message_id},
        timeout=60,
    )
    return spoken.content if spoken.ok else None


def _send(text: str) -> None:
    """Queue a visitor message; it is shown at once and answered on the next run."""
    st.session_state.messages.append({"role": "user", "content": text})
    st.session_state.awaiting_reply = text
    st.session_state.chips = []
    st.rerun()


# ---- header ---------------------------------------------------------------------------------
head, voice = st.columns([4, 1.4], vertical_alignment="center")
head.markdown('<div class="brand">Hayat<small>trawellcare AI concierge for health and wellness</small></div>', unsafe_allow_html=True)
voice.toggle("🔊 Voice replies", key="auto_voice")

st.markdown('<div class="section-label">Our signature programmes</div>', unsafe_allow_html=True)
for column, (name, tagline, message) in zip(st.columns(3), PROGRAMMES):
    if column.button(name, help=tagline, use_container_width=True, key=f"prog_{name}"):
        _send(message)

st.divider()

# ---- the conversation -------------------------------------------------------------------------
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.write(message["content"])

if st.session_state.pending_audio:
    st.audio(st.session_state.pending_audio, format="audio/wav", autoplay=True)
    st.session_state.pending_audio = None

if st.session_state.get("awaiting_reply"):
    pending = st.session_state.awaiting_reply
    with st.chat_message("assistant"):
        with st.spinner("Hayat is typing..."):
            response = api.post(
                f"{base_url}/v1/chat",
                headers=_headers(),
                json={
                    "conversation_id": st.session_state.conversation_id,
                    "message": pending,
                    "client_message_id": str(uuid.uuid4()),
                },
                timeout=60,
            )
            data = response.json() if response.ok else {}
            message_id = data.get("message_id")
            voice_turn = st.session_state.pop("voice_turn", False)
            audio = _speak(message_id) if response.ok and (voice_turn or st.session_state.get("auto_voice")) else None
    st.session_state.awaiting_reply = None
    if response.ok:
        st.session_state.messages.append(
            {"role": "assistant", "content": data.get("reply") or data.get("answer", ""), "id": message_id}
        )
        st.session_state.chips = [
            action.get("label") for action in (data.get("suggestions") or data.get("suggested_actions") or [])
            if action.get("label")
        ]
        st.session_state.reference = data.get("reference") or st.session_state.reference
        st.session_state.pending_audio = audio
        if data.get("ai_status") == "unavailable":
            st.session_state.ai_notice = True
    else:
        st.session_state.messages.append(
            {"role": "assistant", "content": "Sorry, something went wrong on my side. Please try again."}
        )
    st.rerun()

# ---- next steps that follow from the last reply, listen, reference ----------------------------
last = st.session_state.messages[-1] if st.session_state.messages else None
if last and last["role"] == "assistant":
    if st.session_state.chips:
        st.markdown('<div class="section-label">Suggested next steps</div>', unsafe_allow_html=True)
        for index, (column, chip) in enumerate(zip(st.columns(len(st.session_state.chips)), st.session_state.chips)):
            if column.button(chip, use_container_width=True, key=f"chip_{len(st.session_state.messages)}_{index}"):
                _send(chip)
    if last.get("id") and st.button("🔊 Listen", key=f"listen_{len(st.session_state.messages)}"):
        st.session_state.pending_audio = _speak(last["id"])
        st.rerun()

if st.session_state.reference:
    st.markdown(
        f'<span class="ref">Your reference: <b>{st.session_state.reference}</b>. Quote it when you sign up '
        "so the team can find your chat.</span>",
        unsafe_allow_html=True,
    )

if st.session_state.pop("ai_notice", False):
    st.caption("Hayat's AI service is busy or unavailable right now. Please try again in a minute.")

# ---- tools: documents and voice ----------------------------------------------------------------
tools_doc, tools_mic, _ = st.columns([1.5, 1.2, 5])
with tools_doc.popover("📎 Document"):
    st.caption(
        "Upload your own document (PDF, Word, PNG or JPG) and Hayat will answer questions about it "
        "in this chat. Hayat explains what it says but never interprets medical results."
    )
    agreed = st.checkbox("I agree that Hayat may read this document in this chat", key="doc_consent")
    upload = st.file_uploader(
        "Choose a file", type=["pdf", "docx", "png", "jpg", "jpeg"], disabled=not agreed,
        label_visibility="collapsed", key="doc_upload",
    )
    if upload is not None and agreed and upload.file_id not in st.session_state.seen_uploads:
        st.session_state.seen_uploads.append(upload.file_id)
        with st.spinner("Reading your document..."):
            sent = api.post(
                f"{base_url}/v1/conversations/{st.session_state.conversation_id}/documents",
                headers=_headers(),
                files={"file": (upload.name, upload.getvalue(), upload.type or "application/octet-stream")},
                data={"consent": "true"},
                timeout=120,
            )
        if sent.ok:
            history = api.get(
                f"{base_url}/v1/conversations/{st.session_state.conversation_id}/messages",
                headers=_headers(), timeout=30,
            )
            if history.ok:
                st.session_state.messages = [
                    {"role": m["role"], "content": m["content"], "id": m.get("id")}
                    for m in history.json().get("messages", [])
                ]
            st.session_state.documents.append(upload.name)
            st.session_state.chips = []
            st.rerun()
        else:
            st.error(_detail(sent))
    for name in st.session_state.documents:
        st.caption(f"📄 {name}")

with tools_mic.popover("🎤 Speak"):
    recording = st.audio_input("Record", key=f"mic_{st.session_state.mic_round}", label_visibility="collapsed")
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
            st.session_state.voice_turn = True
            _send(transcribed.json()["transcript"])
        elif transcribed.ok:
            st.warning("I could not hear anything in that recording. Please try again.")
        else:
            st.error(_detail(transcribed))

prompt = st.chat_input("Message Hayat")
if prompt:
    _send(prompt)

# ---- for the project team only: ?debug=1 -----------------------------------------------------
if st.query_params.get("debug") == "1" and os.getenv("HAYAT_CLOUD") == "1":
    with st.expander("AI connection check"):
        if st.button("Check now"):
            from hayat_backend.cloud_bootstrap import check_ai_connection

            for label, ok, detail in check_ai_connection():
                st.write(f"{'✅' if ok else '❌'} {label}: {detail}")
