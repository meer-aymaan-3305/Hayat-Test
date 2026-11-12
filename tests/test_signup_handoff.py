"""Signup handoff mode: the rules and the verbatim replies of the enhanced training document.

Chat never takes contact details, diagnosis, reports or consent. It collects only the
allowed enquiry fields, then offers the free consultation through signup or login. The
scenario replies S2 to S17 are the document's own words.
"""

import asyncio
import re
import uuid

from hayat_backend.chat_service import ChatService, greeting
from hayat_backend.memory_store import MemoryStore
from hayat_backend.question_planner import QuestionPlanner
from hayat_backend.training_scripts import SCRIPTS, lower_brand
from hayat_backend.turn_analyzer import TurnAnalysis


class StubModel:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    async def complete(self, messages):
        self.calls.append(messages)
        return "Of course."


class StubAnalyzer:
    """The real analyzer sees the redacted text, so unscripted texts get the default."""

    def __init__(self, script, default=None) -> None:
        self.script = script
        self.default = default

    async def analyze(self, *, text, last_assistant, pending_field, known):
        return self.script.get(text, self.default)


def _service(script, default=None, name_asked=True):
    store = MemoryStore()
    model = StubModel()
    service = ChatService(store, model)
    service.handoff = True
    service.question_planner = QuestionPlanner(extended=True, handoff=True)
    service.analyzer = StubAnalyzer(script, default)
    session, _ = store.create_guest_session("en")
    conversation = store.create_conversation(session.id)
    store.append_message(conversation, "assistant", greeting("en", 19, handoff=True), "en")
    if name_asked:  # most tests are about later steps, so the name was already asked
        store.append_message(conversation, "assistant", "What would you like me to call you?", "en")
        conversation.case_facts["preferred_name"] = "Maria"
    return service, model, conversation


def _say(service, conversation, text):
    return asyncio.run(service.respond(conversation, text, str(uuid.uuid4()), use_ai=True))


MEDICAL = TurnAnalysis(
    intent="answering", category="medical_treatment",
    facts={"procedure_or_service": "orthopaedics"},
)


def _offered(extra=None):
    script = {
        "knee surgery": MEDICAL,
        "Germany": TurnAnalysis(intent="answering", facts={"destination_preference": "Germany"}),
        "next month": TurnAnalysis(intent="answering", facts={"preferred_timing": "next month"}),
        **(extra or {}),
    }
    service, model, conversation = _service(script)
    for text in ["knee surgery", "Germany", "next month"]:
        _say(service, conversation, text)
    return service, model, conversation


# ---- S1 and the rules ------------------------------------------------------------------------
def test_s1_first_message_is_the_ai_introduction_in_the_visitors_time_of_day():
    text = greeting("en", 19, handoff=True)
    assert text == (
        "Good evening! 😊 I'm Hayat, trawellcare's AI concierge for health and wellness journeys. "
        "I can help you explore healthcare options and wellness experiences, and guide you to the "
        "right people on our team. How is your evening going?"
    )
    assert greeting("en", 9, handoff=True).startswith("Good morning")
    assert " - " not in text and "—" not in text


def test_trawellcare_is_always_lower_case():
    assert lower_brand("Welcome to TrawellCare and Trawellcare, TRAWELLCARE.") == (
        "Welcome to trawellcare and trawellcare, trawellcare."
    )
    for script in SCRIPTS.values():
        assert "Trawellcare" not in script.text and "TrawellCare" not in script.text


def test_a_reply_the_model_writes_is_lower_cased_too():
    class Shouty(StubModel):
        async def complete(self, messages):
            return "Welcome to Trawellcare! TrawellCare is glad you are here."

    service, _, conversation = _service({"hello": TurnAnalysis(intent="question")})
    service.model = Shouty()
    result = _say(service, conversation, "hello")
    assert "Trawell" not in result["reply"] and "trawellcare" in result["reply"]


# ---- S2: the optional name ---------------------------------------------------------------------
def test_s2_a_preferred_first_name_is_asked_once_and_is_optional():
    service, model, conversation = _service(
        {"I'm good, thanks": TurnAnalysis(intent="smalltalk")}, name_asked=False
    )
    first = _say(service, conversation, "I'm good, thanks")
    assert first["reply"] == SCRIPTS["S2"].text
    assert first["follow_up_target"] == "preferred_name"
    assert model.calls == []  # a scripted reply needs no model call
    service.analyzer.script["I'd rather not say"] = TurnAnalysis(intent="declines")
    second = _say(service, conversation, "I'd rather not say")
    assert conversation.case_facts.get("preferred_name") == "declined"
    assert second["follow_up_target"] != "preferred_name"


# ---- collection rules --------------------------------------------------------------------------
def test_only_allowed_fields_are_collected_and_never_diagnosis_or_contact():
    service, _, conversation = _service({
        "knee surgery please": MEDICAL,
        "Germany": TurnAnalysis(intent="answering", facts={"destination_preference": "Germany"}),
    })
    asked = [_say(service, conversation, t)["follow_up_target"] for t in ["knee surgery please", "Germany"]]
    forbidden = {
        "condition_context_for_advisor", "medical_reports_available", "phone_number",
        "email", "callback_time", "name",
    }
    assert not forbidden & set(asked)
    assert not forbidden & set(conversation.case_facts)


def test_a_medical_statement_is_never_stored_as_the_answer_to_a_question():
    service, _, conversation = _service(
        {"a longevity retreat": TurnAnalysis(
            intent="answering", category="wellness",
            facts={"wellness_programme_or_goal": "longevity retreat"})},
        default=TurnAnalysis(intent="answering"),
    )
    _say(service, conversation, "a longevity retreat")
    _say(service, conversation, "I have type 2 diabetes and take metformin")
    stored = " ".join(str(v) for v in conversation.case_facts.values()).lower()
    assert "diabetes" not in stored and "metformin" not in stored


# ---- S3 and S4: clinical detail, reports, and not repeating ------------------------------------
def test_s3_clinical_detail_gets_the_documents_reply_then_the_flow_continues():
    service, model, conversation = _offered()
    # The analyzer sees redacted text for clinical messages, hence the default.
    service.analyzer.default = TurnAnalysis(intent="clinical_detail")
    result = _say(service, conversation, "I also have asthma")
    assert result["reply"].startswith(SCRIPTS["S3"].text)
    assert "asthma" not in " ".join(str(v) for v in conversation.case_facts.values()).lower()


def test_a_repeated_condition_does_not_repeat_the_same_paragraph():
    service, _, conversation = _service({}, default=TurnAnalysis(intent="clinical_detail"))
    replies = [_say(service, conversation, f"I have condition number {i}")["reply"] for i in range(4)]
    assert replies[0].startswith(SCRIPTS["S3"].text)
    # The long reply is said once; later mentions get a short, different acknowledgement.
    assert all(SCRIPTS["S3"].text not in r for r in replies[1:])
    assert all(len(r) < len(replies[0]) for r in replies[1:])
    assert replies[1] != replies[2]


def test_s4_asking_to_interpret_a_report_gets_the_documents_reply():
    service, _, conversation = _service({}, default=TurnAnalysis(intent="asks_interpretation"))
    result = _say(service, conversation, "can you read my scan?")
    assert result["reply"].startswith(SCRIPTS["S4"].text)


# ---- S5 to S8: wellness, the offer, accepting and declining ------------------------------------
def test_s5_a_wellness_enquiry_asks_about_the_feeling_they_want():
    service, _, conversation = _service({
        "a retreat": TurnAnalysis(
            intent="answering", category="wellness",
            facts={"wellness_programme_or_goal": "retreat"},
        ),
    })
    result = _say(service, conversation, "a retreat")
    assert result["reply"] == SCRIPTS["S5"].text


def test_s6_the_medical_offer_is_the_documents_wording_and_given_once_enough_is_shared():
    service, _, conversation = _service({})
    service.analyzer.script.update({
        "knee surgery": MEDICAL,
        "Germany": TurnAnalysis(intent="answering", facts={"destination_preference": "Germany"}),
        "next month": TurnAnalysis(intent="answering", facts={"preferred_timing": "next month"}),
    })
    results = [_say(service, conversation, t) for t in ["knee surgery", "Germany", "next month"]]
    assert results[-1]["next_action"] == "signup_handoff"
    assert results[-1]["reply"] == SCRIPTS["S6"].text
    assert [a.label for a in results[-1]["suggestions"]] == ["Yes, take me to signup", "Not right now"]
    assert conversation.case_facts["handoff_offered"] == "yes"


def test_s7_wellness_visitors_are_offered_a_free_call_with_the_curator():
    script = {
        "a longevity retreat": TurnAnalysis(
            intent="answering", category="wellness",
            facts={"wellness_programme_or_goal": "longevity retreat", "wellness_goal": "longevity",
                   "destination_preference": "Spain"},
        ),
    }
    service, _, conversation = _service(script)
    result = _say(service, conversation, "a longevity retreat")
    assert result["next_action"] == "signup_handoff"
    assert result["reply"] == SCRIPTS["S7"].text


def test_accepting_the_offer_gives_the_signup_step_and_the_reference_without_contact_capture():
    service, model, conversation = _offered({"yes please": TurnAnalysis(intent="accepts")})
    result = _say(service, conversation, "yes please")
    assert result["next_action"] == "handoff_link"
    system = model.calls[-1][0]["content"]
    assert "Do not take any contact details here" in system
    assert result["reference"] in system and result["reference"].startswith("HYT-")


def test_s8_declining_the_offer_is_the_documents_reply():
    service, model, conversation = _offered({"not now": TurnAnalysis(intent="declines")})
    result = _say(service, conversation, "not now")
    assert result["next_action"] == "handoff_declined"
    assert result["reply"] == SCRIPTS["S8"].text
    assert conversation.case_facts["handoff_declined"] == "yes"


# ---- S9 to S12: contact, a person, stopping -----------------------------------------------------
def test_s9_contact_details_typed_in_chat_are_not_stored_and_get_the_documents_reply():
    service, _, conversation = _service({}, default=TurnAnalysis(intent="contact_request"))
    result = _say(service, conversation, "call me on +968 9123 4567 or maria@example.com")
    assert result["reply"].startswith(SCRIPTS["S9"].text)
    stored = " ".join(str(v) for v in conversation.case_facts.values())
    assert "9123" not in stored and "maria@example.com" not in stored
    assert "phone_number" not in conversation.case_facts and "email" not in conversation.case_facts


def test_s10_wanting_a_human_points_to_the_consultation_and_the_support_channel():
    service, _, conversation = _service({"can I talk to a person?": TurnAnalysis(intent="wants_human")})
    result = _say(service, conversation, "can I talk to a person?")
    assert result["next_action"] == "human_request"
    # The support channel is still to be confirmed, so that sentence is left out.
    assert result["reply"] == SCRIPTS["S10"].text.split(" If you'd prefer")[0]
    fresh, _, other = _service({"can I talk to a person?": TurnAnalysis(intent="wants_human")})
    fresh.support_contact = "support@example.org"
    assert "you can use support@example.org." in _say(fresh, other, "can I talk to a person?")["reply"]


def test_s11_stop_messaging_is_recorded_and_the_documents_reply_is_used():
    service, _, conversation = _service({"stop messaging me": TurnAnalysis(intent="wants_stop")})
    result = _say(service, conversation, "stop messaging me")
    assert result["next_action"] == "opt_out"
    assert result["reply"] == SCRIPTS["S11"].text
    assert conversation.case_facts["opt_out_requested"] == "yes"


def test_s12_a_whatsapp_or_phone_request_gets_the_documents_reply():
    service, _, conversation = _service({}, default=TurnAnalysis(intent="contact_channel"))
    result = _say(service, conversation, "can you WhatsApp me?")
    assert result["reply"].startswith(SCRIPTS["S12"].text)


# ---- S13 to S17: safety, age, secrets, identity, how it works -----------------------------------
def test_s13_an_emergency_gets_the_documents_reply_and_escalates():
    service, _, conversation = _service({})
    result = _say(service, conversation, "my father has chest pain and I don't know what to do")
    assert result["reply"] == SCRIPTS["S13"].text
    assert result["escalation_required"] is True


def test_s14_under_18_stops_the_intake_for_good():
    service, model, conversation = _service({
        "I'm 16": TurnAnalysis(intent="under_18"),
        "ok": TurnAnalysis(intent="answering"),
    })
    first = _say(service, conversation, "I'm 16")
    assert first["next_action"] == "stop_intake"
    assert first["reply"] == SCRIPTS["S14"].text
    assert _say(service, conversation, "ok")["next_action"] == "stop_intake"  # it stays stopped


def test_s15_a_pasted_password_gets_the_documents_reply_and_is_not_repeated():
    service, _, conversation = _service({}, default=TurnAnalysis(intent="answering"))
    result = _say(service, conversation, "my password is hunter2 and my card is 4111 1111 1111 1111")
    assert result["reply"].startswith(SCRIPTS["S15"].text)
    assert "hunter2" not in result["reply"] and "4111" not in result["reply"]


def test_s16_asking_if_hayat_is_a_person_gets_the_documents_reply():
    service, _, conversation = _service({"are you a real person?": TurnAnalysis(intent="asks_if_human")})
    result = _say(service, conversation, "are you a real person?")
    assert result["reply"].startswith(SCRIPTS["S16"].text)


def test_s17_how_does_trawellcare_work_gets_the_documents_explanation_once():
    service, model, conversation = _service({"how does trawellcare work?": TurnAnalysis(intent="how_it_works")})
    first = _say(service, conversation, "how does trawellcare work?")
    assert first["reply"] == SCRIPTS["S17"].text
    again = _say(service, conversation, "how does trawellcare work?")
    assert again["reply"] != first["reply"] and len(again["reply"]) < len(first["reply"])


# ---- flow, references, chips --------------------------------------------------------------------
def test_the_fifth_visitor_message_triggers_the_offer_even_with_little_shared():
    chat = {f"message {i}": TurnAnalysis(intent="smalltalk") for i in range(1, 6)}
    service, model, conversation = _service(chat)
    last = None
    for i in range(1, 6):
        last = _say(service, conversation, f"message {i}")
    assert last["next_action"] == "signup_handoff"
    assert conversation.case_facts["handoff_offered"] == "yes"


def test_no_generic_suggestion_buttons_are_sent():
    service, _, conversation = _service({"hello": TurnAnalysis(intent="smalltalk")})
    result = _say(service, conversation, "hello")
    assert result["suggestions"] == []
    assert result["suggested_actions"] == []


def test_hayat_never_invents_a_signup_link():
    service, model, conversation = _offered({"yes please": TurnAnalysis(intent="accepts")})
    _say(service, conversation, "yes please")
    system = model.calls[-1][0]["content"]
    assert "do not write any link" in system
    assert "Never write a web address" in system

    service.signup_url = "https://example.org/join"
    conversation.case_facts["handoff_offer_turn"] = str(
        sum(1 for m in conversation.messages if m.role == "assistant")
    )
    service.analyzer.script["sure"] = TurnAnalysis(intent="accepts")
    _say(service, conversation, "sure")
    assert "https://example.org/join" in model.calls[-1][0]["content"]


def test_suggested_next_steps_are_taken_from_the_reply_and_never_shown_as_text():
    from hayat_backend.chat_service import _split_chips

    reply, chips = _split_chips(
        "Happy to explain.\n[[chips: Tell me about AAfiya | How long is a retreat? | "
        "How long is a retreat? | email me at a@b.com | call +971 50 123 4567]]"
    )
    assert reply == "Happy to explain."
    assert chips == ["Tell me about AAfiya", "How long is a retreat?"]  # no duplicates or contact
    reply, chips = _split_chips("Sure thing. [[chips: One | Two")  # cut off by the token limit
    assert reply == "Sure thing." and chips == ["One", "Two"]
    assert _split_chips("No chips here.") == ("No chips here.", [])


def test_chips_reach_the_page_as_related_suggestions():
    class ChipModel(StubModel):
        async def complete(self, messages):
            self.calls.append(messages)
            return "AAfiya is our women's wellness programme. [[chips: How long is it? | Is it only for women?]]"

    service, _, conversation = _service({"what is AAfiya?": TurnAnalysis(intent="question")})
    service.model = ChipModel()
    result = _say(service, conversation, "what is AAfiya?")
    assert "[[" not in result["reply"] and "chips" not in result["reply"]
    assert [a.label for a in result["suggestions"]] == ["How long is it?", "Is it only for women?"]
    assert "SUGGESTED NEXT STEPS" in service.model.calls[-1][0]["content"]


def test_the_reference_is_a_short_readable_number_that_stays_the_same():
    from hayat_backend.reference import enquiry_reference

    service, _, conversation = _service({})
    first = enquiry_reference(conversation)
    assert re.fullmatch(r"HYT-\d{6}-\d{5}", first)
    assert enquiry_reference(conversation) == first
    assert enquiry_reference(_service({})[2]) != first


def test_the_chat_response_carries_what_the_page_needs():
    from fastapi.testclient import TestClient

    from hayat_backend.main import create_app

    with TestClient(create_app(store=MemoryStore())) as client:
        session = client.post("/v1/sessions/guest", json={"locale": "en"}).json()
        headers = {"X-Session-ID": session["session_id"], "X-Session-Token": session["session_token"]}
        conv = client.post(
            "/v1/conversations", headers={"X-Session-Token": session["session_token"]},
            json={"guest_session_id": session["session_id"]},
        ).json()
        body = client.post(
            "/v1/chat", headers=headers, json={"conversation_id": conv["id"], "message": "hello"}
        ).json()
        assert {"message_id", "suggestions", "reference", "ai_status"} <= set(body)


# ---- the definition, names and roles --------------------------------------------------------------
def test_what_is_trawellcare_gets_the_definition_word_for_word():
    service, _, conversation = _service({"what is trawellcare?": TurnAnalysis(intent="what_is_trawellcare")})
    result = _say(service, conversation, "what is trawellcare?")
    assert result["reply"] == (
        "trawellcare helps you explore and arrange healthcare and wellness experiences around the "
        "world, with everything in one place, from treatments and wellness programmes to flights, "
        "hotels, transport and payments. 😊 What are you hoping to find?"
    )
    assert [a.label for a in result["suggestions"]] == ["Medical treatment", "Wellness programmes"]
    again = _say(service, conversation, "what is trawellcare?")
    assert again["reply"] != result["reply"]  # a short variant, not the same paragraph again


def test_house_style_names_the_programme_zoe_and_uses_the_right_roles():
    from hayat_backend.training_scripts import house_style

    text = house_style("TrawellCare's AAfiya, or AAfiyah, is reviewed by a Medical Advisor. Our medical advisors help.")
    assert text == "trawellcare's Zoé, or Zoé, is reviewed by a Case manager. Our case managers help."
    assert "medical advis" not in " ".join(s.text.lower() for s in SCRIPTS.values())


def test_everything_hayat_says_is_stored_in_house_style():
    store = MemoryStore()
    session, _ = store.create_guest_session("en")
    conversation = store.create_conversation(session.id)
    said = store.append_message(
        conversation, "assistant", "Welcome to Trawellcare. Try AAfiya with a Medical Advisor.", "en"
    )
    assert said.content == "Welcome to trawellcare. Try Zoé with a Case manager."
    heard = store.append_message(conversation, "user", "I love Trawellcare and AAfiya", "en")
    assert heard.content == "I love Trawellcare and AAfiya"  # the visitor's own words are untouched


def test_the_model_is_told_the_names_and_roles():
    service, model, conversation = _service({"hello": TurnAnalysis(intent="question")})
    _say(service, conversation, "hello")
    system = model.calls[-1][0]["content"]
    assert "called Zoé" in system and "never use that name" in system
    assert "case manager" in system and "wellness curator" in system


def test_a_question_is_answered_first_and_the_offer_waits_for_a_plain_turn():
    chat = {f"message {i}": TurnAnalysis(intent="smalltalk") for i in range(1, 5)}
    chat["tell me about Zoe"] = TurnAnalysis(intent="question")
    chat["thanks"] = TurnAnalysis(intent="smalltalk")
    service, model, conversation = _service(chat)
    for i in range(1, 5):
        _say(service, conversation, f"message {i}")
    # The fifth visitor message is a question: it is answered, not met with a scripted offer.
    fifth = _say(service, conversation, "tell me about Zoe")
    assert fifth["next_action"] != "signup_handoff"
    assert fifth["reply"] not in {SCRIPTS["S6"].text, SCRIPTS["S7"].text}
    assert "handoff_offered" not in conversation.case_facts
    sixth = _say(service, conversation, "thanks")
    assert conversation.case_facts.get("handoff_offered") == "yes" or sixth["next_action"] == "signup_handoff"


# ---- the renamed programme is understood however it is typed ----------------------------------------
def test_zoe_is_recognised_in_every_spelling_by_the_older_programme_flow():
    from hayat_backend.memory_store import MemoryStore as Store
    from hayat_backend.programme_service import ProgrammeConversationService

    store = Store()
    session, _ = store.create_guest_session("en")
    conversation = store.create_conversation(session.id)
    flow = ProgrammeConversationService(store)
    for text in ["tell me about zoe", "Tell me about Zoé", "I want ZOE please", "what is aafiya"]:
        assert flow.is_programme_intent(text, conversation), text
    reply = flow.handle_programme_message(conversation=conversation, text="tell me about zoe", language="en")
    assert "Zoé" in reply["reply"] or "AAfiya" in reply["reply"]  # shown as Zoé once stored


def test_stale_knowledge_that_still_says_the_old_name_is_corrected_before_the_model_sees_it():
    from hayat_backend.rag import InMemoryRetriever, KnowledgeChunk, SourceReference

    stale = KnowledgeChunk(
        text="AAFIYA is our women's wellness programme, reviewed by a Medical Advisor.",
        source=SourceReference(document_id="old", title="Old", version="1"),
    )
    service, model, conversation = _service({"what is zoe?": TurnAnalysis(intent="question")})
    service.retriever = InMemoryRetriever([stale])
    _say(service, conversation, "what is zoe?")
    system = model.calls[-1][0]["content"]
    assert "Zoé is our women's wellness programme" in system
    assert "AAFIYA" not in system.split("<evidence>")[1] and "Medical Advisor" not in system.split("<evidence>")[1]
