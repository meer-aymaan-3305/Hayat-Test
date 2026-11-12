"""Hayat chat client for Streamlit.

Laid out like a modern assistant: one rounded composer with attach and voice built in,
your messages on the right, Hayat's replies as clean text with a listen button, suggested
next steps as pills, and the three signature programmes on the welcome screen. Everything
else (the intake flow, guardrails, the signup handoff, storage) happens in the backend.
Add ?debug=1 to the page address to reveal a connection check for the project team.
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

st.set_page_config(page_title="Hayat", page_icon="🌿", layout="centered", initial_sidebar_state="collapsed")
st.markdown(
    """
    <style>
      header[data-testid="stHeader"], #MainMenu, footer, [data-testid="stToolbar"],
      [data-testid="stDecoration"], [data-testid="stSidebar"],
      [data-testid="collapsedControl"] { display: none !important; }
      .block-container { padding-top: 1rem; padding-bottom: 7rem; max-width: 760px; }
      html, body, [class*="css"] { font-family: -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }

      /* top bar */
      .brand { font-size: 1.25rem; font-weight: 650; color: #111827; letter-spacing: -0.01em; }
      .brand span { color: #0f766e; }

      /* messages: yours on the right in a soft bubble, Hayat's as plain text */
      [data-testid="stChatMessage"] { background: transparent; padding: .35rem 0; gap: .7rem; }
      [data-testid="stChatMessage"] p { line-height: 1.62; font-size: 1rem; margin-bottom: .25rem; }
      [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) { flex-direction: row-reverse; }
      [data-testid="stChatMessageAvatarUser"] { display: none; }
      [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"] {
        background: #f3f4f6; border-radius: 20px; padding: .55rem 1rem; width: fit-content; max-width: 80%;
      }
      [data-testid="stChatMessageAvatarAssistant"] { background: #ecfdf5; color: #0f766e; }

      /* pills for suggested steps and programmes */
      .stButton > button {
        border-radius: 999px; border: 1px solid #e5e7eb; background: #ffffff; color: #1f2937;
        padding: .3rem 1rem; font-size: .88rem; font-weight: 500; box-shadow: none; min-height: 0;
      }
      .stButton > button:hover { border-color: #0f766e; color: #0f766e; background: #f0fdfa; }
      /* small ghost icon buttons under a reply */
      [class*="st-key-listen_"] button {
        border: none; background: transparent; color: #6b7280; padding: .1rem .5rem; font-size: .8rem;
      }
      [class*="st-key-listen_"] button:hover { background: #f3f4f6; color: #111827; }
      /* welcome cards */
      [class*="st-key-card_"] button {
        border-radius: 16px; min-height: 5.2rem; text-align: left; padding: .8rem 1rem; white-space: normal;
        border: 1px solid #e5e7eb; line-height: 1.35;
      }
      /* composer */
      [data-testid="stChatInput"] { border-radius: 28px; border: 1px solid #e5e7eb; box-shadow: 0 2px 14px rgba(0,0,0,.06); }
      .caption-muted { color: #9ca3af; font-size: .76rem; margin: .55rem 0 .25rem; }
      .ref { font-size: .8rem; color: #4b5563; background: #f3f4f6; border-radius: 12px; padding: .4rem .8rem; display: inline-block; margin-top: .4rem; }
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
    "reference": None, "pending_audio": None, "pending_files": [], "documents": [],
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


def _refresh_messages() -> None:
    history = api.get(
        f"{base_url}/v1/conversations/{st.session_state.conversation_id}/messages",
        headers=_headers(), timeout=30,
    )
    if history.ok:
        st.session_state.messages = [
            {"role": m["role"], "content": m["content"], "id": m.get("id")}
            for m in history.json().get("messages", [])
        ]


# ---- top bar ---------------------------------------------------------------------------------
left, right = st.columns([3, 2], vertical_alignment="center")
left.markdown('<div class="brand">Hayat <span>·</span> trawellcare</div>', unsafe_allow_html=True)
with right:
    toggle_col, link_col = st.columns([1.2, 1])
    toggle_col.toggle("Read aloud", key="auto_voice")
    signup_url = get_settings().signup_url
    if signup_url:
        link_col.link_button("Sign up / log in", signup_url, use_container_width=True)

# ---- the conversation ------------------------------------------------------------------------
messages = st.session_state.messages
for index, message in enumerate(messages):
    avatar = "🌿" if message["role"] == "assistant" else None
    with st.chat_message(message["role"], avatar=avatar):
        st.write(message["content"])
        if message["role"] == "assistant" and message.get("id") and not st.session_state.get("awaiting_reply"):
            if st.button("🔊 Listen", key=f"listen_{index}"):
                st.session_state.pending_audio = _speak(message["id"])
                st.rerun()

if st.session_state.pending_audio:
    st.audio(st.session_state.pending_audio, format="audio/wav", autoplay=True)
    st.session_state.pending_audio = None

if st.session_state.get("awaiting_reply"):
    pending = st.session_state.awaiting_reply
    with st.chat_message("assistant", avatar="🌿"):
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
        messages.append({"role": "assistant", "content": data.get("reply") or data.get("answer", ""), "id": message_id})
        st.session_state.chips = [
            action.get("label") for action in (data.get("suggestions") or data.get("suggested_actions") or [])
            if action.get("label")
        ]
        st.session_state.reference = data.get("reference") or st.session_state.reference
        st.session_state.pending_audio = audio
        if data.get("ai_status") == "unavailable":
            st.session_state.ai_notice = True
    else:
        messages.append({"role": "assistant", "content": "Sorry, something went wrong on my side. Please try again."})
    st.rerun()

# ---- documents waiting for the visitor's consent -----------------------------------------------
if st.session_state.pending_files:
    names = ", ".join(f["name"] for f in st.session_state.pending_files)
    with st.container(border=True):
        st.markdown(f"**{names}**")
        st.caption(
            "Hayat will read this only in this chat, to answer your questions about it. She can tell you "
            "what it says, but she never interprets medical results."
        )
        allow, cancel, _ = st.columns([1.3, 1, 3])
        if allow.button("Allow and upload", key="allow_upload", type="primary"):
            with st.spinner("Reading your document..."):
                for item in st.session_state.pending_files:
                    sent = api.post(
                        f"{base_url}/v1/conversations/{st.session_state.conversation_id}/documents",
                        headers=_headers(),
                        files={"file": (item["name"], item["data"], item["type"])},
                        data={"consent": "true"},
                        timeout=120,
                    )
                    if sent.ok:
                        st.session_state.documents.append(item["name"])
                    else:
                        st.error(f"{item['name']}: {_detail(sent)}")
            st.session_state.pending_files = []
            st.session_state.chips = []
            _refresh_messages()
            st.rerun()
        if cancel.button("Cancel", key="cancel_upload"):
            st.session_state.pending_files = []
            st.rerun()

# ---- welcome cards, then suggested next steps ---------------------------------------------------
only_greeting = len(messages) <= 1
if only_greeting and not st.session_state.get("awaiting_reply"):
    st.markdown('<div class="caption-muted">Start with one of our signature programmes</div>', unsafe_allow_html=True)
    for column, (name, tagline, message) in zip(st.columns(3), PROGRAMMES):
        if column.button(f"**{name}**\n\n{tagline}", key=f"card_{name}", use_container_width=True):
            _send(message)
else:
    if st.session_state.chips:
        columns = st.columns(len(st.session_state.chips))
        for index, (column, chip) in enumerate(zip(columns, st.session_state.chips)):
            if column.button(chip, key=f"chip_{len(messages)}_{index}", use_container_width=True):
                _send(chip)
    with st.expander("Signature programmes", expanded=False):
        for column, (name, tagline, message) in zip(st.columns(3), PROGRAMMES):
            if column.button(name, help=tagline, key=f"prog_{name}", use_container_width=True):
                _send(message)

if st.session_state.reference:
    st.markdown(
        f'<span class="ref">Your reference <b>{st.session_state.reference}</b> · quote it when you sign up '
        "so the team can find your chat</span>",
        unsafe_allow_html=True,
    )

if st.session_state.pop("ai_notice", False):
    st.caption("Hayat's AI service is busy or unavailable right now. Please try again in a minute.")

# ---- composer: text, attach and voice in one place ----------------------------------------------
entry = st.chat_input(
    "Message Hayat",
    accept_file="multiple",
    file_type=["pdf", "docx", "png", "jpg", "jpeg"],
    accept_audio=True,
)
if entry:
    text = (entry.get("text") if hasattr(entry, "get") else getattr(entry, "text", "")) or ""
    files = (entry.get("files") if hasattr(entry, "get") else getattr(entry, "files", [])) or []
    audio = entry.get("audio") if hasattr(entry, "get") else getattr(entry, "audio", None)
    if files:
        st.session_state.pending_files = [
            {"name": f.name, "data": f.getvalue(), "type": f.type or "application/octet-stream"} for f in files
        ]
    if audio is not None:
        transcribed = api.post(
            f"{base_url}/v1/voice/transcribe",
            headers=_headers(),
            files={"file": ("voice.wav", audio.getvalue(), "audio/wav")},
            data={"conversation_id": st.session_state.conversation_id},
            timeout=60,
        )
        if transcribed.ok and transcribed.json().get("transcript"):
            st.session_state.voice_turn = True
            _send(transcribed.json()["transcript"])
        elif transcribed.ok:
            st.warning("I could not hear anything in that recording. Please try again.")
        else:
            st.error(_detail(transcribed))
    elif text.strip():
        _send(text.strip())
    elif files:
        st.rerun()

# ---- for the project team only: ?debug=1 -----------------------------------------------------
if st.query_params.get("debug") == "1" and os.getenv("HAYAT_CLOUD") == "1":
    with st.expander("AI connection check"):
        if st.button("Check now"):
            from hayat_backend.cloud_bootstrap import check_ai_connection

            for label, ok, detail in check_ai_connection():
                st.write(f"{'✅' if ok else '❌'} {label}: {detail}")
