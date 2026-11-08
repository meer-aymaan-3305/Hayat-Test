"""Visitor attachments: storage, validation, acknowledgement, staff access, retention."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import hayat_backend.main as main
from hayat_backend.attachments import AttachmentStore
from hayat_backend.config import Settings
from hayat_backend.main import create_app
from hayat_backend.memory_store import MemoryStore

PDF = b"%PDF-1.4\n%fake body"
DOCX = b"PK\x03\x04fake zip body"
EN_REPLY = "I've saved your file with this conversation. I can't read or review documents myself."
AR_REPLY = "حفظتُ ملفك ضمن هذه المحادثة. لا أستطيع قراءة المستندات أو مراجعتها بنفسي."


@pytest.fixture
def env(tmp_path, monkeypatch):
    settings = Settings(
        app_env="test", knowledge_dir=str(tmp_path / "knowledge"),
        attachments_dir=str(tmp_path / "attachments"),
        visitor_attachments_enabled=True, max_upload_mb=1,
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    store = MemoryStore()
    return TestClient(create_app(store=store)), store, tmp_path / "attachments"


def _session(client):
    s = client.post("/v1/sessions/guest", json={"locale": "en"}).json()
    c = client.post("/v1/conversations", json={"guest_session_id": s["session_id"]},
                    headers={"X-Session-Token": s["session_token"]}).json()
    return c["id"], {"X-Session-ID": s["session_id"], "X-Session-Token": s["session_token"]}


def _upload(client, conv_id, headers, name="note.txt", data=b"hello", **extra):
    return client.post(f"/v1/conversations/{conv_id}/attachments", headers={**headers, **extra},
                       files={"file": (name, data, "application/octet-stream")})


def test_upload_stores_file_privately_and_acknowledges_in_chat(env):
    client, store, root = env
    conv_id, headers = _session(client)
    res = _upload(client, conv_id, headers, "../../My Report.TXT", b"plain text")
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"attachment_id", "filename", "reply", "message_id"}
    assert body["filename"] == "My Report.TXT"
    assert body["reply"] == EN_REPLY

    # Generated name on disk, never the visitor's filename; index lists display metadata.
    folder = root / conv_id
    assert sorted(p.name for p in folder.iterdir()) == sorted(["index.json", f"{body['attachment_id']}.txt"])
    entry = json.loads((folder / "index.json").read_text())["attachments"][0]
    assert entry["id"] == body["attachment_id"] and entry["filename"] == "My Report.TXT"
    assert entry["extension"] == ".txt" and entry["size"] == 10 and entry["uploaded_at"]

    # Both turns are in the stored conversation, so history and staff views show them.
    messages = store.get_conversation(*_ids(client, headers, conv_id)).messages[-2:]
    assert [(m.role, m.content) for m in messages] == [
        ("user", "Attached file: My Report.TXT"), ("assistant", EN_REPLY),
    ]
    assert str(messages[-1].id) == body["message_id"]


def _ids(client, headers, conv_id):
    return headers["X-Session-ID"], conv_id


def test_reply_is_arabic_with_header_and_never_promises_contact(env):
    client, store, _ = env
    conv_id, headers = _session(client)
    body = _upload(client, conv_id, headers, "تقرير.txt", b"x", **{"X-Reply-Language": "ar"}).json()
    assert body["reply"] == AR_REPLY
    messages = store.get_conversation(*_ids(client, headers, conv_id)).messages[-2:]
    assert messages[0].content == "تم إرفاق ملف: تقرير.txt" and messages[0].language == "ar"
    assert all(word not in EN_REPLY.lower() for word in ("call", "contact", "coordinator"))


@pytest.mark.parametrize("name,data", [
    ("evil.exe", b"MZ"),
    ("noext", b"hello"),
    ("empty.txt", b""),
    ("fake.pdf", b"not a pdf"),
    ("fake.docx", b"%PDF-1.4"),
    ("binary.txt", b"\xff\xfe\x00\x01"),
    ("nul.txt", b"abc\x00def"),
])
def test_invalid_files_are_refused(env, name, data):
    client, _, root = env
    conv_id, headers = _session(client)
    assert _upload(client, conv_id, headers, name, data).status_code == 422
    assert not root.exists() or not any(root.rglob("*.*"))


def test_valid_pdf_and_docx_are_accepted(env):
    client, _, _ = env
    conv_id, headers = _session(client)
    assert _upload(client, conv_id, headers, "a.pdf", PDF).status_code == 200
    assert _upload(client, conv_id, headers, "b.docx", DOCX).status_code == 200


def test_oversized_upload_is_rejected(env):
    client, _, _ = env
    conv_id, headers = _session(client)
    # Slightly over the limit: the route refuses it. Far over: the middleware does, before parsing.
    assert _upload(client, conv_id, headers, "a.txt", b"x" * (1024 * 1024 + 1)).status_code == 422
    assert _upload(client, conv_id, headers, "b.txt", b"x" * (2 * 1024 * 1024)).status_code == 413


def test_sixth_file_is_refused_with_a_clear_message(env):
    client, _, _ = env
    conv_id, headers = _session(client)
    for i in range(5):
        assert _upload(client, conv_id, headers, f"f{i}.txt", b"x").status_code == 200
    res = _upload(client, conv_id, headers, "f6.txt", b"x")
    assert res.status_code == 422 and "up to 5 files" in res.json()["detail"]


def test_other_sessions_cannot_upload_to_the_conversation(env):
    client, _, _ = env
    conv_id, _ = _session(client)
    _, other_headers = _session(client)
    assert _upload(client, conv_id, other_headers).status_code == 403


def test_disabled_flag_blocks_every_attachment_route(tmp_path, monkeypatch):
    settings = Settings(app_env="test", attachments_dir=str(tmp_path), knowledge_dir=str(tmp_path / "k"))
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    client = TestClient(create_app(store=MemoryStore()))
    conv_id, headers = _session(client)
    assert _upload(client, conv_id, headers).status_code == 403
    assert client.get(f"/v1/staff/conversations/{conv_id}/attachments").status_code == 403
    assert client.get(f"/v1/staff/attachments/{'a' * 32}").status_code == 403


def test_staff_can_list_and_download(env):
    client, _, _ = env
    conv_id, headers = _session(client)
    uploaded = _upload(client, conv_id, headers, "Report é.pdf", PDF).json()

    listing = client.get(f"/v1/staff/conversations/{conv_id}/attachments").json()
    assert len(listing) == 1
    assert listing[0]["attachment_id"] == uploaded["attachment_id"]
    assert listing[0]["filename"] == "Report é.pdf"
    assert listing[0]["extension"] == ".pdf" and listing[0]["size"] == len(PDF) and listing[0]["uploaded_at"]

    res = client.get(f"/v1/staff/attachments/{uploaded['attachment_id']}")
    assert res.status_code == 200 and res.content == PDF
    assert res.headers["content-type"] == "application/pdf"
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["content-disposition"] == "attachment; filename*=UTF-8''Report%20%C3%A9.pdf"


def test_staff_download_rejects_unknown_and_malformed_ids(env):
    client, _, _ = env
    assert client.get(f"/v1/staff/attachments/{'a' * 32}").status_code == 404
    assert client.get("/v1/staff/attachments/not-a-uuid").status_code == 404
    assert client.get("/v1/staff/attachments/..%2F..%2Findex").status_code == 404
    assert client.get(f"/v1/staff/conversations/{'0' * 8}-0000-0000-0000-{'0' * 12}/attachments").json() == []


def test_purge_removes_only_expired_files_and_index_entries(tmp_path):
    store = AttachmentStore(tmp_path, retention_days=90)
    old = store.save("c1", "old.txt", b"old", ".txt")
    fresh = store.save("c1", "new.txt", b"new", ".txt")
    only_old = store.save("c2", "gone.txt", b"gone", ".txt")
    index_path = tmp_path / "c1" / "index.json"
    for conv, entry in (("c1", old), ("c2", only_old)):
        path = tmp_path / conv / "index.json"
        data = json.loads(path.read_text())
        data["attachments"][0]["uploaded_at"] = (datetime.now(UTC) - timedelta(days=91)).isoformat()
        path.write_text(json.dumps(data))

    assert store.purge_expired() == 2
    assert [e["id"] for e in store.list_for("c1")] == [fresh["id"]]
    assert not (tmp_path / "c1" / f"{old['id']}.txt").exists()
    assert (tmp_path / "c1" / f"{fresh['id']}.txt").exists()
    assert not (tmp_path / "c2").exists()
    assert index_path.exists()
    assert store.purge_expired() == 0


def test_retention_zero_keeps_everything(tmp_path):
    store = AttachmentStore(tmp_path, retention_days=0)
    store.save("c1", "a.txt", b"a", ".txt")
    assert store.purge_expired(now=datetime.now(UTC) + timedelta(days=3650)) == 0
    assert len(store.list_for("c1")) == 1


def test_purge_runs_at_startup(env):
    client, _, root = env
    conv_id, headers = _session(client)
    _upload(client, conv_id, headers)
    path = root / conv_id / "index.json"
    data = json.loads(path.read_text())
    data["attachments"][0]["uploaded_at"] = (datetime.now(UTC) - timedelta(days=400)).isoformat()
    path.write_text(json.dumps(data))
    with client:  # entering the client runs the app lifespan
        pass
    assert not (root / conv_id).exists()
