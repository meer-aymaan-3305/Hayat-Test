"""Voice, knowledge-document ingestion and visitor-attachment gate tests."""

from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from hayat_backend import main
from hayat_backend.config import Settings
from hayat_backend.main import create_app
from hayat_backend.memory_store import MemoryStore


def _client(tmp_path, **kwargs):
    settings = Settings(app_env="test", knowledge_dir=str(tmp_path / "knowledge"), **kwargs)
    import hayat_backend.main as m
    orig = m.get_settings
    m.get_settings = lambda: settings
    try:
        yield TestClient(create_app(store=MemoryStore()))
    finally:
        m.get_settings = orig


@pytest.fixture
def client(tmp_path):
    yield from _client(tmp_path)


def _session(client):
    s = client.post("/v1/sessions/guest", json={"locale": "en"}).json()
    c = client.post("/v1/conversations", json={"guest_session_id": s["session_id"]},
                    headers={"X-Session-Token": s["session_token"]}).json()
    return s, c, {"X-Session-ID": s["session_id"], "X-Session-Token": s["session_token"], "X-Visitor": "guest"}


def test_txt_knowledge_upload_indexes_and_retrieves(client, tmp_path):
    content = b"Trawellcare offers curated wellness retreats in Spain and Japan. Prices are individually tailored."
    res = client.post("/v1/knowledge/documents",
                      files={"file": ("retreats.txt", content, "text/plain")},
                      data={"title": "Retreat FAQ"})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "indexed" and body["chunk_count"] >= 1

    docs = client.get("/v1/knowledge/documents").json()
    assert docs[0]["document_id"] == body["document_id"]

    # The retriever now surfaces the uploaded chunk with source attribution.
    from hayat_backend.knowledge import KnowledgeStore
    ks = KnowledgeStore(str(tmp_path / "knowledge"))
    assert any("Spain" in c.text for c in ks.indexed_chunks())


def test_knowledge_upload_rejects_bad_type_and_empty(client):
    res = client.post("/v1/knowledge/documents",
                      files={"file": ("evil.exe", b"MZ", "application/octet-stream")})
    assert res.status_code == 422
    res = client.post("/v1/knowledge/documents",
                      files={"file": ("empty.txt", b"", "text/plain")})
    assert res.status_code == 422


def test_knowledge_upload_handles_unreadable_pdf(client):
    res = client.post("/v1/knowledge/documents",
                      files={"file": ("broken.pdf", b"not a pdf", "application/pdf")})
    assert res.status_code == 200
    assert res.json()["status"] == "failed"


def test_voice_chat_fails_closed_without_stt(client):
    _, conv, headers = _session(client)
    res = client.post("/v1/voice/chat",
                      files={"file": ("a.webm", b"fakeaudio", "audio/webm")},
                      data={"conversation_id": conv["id"]}, headers=headers)
    assert res.status_code == 503


def test_voice_synthesize_only_reads_stored_assistant_messages(client):
    s, conv, headers = _session(client)
    res = client.post("/v1/voice/synthesize", headers=headers,
                      json={"conversation_id": conv["id"], "message_id": "00000000-0000-0000-0000-000000000000"})
    assert res.status_code == 404
    # Arbitrary text is never accepted — only a stored assistant message id.
    res = client.post("/v1/voice/synthesize", headers=headers,
                      json={"conversation_id": conv["id"], "message_id": "not-a-uuid"})
    assert res.status_code == 400


def test_visitor_attachments_disabled_by_default(client):
    _, conv, headers = _session(client)
    res = client.post(f"/v1/conversations/{conv['id']}/attachments", headers=headers,
                      files={"file": ("note.txt", b"hello", "text/plain")})
    assert res.status_code == 403
