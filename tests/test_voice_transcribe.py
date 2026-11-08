"""POST /v1/voice/transcribe: dictation only, nothing stored, chat pipeline untouched."""

import pytest
from fastapi.testclient import TestClient

from hayat_backend import chat_service, main
from hayat_backend.config import Settings
from hayat_backend.main import create_app
from hayat_backend.memory_store import MemoryStore
from hayat_backend.speech import EmptyTranscriptError, SpeechError


class FakeSTT:
    def __init__(self, transcript="I want a wellness retreat", error=None):
        self.transcript = transcript
        self.error = error
        self.filenames: list[str] = []

    async def transcribe(self, audio, filename, content_type):
        self.filenames.append(filename)
        if self.error:
            raise self.error
        return self.transcript, "en"


def _client(tmp_path, monkeypatch, stt, store=None, **kw):
    settings = Settings(app_env="test", knowledge_dir=str(tmp_path / "k"), **kw)
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "create_stt", lambda _s: stt)
    return TestClient(create_app(store=store or MemoryStore()))


def _session(client):
    s = client.post("/v1/sessions/guest", json={"locale": "en"}).json()
    c = client.post("/v1/conversations", json={"guest_session_id": s["session_id"]},
                    headers={"X-Session-Token": s["session_token"]}).json()
    return c, {"X-Session-ID": s["session_id"], "X-Session-Token": s["session_token"]}


def _post(client, conv, headers, name="../x.mp3", data=b"audio", ctype="audio/mpeg"):
    return client.post("/v1/voice/transcribe", files={"file": (name, data, ctype)},
                       data={"conversation_id": conv["id"]}, headers=headers)


def test_returns_only_the_transcript_and_stores_nothing(tmp_path, monkeypatch):
    store = MemoryStore()
    stt = FakeSTT()
    c = _client(tmp_path, monkeypatch, stt, store)

    async def boom(*_a, **_k):
        raise AssertionError("the chat pipeline must not run")

    monkeypatch.setattr(chat_service.ChatService, "respond", boom)
    conv, headers = _session(c)
    from uuid import UUID
    session_id = UUID(headers["X-Session-ID"])
    before = len(store.get_conversation(session_id, UUID(conv["id"])).messages)
    res = _post(c, conv, headers)
    assert res.status_code == 200
    assert res.json() == {"transcript": stt.transcript}
    assert stt.filenames == ["audio.mp3"]  # visitor filename never forwarded
    assert len(store.get_conversation(session_id, UUID(conv["id"])).messages) == before


def test_requires_conversation_ownership(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch, FakeSTT())
    conv, _ = _session(c)
    _, other_headers = _session(c)
    assert _post(c, conv, other_headers).status_code == 403
    assert _post(c, conv, {"X-Session-ID": other_headers["X-Session-ID"], "X-Session-Token": "bad"}).status_code == 403


def test_size_type_and_length_limits(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch, FakeSTT(), max_upload_mb=1)
    conv, headers = _session(c)
    assert _post(c, conv, headers, data=b"").status_code == 400
    assert _post(c, conv, headers, data=b"a" * (1024 * 1024 + 1)).status_code == 413
    assert _post(c, conv, headers, name="a.pdf", ctype="application/pdf").status_code == 415
    long_c = _client(tmp_path, monkeypatch, FakeSTT("a" * 8_001))
    conv, headers = _session(long_c)
    assert _post(long_c, conv, headers).status_code == 422
    ok_c = _client(tmp_path, monkeypatch, FakeSTT("a" * 8_000))
    conv, headers = _session(ok_c)
    assert _post(ok_c, conv, headers).status_code == 200


def test_silent_recording_returns_empty_transcript(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch, FakeSTT(error=EmptyTranscriptError("empty")))
    conv, headers = _session(c)
    res = _post(c, conv, headers)
    assert res.status_code == 200 and res.json() == {"transcript": ""}


def test_provider_failure_answers_503(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch, FakeSTT(error=SpeechError("down")))
    conv, headers = _session(c)
    assert _post(c, conv, headers).status_code == 503


def test_voice_chat_still_503_on_silence(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch, FakeSTT(error=EmptyTranscriptError("empty")))
    conv, headers = _session(c)
    res = c.post("/v1/voice/chat", files={"file": ("a.mp3", b"audio", "audio/mpeg")},
                 data={"conversation_id": conv["id"]}, headers={**headers, "X-Visitor": "guest"})
    assert res.status_code == 503
