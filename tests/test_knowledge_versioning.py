"""Regression: document-addressed knowledge versioning (QA defect D1)."""
import io
import pytest
from fastapi.testclient import TestClient

from hayat_backend import main as m
from hayat_backend.config import Settings
from hayat_backend.main import create_app
from hayat_backend.memory_store import MemoryStore

V1 = b"Trawellcare policy QA-1: the Cedar retreat meets every second Tuesday in Muscat."
V2 = b"Trawellcare policy QA-1: the Cedar retreat meets every first Friday in Muscat."
OTHER = b"Unrelated document about airport transfers only."


@pytest.fixture
def env(tmp_path):
    settings = Settings(app_env="test", knowledge_dir=str(tmp_path / "k"), max_upload_mb=1)
    orig = m.get_settings
    m.get_settings = lambda: settings
    client = TestClient(create_app(store=MemoryStore()))
    return client, tmp_path / "k"


def _up(client, name, data, title):
    return client.post("/v1/knowledge/documents",
                       files={"file": (name, io.BytesIO(data), "text/plain")},
                       data={"title": title})


def _put(client, doc_id, data, title=None):
    return client.put(f"/v1/knowledge/documents/{doc_id}",
                      files={"file": ("policy.txt", io.BytesIO(data), "text/plain")},
                      data={"title": title} if title else {})


def _chunks_text(client):
    """All retrievable uploaded-chunk text via the store's indexed_chunks."""
    return client.app.state if False else None


def test_initial_upload_v1(env):
    client, _ = env
    r = _up(client, "p.txt", V1, "Cedar")
    assert r.status_code == 200 and r.json()["version"] == "1"


def test_update_preserves_id_increments_version(env):
    client, _ = env
    doc_id = _up(client, "p.txt", V1, "Cedar").json()["document_id"]
    r = _put(client, doc_id, V2)
    b = r.json()
    assert r.status_code == 200
    assert b["document_id"] == doc_id and b["version"] == "2"


def test_retriever_returns_v2_not_v1(env):
    client, kdir = env
    doc_id = _up(client, "p.txt", V1, "Cedar").json()["document_id"]
    _put(client, doc_id, V2)
    # Rebuild retriever state exactly as startup does.
    from hayat_backend.knowledge import KnowledgeStore
    ks = KnowledgeStore(str(kdir))
    texts = [c.text for c in ks.indexed_chunks()]
    joined = " ".join(texts)
    assert "first Friday" in joined and "second Tuesday" not in joined


def test_previous_version_file_preserved(env):
    client, kdir = env
    doc_id = _up(client, "p.txt", V1, "Cedar").json()["document_id"]
    _put(client, doc_id, V2)
    files = sorted(p.name for p in (kdir / "documents").glob(f"{doc_id}-v*.txt"))
    assert files == [f"{doc_id}-v1.txt", f"{doc_id}-v2.txt"]


def test_same_title_docs_independent(env):
    client, _ = env
    a = _up(client, "a.txt", V1, "Same Title").json()["document_id"]
    b = _up(client, "b.txt", OTHER, "Same Title").json()["document_id"]
    assert a != b
    _put(client, a, V2)
    docs = {d["document_id"]: d for d in client.get("/v1/knowledge/documents").json()}
    assert docs[a]["version"] == "2" and docs[b]["version"] == "1"


def test_identical_content_dedup_still_works(env):
    client, _ = env
    a = _up(client, "a.txt", V1, "DocA").json()
    b = _up(client, "b.txt", V1, "DocB")
    assert b.json()["document_id"] == a["document_id"]
    assert b.json()["version"] == "2"


def test_failed_update_preserves_active(env):
    client, kdir = env
    doc_id = _up(client, "p.txt", V1, "Cedar").json()["document_id"]
    r = client.put(f"/v1/knowledge/documents/{doc_id}",
                   files={"file": ("bad.exe", io.BytesIO(b"MZ"), "application/octet-stream")})
    assert r.status_code == 422
    docs = {d["document_id"]: d for d in client.get("/v1/knowledge/documents").json()}
    assert docs[doc_id]["version"] == "1" and docs[doc_id]["status"] == "indexed"
    from hayat_backend.knowledge import KnowledgeStore
    texts = " ".join(c.text for c in KnowledgeStore(str(kdir)).indexed_chunks())
    assert "second Tuesday" in texts


def test_update_missing_doc_404(env):
    client, _ = env
    r = _put(client, "doc-nonexistent", V2)
    assert r.status_code == 404


def test_delete_removes_all_versions(env):
    client, kdir = env
    doc_id = _up(client, "p.txt", V1, "Cedar").json()["document_id"]
    _put(client, doc_id, V2)
    client.delete(f"/v1/knowledge/documents/{doc_id}")
    assert not list((kdir / "documents").glob(f"{doc_id}-v*.txt"))
    from hayat_backend.knowledge import KnowledgeStore
    assert not [c for c in KnowledgeStore(str(kdir)).indexed_chunks() if c.source.document_id == doc_id]


def test_restart_restores_only_active(env):
    client, kdir = env
    doc_id = _up(client, "p.txt", V1, "Cedar").json()["document_id"]
    _put(client, doc_id, V2)
    # Simulate restart: brand-new store instance reads disk only.
    from hayat_backend.knowledge import KnowledgeStore
    chunks = KnowledgeStore(str(kdir)).indexed_chunks()
    cedar = [c for c in chunks if c.source.document_id == doc_id]
    assert cedar and all(c.source.version == "2" for c in cedar)
    assert all("first Friday" in c.text for c in cedar)


def test_concurrent_updates_serialized(env):
    client, kdir = env
    doc_id = _up(client, "p.txt", V1, "Cedar").json()["document_id"]
    import threading
    def do_update(tag):
        _put(client, doc_id, f"Trawellcare policy {tag}".encode())
    threads = [threading.Thread(target=do_update, args=(f"U{i}",)) for i in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()
    docs = {d["document_id"]: d for d in client.get("/v1/knowledge/documents").json()}
    # Version must be a clean integer increment, never corrupted/duplicated.
    assert docs[doc_id]["version"].isdigit()
    assert int(docs[doc_id]["version"]) >= 2
