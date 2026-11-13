"""Phase 4 of IMPLEMENTATION.md: grounding and the knowledge base manager."""

import re

import pytest
from fastapi.testclient import TestClient

from hayat_backend import main as m
from hayat_backend import programmes_registry as registry
from hayat_backend.config import Settings
from hayat_backend.knowledge import _chunk_text
from hayat_backend.main import create_app
from hayat_backend.memory_store import MemoryStore
from hayat_backend.rag import DEFAULT_APPROVED_KNOWLEDGE, InMemoryRetriever
from hayat_backend.training_scripts import house_style

from test_flow_addendum import A, _chat, say


@pytest.fixture
def client(tmp_path):
    settings = Settings(app_env="test", knowledge_dir=str(tmp_path / "k"))
    original = m.get_settings
    m.get_settings = lambda: settings
    try:
        yield TestClient(create_app(store=MemoryStore()))
    finally:
        m.get_settings = original
        registry._ROOT.clear()
        registry.reload()


def test_a_programme_rename_through_the_api_is_used_immediately_and_drafts_stay_hidden(client):
    records = client.get("/v1/knowledge/programmes").json()["programmes"]
    zoe = next(r for r in records if r["id"] == "zoe")
    zoe.update(name="Noor", former_names=["Zoé", "AAfiya", "AAfiyah"])
    records.append({"id": "draft-one", "name": "Secret Programme", "tagline": "not yet", "status": "draft"})
    assert client.put("/v1/knowledge/programmes", json={"programmes": records}).status_code == 200
    names = [p.name for p in registry.programmes()]
    assert "Noor" in names and "Zoé" not in names and "Secret Programme" not in names
    assert house_style("Tell me about Zoé and AAfiya") == "Tell me about Noor and Noor"
    bad = client.put("/v1/knowledge/programmes", json={"programmes": [{"id": "x"}]})
    assert bad.status_code == 422


def test_passages_never_start_or_end_mid_sentence():
    text = "First fact about trawellcare. " * 60 + "\nA new paragraph with the destinations Spain and Japan."
    chunks = _chunk_text(text)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk[0].isupper() and chunk.rstrip()[-1] in ".!?"


def test_the_production_turn_shows_no_unapproved_or_instruction_passages_as_facts():
    service, model, c = _chat({}, default=A(intent="question"))
    guidance = type(DEFAULT_APPROVED_KNOWLEDGE[0])(
        text="Hayat must never quote an assumed price. Suggested response: pricing is customised.",
        source=type(DEFAULT_APPROVED_KNOWLEDGE[0].source)(document_id="doc-guide", title="Rules", version="1"),
    )
    service.retriever = InMemoryRetriever(list(DEFAULT_APPROVED_KNOWLEDGE) + [guidance])
    say(service, c, "which hospitals and destinations do you compare, is India JCI accredited?")
    passages = model.calls[-1][0]["content"].split("Passages:")[-1] if "Passages:" in model.calls[-1][0]["content"] else ""
    assert "JCI" not in passages and "Thailand" not in passages
    assert not re.search(r"Hayat must never quote", passages)
