"""HB-3: Hayat never names, ranks or recommends providers, whatever the AI writes."""

import pytest

from hayat_backend.guardrails import inspect_input, redact_message, validate_output
from hayat_backend.policy_engine import EF_SCRIPTS_AR, EF_SCRIPTS_EN


@pytest.mark.parametrize(
    "reply",
    [
        "In India, some of the best hospitals for cardiology include:\n\n1. Apollo Hospitals: a dedicated Cardiac Care Center.",
        "For cardiac issues, India is a suitable option due to its expertise.",
        "I recommend you visit Sunrise Heart Hospital in Dubai.",
        "Cleveland Clinic has a strong reputation.",
        "The top surgeons work in Bangkok.",
        "I can assist you with medical queries, hospital recommendations, and travel planning.",
    ],
)
def test_replies_that_steer_towards_a_provider_are_replaced(reply):
    assert validate_output(reply, "en") == EF_SCRIPTS_EN["EF-3"]


def test_arabic_visitors_get_the_arabic_script():
    assert validate_output("أفضل مستشفى هو أبولو", "ar") == EF_SCRIPTS_AR["EF-3"]


@pytest.mark.parametrize(
    "reply",
    [
        "Understood. Which destination would you prefer?",
        "A case manager will prepare tailored options with internationally accredited partners.",
        "What timeframe would suit you best?",
    ],
)
def test_ordinary_replies_pass_through(reply):
    assert validate_output(reply, "en") == reply


@pytest.mark.parametrize(
    "question",
    ["Which hospital is the best in India?", "Which country is best for heart surgery?", "What are the top hospitals in Dubai?", "best doctor for knees", "ما هو أفضل مستشفى في الهند؟"],
)
def test_requests_for_a_recommendation_are_recognised(question):
    decision = inspect_input(question)
    assert decision.reply is not None


@pytest.mark.parametrize(
    "message, removed",
    [
        ("I have type 2 diabetes and want a check-up", "diabetes"),
        ("I am taking metformin daily", "metformin"),
        ("I was diagnosed with cancer last year", "diagnosed"),
        ("عندي مرض السكري", "السكري"),
    ],
)
def test_medical_details_are_removed_before_saving(message, removed):
    assert removed not in redact_message(message)
    assert "[REDACTED_CLINICAL_DETAIL]" in redact_message(message)


@pytest.mark.parametrize("message", ["Cardiology: I would like to travel for treatment", "I prefer Japan.", "Tell me about AAfiya"])
def test_ordinary_requests_are_saved_as_typed(message):
    assert redact_message(message) == message


def test_everyday_arabic_is_not_mistaken_for_a_diagnosis():
    reply = "سنعد لك خطة شخصية تناسب تفضيلاتك."
    assert validate_output(reply, "ar") == reply
