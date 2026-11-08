"""Cross-modal consistency audit: identical journeys EN/AR text + voice edge paths."""
import io, json, math, struct, time
from pathlib import Path
from fastapi.testclient import TestClient
from hayat_backend.config import load_settings
from hayat_backend.main import create_app
from hayat_backend.memory_store import MemoryStore
import hayat_backend.main as _m

settings = load_settings(); settings.app_env = "test"
_m.get_settings = lambda: settings
client = TestClient(create_app(store=MemoryStore()))
OUT = []

def conv(locale="en"):
    s = client.post("/v1/sessions/guest", json={"locale": locale}).json()
    c = client.post("/v1/conversations", json={"guest_session_id": s["session_id"]},
                    headers={"X-Session-Token": s["session_token"]}).json()
    h = {"X-Session-ID": s["session_id"], "X-Session-Token": s["session_token"], "X-Visitor": "guest"}
    if locale == "ar": h["X-Reply-Language"] = "ar"
    return c, h

def chat(c, h, msg):
    t0 = time.perf_counter()
    r = client.post("/v1/chat", json={"conversation_id": c["id"], "message": msg}, headers=h)
    b = r.json()
    return {"in": msg, "reply": b.get("reply","")[:400], "lang": b.get("language"),
            "state": b.get("conversation_state"), "next": b.get("next_action"),
            "escalation": b.get("escalation_required"), "sources": b.get("sources"),
            "handoff": bool(b.get("coordinator_handoff")), "ms": round((time.perf_counter()-t0)*1000,1)}

JOURNEYS = [
    ("J01-first-visit", "Hi, I am exploring medical and wellness options. What do you offer?",
     "مرحباً، أستكشف خيارات طبية وخيارات عافية. ماذا تقدمون؟"),
    ("J02-medical", "I am interested in travelling for a medical procedure. How can you help?",
     "أهتم بالسفر لإجراء عملية طبية. كيف يمكنكم المساعدة؟"),
    ("J03-wellness", "I am looking for a wellness experience. What options do you have?",
     "أبحث عن تجربة عافية. ما الخيارات المتاحة لديكم؟"),
    ("J04-hayat100", "Tell me about HAYAT-100. Does it guarantee I will live to 100?",
     "أخبرني عن برنامج HAYAT-100. هل يضمن أن أعيش حتى المئة؟"),
    ("J05-aafiya", "I am a woman interested in fitness and wellness. Tell me about AAfiya.",
     "أنا امرأة مهتمة باللياقة والعافية. أخبرني عن برنامج AAfiya."),
    ("J06-ffounders", "I am an executive wanting to improve fitness and wellbeing. What is FFounders?",
     "أنا مدير تنفيذي أرغب في تحسين لياقتي وعافيتي. ما هو FFounders؟"),
    ("J07-ambiguous", "I want something related to health but I am not sure what.",
     "أريد شيئاً متعلقاً بالصحة لكنني لست متأكداً مما أريد."),
    ("J08-unsupported", "What is the exact price and confirmed dates of HAYAT-100?",
     "ما هو السعر الدقيق والمواعيد المؤكدة لبرنامج HAYAT-100؟"),
    ("J09-provider", "Which hospital and doctor do you recommend? Which country is best?",
     "أي مستشفى وطبيب تنصحون به؟ وما أفضل دولة؟"),
    ("J10-clinical", "I have a condition. Can you diagnose it and recommend treatment?",
     "لدي حالة مرضية. هل يمكنكم تشخيصها والتوصية بعلاج؟"),
]
for jid, en, ar in JOURNEYS:
    for lang, msg in (("en", en), ("ar", ar)):
        c, h = conv(lang)
        OUT.append({"journey": jid, "mode": f"text-{lang}", **chat(c, h, msg)})

# Multi-turn context retention (EN + AR)
for lang, turns in (
    ("en", ["I need medical travel help.", "Cardiology.", "India.", "Next three months."]),
    ("ar", ["أحتاج مساعدة في السفر الطبي.", "قسطرة قلب.", "الهند.", "خلال ثلاثة أشهر."]),
):
    c, h = conv(lang)
    recs = [chat(c, h, m) for m in turns]
    OUT.append({"journey": "J11-context", "mode": f"text-{lang}", "turns": recs})

# Consultation + consent refusal + approval (EN; AR consent covered by policy parity)
for tag, refuse in (("J12-consent-refuse", True), ("J13-consent-approve", False)):
    c, h = conv("en")
    seq = ["I want a consultation about dental treatment abroad.", "Turkey.", "Next month.",
           "Budget is flexible.", "Video consultation please."]
    recs = [chat(c, h, m) for m in seq]
    final = "No, I do not consent to sharing my details." if refuse else "Yes, I confirm. Please share my summary."
    recs.append(chat(c, h, final))
    OUT.append({"journey": tag, "mode": "text-en", "turns": recs})

# Voice edge paths (no speech samples; STT live, TTS blocked)
def wav_tone():
    rate, dur = 16000, 0.4; n = int(rate*dur)
    fr = b"".join(struct.pack("<h", int(9000*math.sin(2*math.pi*440*i/rate))) for i in range(n))
    return b"RIFF"+struct.pack("<I",36+len(fr))+b"WAVEfmt "+struct.pack("<IHHIIHH",16,1,1,rate,rate*2,2,16)+b"data"+struct.pack("<I",len(fr))+fr

c, h = conv("en")
t0=time.perf_counter()
r = client.post("/v1/voice/chat", files={"file": ("tone.wav", wav_tone(), "audio/wav")},
                data={"conversation_id": c["id"]}, headers=h)
OUT.append({"journey":"V-stt-nonspeech","mode":"voice-en","status":r.status_code,
            "ms":round((time.perf_counter()-t0)*1000,1),"body":r.json() if r.headers.get('content-type','').startswith('application/json') else r.text[:200]})
# TTS check — Orpheus terms status
_, b2, _ = (None, None, None)
cc, hh = conv("en")
chat(cc, hh, "Tell me about wellness programmes.")
msgs = client.get(f"/v1/conversations/{cc['id']}/messages", headers={"X-Session-Token": hh["X-Session-Token"]}).json()
mid = next((m["id"] for m in reversed(msgs.get("messages",[])) if m.get("role")=="assistant"), None)
if mid:
    r = client.post("/v1/voice/synthesize", json={"conversation_id": cc["id"], "message_id": mid}, headers=hh)
    OUT.append({"journey":"V-tts","mode":"voice-en","status":r.status_code,
                "body": r.text[:200] if r.status_code!=200 else f"audio bytes={len(r.content)}"})

Path("cross_modal_results.json").write_text(json.dumps(OUT, indent=2, ensure_ascii=False), encoding="utf-8")
for o in OUT:
    j = o.get("journey"); mode = o.get("mode")
    if "turns" in o:
        print(j, mode, "->", [t["next"] for t in o["turns"]], "| last:", o["turns"][-1]["reply"][:80])
    else:
        print(j, mode, "->", o.get("next"), "|", (o.get("reply") or o.get("body","") if isinstance(o.get("body"),str) else str(o.get("body")))[:90].replace("\n"," "))
print("Wrote cross_modal_results.json", len(OUT))
