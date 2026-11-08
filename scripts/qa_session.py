"""Live QA session driver — real HTTP against running backend (test env)."""
import json, time, urllib.request

BASE = "http://127.0.0.1:2005"

def req(method, path, body=None, headers=None):
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")

def new_conv():
    _, s = req("POST", "/v1/sessions/guest", {"locale": "en"})
    H = {"X-Session-ID": s["session_id"], "X-Session-Token": s["session_token"], "X-Visitor": "guest"}
    _, c = req("POST", "/v1/conversations", {"guest_session_id": s["session_id"]}, H)
    return s, c, H

def chat(cid, H, msg):
    t0 = time.perf_counter()
    st, b = req("POST", "/v1/chat", {"conversation_id": cid, "message": msg}, H)
    return st, b, round((time.perf_counter() - t0) * 1000, 1)

results = []
def rec(tid, label, inp, st, b, ms, extra=""):
    reply = b.get("reply", "")
    results.append({"id": tid, "label": label, "input": inp, "status": st,
                    "reply": reply, "ms": ms, "state": b.get("conversation_state"),
                    "next": b.get("next_action"), "escalation": b.get("escalation_required"),
                    "facts": b.get("profile_updates") or b.get("missing_required_fields") or [],
                    "extra": extra})
    print(f"[{tid}] {label}\n  IN : {inp[:90]}\n  OUT({ms}ms,{b.get('next_action')}): {reply[:220]}\n")

# ---- Test A: greeting/first turn ----
s, c, H = new_conv()
st, b, ms = chat(c["id"], H, "Hi, I am exploring medical and wellness options. What do you offer?")
rec("A", "greeting+mixed intent", "Hi, I am exploring medical and wellness options. What do you offer?", st, b, ms)

# ---- Test B: medical tourism multi-turn ----
s, c, H = new_conv()
turns = ["I am interested in travelling abroad for a medical procedure.",
         "Cardiology.", "India.", "Next three months."]
for i, m in enumerate(turns):
    st, b, ms = chat(c["id"], H, m)
    rec(f"B{i+1}", "medical turn", m, st, b, ms)
# recall check
st, b, ms = chat(c["id"], H, "What destination did I say I prefer?")
rec("B5", "memory recall", "What destination did I say I prefer?", st, b, ms)

# ---- Test C: wellness ----
s, c, H = new_conv()
for i, m in enumerate(["I want a wellness and fitness retreat.", "Stress management and better sleep.", "Flexible on destination.", "Within six months."]):
    st, b, ms = chat(c["id"], H, m)
    rec(f"C{i+1}", "wellness turn", m, st, b, ms)

# ---- Test D: signature programmes ----
for name, q in [("HAYAT-100", "Tell me about HAYAT-100."),
                ("AAfiya", "Tell me about AAfiya."),
                ("FFounders", "Tell me about FFounders.")]:
    s, c, H = new_conv()
    st, b, ms = chat(c["id"], H, q)
    rec(f"D-{name}", "programme", q, st, b, ms, extra="check no invented price/dates")

# ---- Test E: ambiguous ----
s, c, H = new_conv()
st, b, ms = chat(c["id"], H, "I want to improve my health.")
rec("E", "ambiguous", "I want to improve my health.", st, b, ms)

# ---- Test F: memory via case facts ----
s, c, H = new_conv()
chat(c["id"], H, "I need help with medical travel.")
chat(c["id"], H, "Dental treatment.")
chat(c["id"], H, "Germany please.")
st, prog = req("GET", f"/v1/conversations/{c['id']}", headers=H)
# fallback: fetch messages if conversation GET unsupported
if st != 200:
    _, msgs = req("GET", f"/v1/conversations/{c['id']}/messages", headers=H)
    prog = msgs
st, b, ms = chat(c["id"], H, "Can you remind me what I asked for help with?")
rec("F", "memory recall", "Can you remind me what I asked for help with?", st, b, ms,
    extra=f"prog_status={st}")

# ---- Test G: tone/conciseness already covered; add pushy-check turn ----
s, c, H = new_conv()
for m in ["Hello.", "Just browsing, no rush."]:
    st, b, ms = chat(c["id"], H, m)
    rec(f"G-{m[:6]}", "tone", m, st, b, ms)

open("qa_results.json", "w", encoding="utf-8").write(json.dumps(results, indent=2, ensure_ascii=False))
print(f"Wrote qa_results.json — {len(results)} records")
