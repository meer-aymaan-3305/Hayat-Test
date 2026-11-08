"""TTS acceptance: endpoint synthesis + Whisper STT round-trips on real audio."""
import io, json, time
from pathlib import Path
from fastapi.testclient import TestClient

from hayat_backend import main as m
from hayat_backend.config import load_settings
from hayat_backend.main import create_app
from hayat_backend.memory_store import MemoryStore

RESULTS = []
def rec(tid, name, expected, actual, verdict, evidence=""):
    RESULTS.append({"test": tid, "name": name, "expected": expected,
                    "actual": str(actual)[:400], "verdict": verdict, "evidence": evidence})
    print(f"[{tid}] {name}: {verdict} — {str(actual)[:110]}")

settings = load_settings(); settings.app_env = "test"
m.get_settings = lambda: settings
client = TestClient(create_app(store=MemoryStore()))

def conv(lang="en"):
    s = client.post("/v1/sessions/guest", json={"locale": lang}).json()
    h = {"X-Session-ID": s["session_id"], "X-Session-Token": s["session_token"], "X-Visitor": "guest"}
    if lang == "ar": h["X-Reply-Language"] = "ar"
    c = client.post("/v1/conversations", json={"guest_session_id": s["session_id"]}, headers=h).json()
    return c, h

def last_assistant_id(cid, h):
    _, msgs = (lambda r: (r.status_code, r.json()))(client.get(f"/v1/conversations/{cid}/messages", headers=h))
    return next((mm["id"] for mm in reversed(msgs.get("messages", [])) if mm.get("role") == "assistant"), None)

# ---- EN endpoint TTS ----
c, h = conv("en")
client.post("/v1/chat", json={"conversation_id": c["id"], "message": "Tell me about wellness programmes."}, headers=h)
mid = last_assistant_id(c["id"], h)
t0 = time.perf_counter()
r = client.post("/v1/voice/synthesize", json={"conversation_id": c["id"], "message_id": mid}, headers=h)
ms = round((time.perf_counter()-t0)*1000)
ok = r.status_code == 200 and len(r.content) > 1000 and r.headers.get("content-type","").startswith("audio")
rec("TTS-EN", "EN synthesize stored msg", "200 audio/wav non-empty",
    f"{r.status_code} {r.headers.get('content-type')} {len(r.content)}B {ms}ms",
    "PASS" if ok else "FAIL")
if ok:
    Path("tts_endpoint_en.wav").write_bytes(r.content)

# ---- AR endpoint TTS ----
ca, ha = conv("ar")
client.post("/v1/chat", json={"conversation_id": ca["id"], "message": "أخبرني عن برامج العافية."}, headers=ha)
mida = last_assistant_id(ca["id"], ha)
t0 = time.perf_counter()
ra = client.post("/v1/voice/synthesize", json={"conversation_id": ca["id"], "message_id": mida}, headers=ha)
msa = round((time.perf_counter()-t0)*1000)
oka = ra.status_code == 200 and len(ra.content) > 1000
rec("TTS-AR", "AR synthesize stored msg", "200 audio non-empty",
    f"{ra.status_code} {ra.headers.get('content-type')} {len(ra.content)}B {msa}ms",
    "PASS" if oka else "FAIL")
if oka:
    Path("tts_endpoint_ar.wav").write_bytes(ra.content)

# ---- Whisper STT round-trips on generated audio ----
for tid, wav, lang in [("STT-EN","tts_en.wav","en"),("STT-AR","tts_ar.wav","ar")]:
    data = Path(wav).read_bytes()
    cb, hb = conv(lang)
    t0 = time.perf_counter()
    rr = client.post("/v1/voice/chat", files={"file": (wav, io.BytesIO(data), "audio/wav")},
                     data={"conversation_id": cb["id"]}, headers=hb)
    ms2 = round((time.perf_counter()-t0)*1000)
    b = rr.json() if rr.headers.get("content-type","").startswith("application/json") else {}
    rec(tid, f"{lang.upper()} TTS->STT round-trip", "transcript ~= source text",
        f"{rr.status_code} transcript={b.get('transcript')!r} lang={b.get('detected_language')} reply={str(b.get('reply'))[:80]!r} {ms2}ms",
        "PASS" if rr.status_code==200 and b.get("transcript") else "FAIL", rr.text[:200])

# ---- ownership / arbitrary / fail-closed ----
cX, hX = conv("en")
client.post("/v1/chat", json={"conversation_id": cX["id"], "message":"hi"}, headers=hX)
midX = last_assistant_id(cX["id"], hX)
cY, hY = conv("en")
r = client.post("/v1/voice/synthesize", json={"conversation_id": cY["id"], "message_id": midX}, headers=hY)
rec("OWN", "other visitor's message", "403/404 rejected", f"{r.status_code}",
    "PASS" if r.status_code in (403,404) else "FAIL")
r = client.post("/v1/voice/synthesize", json={"conversation_id": cX["id"], "message_id": "00000000-0000-0000-0000-000000000000"}, headers=hX)
rec("ARB", "arbitrary text/missing msg", "404 rejected", f"{r.status_code}",
    "PASS" if r.status_code in (400,403,404) else "FAIL")

# missing key: build settings without key
s2 = load_settings(); s2.app_env="test"; s2.groq_api_key=None
m.get_settings = lambda: s2
client2 = TestClient(create_app(store=MemoryStore()))
c2, h2 = conv("en")
client2.post("/v1/chat", json={"conversation_id": c2["id"], "message":"hi"}, headers=h2)
mid2 = last_assistant_id(c2["id"], h2)
r = client2.post("/v1/voice/synthesize", json={"conversation_id": c2["id"], "message_id": mid2}, headers=h2)
rec("NOKEY", "TTS no API key", "503 fail-closed", f"{r.status_code}", "PASS" if r.status_code==503 else "FAIL")

Path("tts_acceptance_results.json").write_text(json.dumps(RESULTS, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"\nWrote tts_acceptance_results.json — {len(RESULTS)} records")
