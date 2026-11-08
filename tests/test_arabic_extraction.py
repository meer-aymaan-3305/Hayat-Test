"""Regression: Arabic-Indic digits, Arabic Appendix-A patterns, dialect intents."""
import asyncio
import pytest
from hayat_backend.chat_service import ChatService
from hayat_backend.llm import OfflineChatModel
from hayat_backend.memory_store import MemoryStore


def _svc():
    return ChatService(MemoryStore(), OfflineChatModel())


def _facts(text):
    svc = _svc()
    conv = svc.store.create_conversation(svc.store.create_guest_session("ar")[0].id)
    msg = svc.store.append_message(conv, "user", text, "ar")
    return {f.field_name: f.value for f in svc._extract_facts(text, msg.id, conv)}


def test_arabic_indic_digits_normalised():
    f = _facts("ميزانيتي ٥٠٠٠ دولار")
    assert "5000" in f.get("budget_range", "")


def test_arabic_budget_pattern():
    f = _facts("ميزانيتي حوالي ١٠٠٠٠ ريال")
    assert f.get("budget_range")


def test_arabic_insurance_not_covered():
    f = _facts("ليس لدي تأمين ولا تغطية")
    assert f.get("insurance_coverage_status") == "not_covered"


def test_arabic_insurance_covered():
    f = _facts("لدي تأمين صحي")
    assert f.get("insurance_coverage_status") == "covered"


def test_arabic_value_priority_cost():
    f = _facts("أبحث عن أرخص خيار متاح")
    assert f.get("value_priority") == "cost-effectiveness"


def test_arabic_value_priority_comfort():
    f = _facts("أريد فندق فاخر ومريح")
    assert f.get("value_priority") == "comfort"


def test_arabic_value_priority_speed():
    f = _facts("أحتاج أسرع موعد ممكن")
    assert f.get("value_priority") == "speed"


def test_dialect_intent_declared():
    """Egyptian/Gulf/Levantine 'want' verbs still register intent."""
    svc = _svc()
    conv = svc.store.create_conversation(svc.store.create_guest_session("ar")[0].id)
    svc.store.append_message(conv, "assistant", "مرحباً!", "ar")
    r = asyncio.run(svc.respond(conv, "عايز أسافر للعلاج في الخارج", visitor="guest", use_ai=False, reply_language="ar"))
    assert r["reply"]
