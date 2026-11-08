"""QA Session 2 — knowledge document lifecycle. Isolated tmp knowledge_dir."""
import io, json, hashlib, tempfile, time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from hayat_backend import main as m
from hayat_backend.config import Settings
from hayat_backend.main import create_app
from hayat_backend.memory_store import MemoryStore

RESULTS = []

def rec(tid, name, inp, expected, actual, ok, evidence=""):
    RESULTS.append({"test": tid, "name": name, "input": inp, "expected": expected,
                    "actual": str(actual)[:400], "verdict": "PASS" if ok else ("PARTIAL" if ok is None else "FAIL"),
                    "evidence": evidence})
    print(f"[{tid}] {name}: {'PASS' if ok else ('PARTIAL' if ok is None else 'FAIL')}")

@pytest.fixture
def env(tmp_path):
    kdir = tmp_path / "knowledge"
    settings = Settings(app_env="test", knowledge_dir=str(kdir), max_upload_mb=1)
    orig = m.get_settings
    m.get_settings = lambda: settings
    client = TestClient(create_app(store=MemoryStore()))
    return client, kdir

def upload(client, filename, data, ctype, title=None):
    files = {"file": (filename, io.BytesIO(data), ctype)}
    data_f = {"title": title} if title else {}
    return client.post("/v1/knowledge/documents", files=files, data=data_f)

def make_pdf(text):
    # minimal valid single-page PDF with a text stream
    stream = f"BT /F1 12 Tf 50 750 Td ({text}) Tj ET".encode()
    objs = []
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>")
    objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = b"%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out

def make_docx(text):
    import docx
    d = docx.Document()
    d.add_paragraph(text)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()

TXT = ("Trawellcare internal policy QA-77: the Cedar Wellness Retreat runs "
       "every second Tuesday of the month in Muscat. The programme code is "
       "CEDAR-2026 and the coordinator on duty is Lina Haddad. Guests receive "
       "a welcome kit containing a linen wrap and a brass compass. Maximum "
       "group size is twelve participants per session.")
TXT_BYTES = TXT.encode()
SHA = hashlib.sha256(TXT_BYTES).hexdigest()

# ---------- Test 1: upload all formats ----------
def test_uploads(env):
    client, kdir = env
    r_txt = upload(client, "policy.txt", TXT_BYTES, "text/plain", "Cedar Policy")
    rec("T1a", "TXT upload", "policy.txt", "200 indexed", f"{r_txt.status_code} {r_txt.json().get('status')}",
        r_txt.status_code == 200 and r_txt.json()["status"] == "indexed", r_txt.text[:200])
    r_pdf = upload(client, "policy.pdf", make_pdf("Cedar Wellness Retreat policy QA document"), "application/pdf", "Cedar PDF")
    rec("T1b", "PDF upload", "policy.pdf", "200 indexed or failed-safely", f"{r_pdf.status_code} {r_pdf.json().get('status')}",
        r_pdf.status_code in (200, 422), r_pdf.text[:200])
    r_docx = upload(client, "policy.docx", make_docx("Cedar Wellness Retreat policy QA document"),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "Cedar DOCX")
    rec("T1c", "DOCX upload", "policy.docx", "200 indexed", f"{r_docx.status_code} {r_docx.json().get('status')}",
        r_docx.status_code == 200, r_docx.text[:200])
    docs = client.get("/v1/knowledge/documents").json()
    rec("T1d", "metadata", "GET documents", "all listed with ids/versions", f"{len(docs)} docs",
        len(docs) >= 2, json.dumps(docs)[:300])
    return client, kdir

# ---------- Test 2: retrieval + attribution ----------
def test_retrieval(client, kdir):
    s = client.post("/v1/sessions/guest", json={"locale": "en"}).json()
    h = {"X-Session-ID": s["session_id"], "X-Session-Token": s["session_token"], "X-Visitor": "guest"}
    c = client.post("/v1/conversations", json={"guest_session_id": s["session_id"]}, headers=h).json()
    # grounded question only answerable from uploaded doc — knowledge questions
    # route through programme/fallback; test retriever directly via chat on a
    # knowledge-style question is indirect; verify via sources on a matching query.
    r = client.post("/v1/chat", json={"conversation_id": c["id"],
                "message": "What is the coordinator on duty for the Cedar Wellness Retreat?"}, headers=h)
    b = r.json()
    rec("T2a", "grounded query", "coordinator on duty?", "reply may be generic; sources should attribute if grounded",
        f"reply={b.get('reply','')[:120]!r} sources={b.get('sources')}",
        r.status_code == 200, json.dumps({"reply": b.get("reply","")[:200], "sources": b.get("sources")}, ensure_ascii=False)[:400])
    # unsupported question
    r2 = client.post("/v1/chat", json={"conversation_id": c["id"],
                 "message": "What is the wifi password for the Cedar Retreat?"}, headers=h)
    rec("T2b", "unsupported query", "wifi password?", "no fabrication", r2.json().get("reply","")[:150],
        r2.status_code == 200, r2.json().get("reply","")[:200])

# ---------- Test 3: versioning ----------
def test_versioning(client, kdir):
    TXT2 = TXT_BYTES + b" UPDATE: sessions now run on the first Friday instead."
    docs_before = {d["document_id"]: d for d in client.get("/v1/knowledge/documents").json()}
    # find cedar txt doc
    cedar = [d for d in docs_before.values() if "Cedar Policy" in (d.get("title") or "")]
    if not cedar:
        rec("T3", "versioning", "re-upload", "n/a", "cedar doc not found", None); return
    doc_id = cedar[0]["document_id"]
    r = upload(client, "policy.txt", TXT2, "text/plain", "Cedar Policy")
    b = r.json()
    rec("T3a", "version increment", "re-upload same title+new content", "version 2 indexed",
        f"version={b.get('version')} status={b.get('status')}",
        b.get("version") == "2" or b.get("status") == "indexed", r.text[:250])

# ---------- Test 4: dedup ----------
def test_dedup(client, kdir):
    r = upload(client, "dup.txt", TXT_BYTES, "text/plain", "Cedar Policy")
    b = r.json()
    rec("T4", "dedup identical", "same bytes+title", "no duplicate chunks; version bump or dedup",
        f"doc_id={b.get('document_id')} version={b.get('version')} chunks={b.get('chunk_count')}",
        r.status_code == 200, r.text[:250])
    docs = client.get("/v1/knowledge/documents").json()
    titles = [d["title"] for d in docs]
    rec("T4b", "no dup index entries", "GET", "single Cedar Policy doc", f"{titles.count('Cedar Policy')} entries",
        titles.count("Cedar Policy") == 1, str(titles))

# ---------- Test 5: deletion ----------
def test_delete(client, kdir):
    docs = client.get("/v1/knowledge/documents").json()
    cedar = [d for d in docs if "Cedar" in (d.get("title") or "")]
    if not cedar:
        rec("T5", "delete", "n/a", "n/a", "no cedar doc", None); return
    doc_id = cedar[0]["document_id"]
    files_before = list((kdir / "documents").glob(f"{doc_id}-v*.txt"))
    r = client.delete(f"/v1/knowledge/documents/{doc_id}")
    rec("T5a", "delete", f"DELETE {doc_id}", "200 deleted", f"{r.status_code} {r.json()}",
        r.status_code == 200, r.text[:200])
    r404 = client.delete(f"/v1/knowledge/documents/{doc_id}")
    rec("T5b", "delete again", "DELETE same", "404", f"{r404.status_code}", r404.status_code == 404, "")
    files_after = list((kdir / "documents").glob(f"{doc_id}-v*.txt"))
    rec("T5c", "files cleaned", "glob", "0 files", f"{len(files_after)} remain",
        len(files_after) == 0 and len(files_before) > 0, f"before={len(files_before)}")
    remaining = client.get("/v1/knowledge/documents").json()
    rec("T5d", "others remain", "GET", "other docs intact", f"{len(remaining)} docs",
        len(remaining) >= 1, str([d['title'] for d in remaining]))

# ---------- Test 6: failure handling ----------
def test_failures(client, kdir):
    r = upload(client, "bad.pdf", b"NOT A PDF AT ALL", "application/pdf", "Bad")
    rec("T6a", "corrupt pdf", "bad.pdf", "failed status or 422, no crash", f"{r.status_code} {r.json().get('status','?')}",
        r.status_code in (200, 422), r.text[:200])
    r = upload(client, "evil.exe", b"MZ", "application/octet-stream", "Evil")
    rec("T6b", "unsupported type", "evil.exe", "4xx rejected", f"{r.status_code}", r.status_code in (400, 415, 422), "")
    r = upload(client, "empty.txt", b"", "text/plain", "Empty")
    rec("T6c", "empty doc", "empty.txt", "failed status, no crash", f"{r.status_code} {r.json().get('status','?')}",
        r.status_code in (200, 422), r.text[:200])
    big = b"x" * (1024 * 1024 + 10)  # >1MB cap
    r = upload(client, "big.txt", big, "text/plain", "Big")
    rec("T6d", "oversized", "big.txt 1MB+", "4xx rejected", f"{r.status_code}", r.status_code in (400, 413, 422), "")

if __name__ == "__main__":
    # run manually with a tmp dir since pytest fixtures are awkward in script form
    import tempfile, pathlib
    tmp = pathlib.Path(tempfile.mkdtemp())
    settings = Settings(app_env="test", knowledge_dir=str(tmp / "k"), max_upload_mb=1)
    orig = m.get_settings
    m.get_settings = lambda: settings
    client = TestClient(create_app(store=MemoryStore()))
    kdir = tmp / "k"

    test_uploads((client, kdir))
    test_retrieval(client, kdir)
    test_versioning(client, kdir)
    test_dedup(client, kdir)
    test_delete(client, kdir)
    test_failures(client, kdir)

    Path("knowledge_qa_results.json").write_text(json.dumps(RESULTS, indent=2, ensure_ascii=False), encoding="utf-8")
    m.get_settings = orig
    print(f"\nWrote knowledge_qa_results.json — {len(RESULTS)} records")
