"""Regression: QA session 1.1 — flexible destination, relative timing, recall."""
import asyncio
from hayat_backend.chat_service import ChatService
from hayat_backend.llm import OfflineChatModel
from hayat_backend.memory_store import MemoryStore


def _svc():
    return ChatService(MemoryStore(), OfflineChatModel())


def _conv(svc, lang="en"):
    return svc.store.create_conversation(svc.store.create_guest_session(lang)[0].id)


def _facts(text, lang="en"):
    svc = _svc()
    conv = _conv(svc, lang)
    msg = svc.store.append_message(conv, "user", text, lang)
    return {f.field_name: f.value for f in svc._extract_facts(text, msg.id, conv)}


# --- Flexible destination ---

def test_flexible_destination_en():
    assert _facts("Flexible on destination.")["destination_preference"] == "Flexible"

def test_flexible_destination_ar():
    assert _facts("مرن في اختيار الوجهة", "ar")["destination_preference"] == "Flexible"

def test_no_preference_destination():
    assert _facts("No preference on destination.")["destination_preference"] == "Flexible"

# --- Relative timing (no date conversion) ---

def test_within_six_months():
    assert _facts("Within six months.")["preferred_timing"].rstrip(".") == "Within six months"

def test_in_next_six_months():
    v = _facts("In the next six months.")["preferred_timing"]
    assert "six months" in v.lower()

def test_sometime_over_next_six_months():
    v = _facts("Sometime over the next six months.")["preferred_timing"]
    assert "six months" in v.lower()

def test_within_6_months_digits():
    v = _facts("Within 6 months.")["preferred_timing"]
    assert "6 months" in v

# --- Deterministic recall ---

def _recall(text, lang="en"):
    svc = _svc()
    conv = _conv(svc, lang)
    svc.store.append_message(conv, "assistant", "Hi!", lang)
    svc.case_facts_update = None
    conv.case_facts.update({
        "customer_category": "medical_treatment",
        "procedure_or_service": "Cardiology",
        "destination_preference": "India",
        "preferred_timing": "next three months",
    })
    svc.store.append_message(conv, "user", text, lang)
    return asyncio.run(svc.respond(conv, text, visitor="guest", use_ai=False, reply_language=lang))["reply"]


def test_recall_preferences_en():
    r = _recall("What did I tell you about my preferences?")
    assert "India" in r and "Cardiology" in r and "medical travel" in r

def test_recall_preferences_ar():
    r = _recall("ماذا أخبرتك عن تفضيلاتي؟", "ar")
    assert "الهند" in r or "India" in r

def test_recall_no_facts_falls_through():
    svc = _svc()
    conv = _conv(svc)
    svc.store.append_message(conv, "assistant", "Hi!", "en")
    r = asyncio.run(svc.respond(conv, "What are my preferences?", visitor="guest", use_ai=False))["reply"]
    assert "Here's what I have" not in r  # no fabricated recall
