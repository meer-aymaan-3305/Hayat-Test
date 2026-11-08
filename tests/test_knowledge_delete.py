"""Regression: knowledge document removal."""
import io
import pytest
from fastapi.testclient import TestClient

from hayat_backend import main as m
from hayat_backend.config import Settings
from hayat_backend.main import create_app
from hayat_backend.memory_store import MemoryStore


@pytest.fixture
def client(tmp_path):
    settings = Settings(app_env="test", knowledge_dir=str(tmp_path / "k"))
    orig = m.get_settings
    m.get_settings = lambda: settings
    try:
        yield TestClient(create_app(store=MemoryStore()))
    finally:
        m.get_settings = orig


def test_delete_knowledge_document(client):
    up = client.post("/v1/knowledge/documents",
                     files={"file": ("faq.txt", io.BytesIO(b"Trawellcare consultations are free."), "text/plain")},
                     data={"title": "FAQ"})
    assert up.status_code == 200
    doc_id = up.json()["document_id"]
    assert any(d["document_id"] == doc_id for d in client.get("/v1/knowledge/documents").json())

    dele = client.delete(f"/v1/knowledge/documents/{doc_id}")
    assert dele.status_code == 200 and dele.json()["status"] == "deleted"
    assert not any(d["document_id"] == doc_id for d in client.get("/v1/knowledge/documents").json())
    assert client.delete(f"/v1/knowledge/documents/{doc_id}").status_code == 404
