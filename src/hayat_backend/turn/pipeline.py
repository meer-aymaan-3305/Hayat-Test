"""One chat turn in signup handoff mode, as named steps in a fixed order.

This is the turn every visitor gets in production (SIGNUP_HANDOFF and EXTENDED_INTAKE on). It
replaces the handoff branches that were interleaved with the older intake bot inside
``ChatService.respond`` (IMPLEMENTATION.md, root cause RC1). The steps:

1. understand   read the message: code first (pre_extract), the extraction model when needed
2. remember     write slot updates through the attribution rules (flow.apply_analysis), recover
3. inspect      the policy engine's safety decision
4. decide       the flow controller's next action, and the flow facts it implies
5. source       a verbatim safety script, the knowledge playbook, or a style example
6. compose      the reply model, with the Addendum's prompt order, then the turn guard
7. finish       house style, links, suggestions, transcript, response

The service object is read on every turn, never copied: tests and the API swap the analyzer,
model, retriever, planner and links on a live service.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from .. import chat_service as cs
from ..audit_logging import global_audit_store
from ..flow import (
    apply_analysis, change_asked_write, flow_state_for, focus_lane, lanes_active, next_flow_state,
    rebuild_writes, state_problems, state_snapshot, stuck_slot_writes, user_turn_count,
)
from ..guardrails import GuardrailDecision, inspect_input, redact_message, validate_output
from ..kb_playbook import respond as kb_respond
from ..llm import LLMError
from ..pre_extract import fallback_analysis, fast_analysis, reinforce
from ..reference import enquiry_reference
from ..schemas.chat import ChatAction
from ..schemas.intake import FactStatus, FactValue
from ..slots import BY_KEY, SlotState
from ..training_scripts import house_style
from ..turn_analyzer import TurnAnalysis
from ..turn_guard import safe_reply

logger = logging.getLogger("hayat.chat")

# Built-in passages written before the approved documents existed. Nothing in the Signature
# Programmes or company knowledge base backs them (JCI claims, destination rankings, a wider
# wellness catalogue, a records checklist), so the production turn never treats them as facts.
_UNAPPROVED_BUILTINS = {
    "hayat-destinations-v1", "hayat-destinations-ar-v1", "hayat-wellness-v1", "hayat-wellness-ar-v1",
    "hayat-coordination-v1", "hayat-prep-v1", "hayat-prep-ar-v1",
}
# Passages that instruct Hayat rather than describe trawellcare.
_GUIDANCE = re.compile(
    r"\bhayat (?:must|should|can confidently|must not|should never)\b|suggested (?:response|company description)|"
    r"information hayat must not|hayat's knowledge and response rules|policy boundary",
    re.IGNORECASE,
)


@dataclass
class Turn:
    """Everything one turn knows, passed from step to step."""

    conversation: Any
    text: str
    language: str
    client_message_id: str | None
    visitor: str | None
    use_ai: bool
    shadow_ai: bool
    document_context: str | None
    user_message: Any = None
    analysis: TurnAnalysis | None = None
    pending_field: str | None = None
    slot_changes: list[tuple[str, str]] = field(default_factory=list)
    recap: bool = False
    decision: Any = None
    plan: Any = None
    progress: Any = None
    profile: Any = None
    verbatim: str | None = None  # a reply used as written (safety script or knowledge playbook)
    style_ref: str | None = None
    chips: list[str] = field(default_factory=list)
    chunks: list = field(default_factory=list)
    scored_chunks: list = field(default_factory=list)
    reply: str | None = None
    used_knowledge: bool = False
    model_outage: bool = False
    safe_fallback: bool = False
    first_message: bool = False
    parts: dict[str, str] | None = None  # acknowledge, answer, bridge, ask (structured replies)
    guard: dict = field(default_factory=dict)
    state_before: dict = field(default_factory=dict)
    started: float = 0.0
    source_kind: str = "model"  # model, playbook, script, policy, fallback


async def run_handoff_turn(
    svc: Any, conversation: Any, text: str, *, language: str, client_message_id: str | None,
    visitor: str | None, use_ai: bool, shadow_ai: bool, document_context: str | None,
) -> dict[str, object]:
    turn = Turn(
        conversation=conversation, text=text, language=language, client_message_id=client_message_id,
        visitor=visitor, use_ai=use_ai, shadow_ai=shadow_ai, document_context=document_context,
    )
    turn.first_message = not any(m.role == "user" for m in conversation.messages)
    turn.started = time.monotonic()
    turn.state_before = state_snapshot(conversation)
    await _understand(svc, turn)
    await _remember(svc, turn)
    _inspect(svc, turn)
    _decide(svc, turn)
    _source(svc, turn)
    await _compose(svc, turn)
    return await _finish(svc, turn)


# ---- 1. understand ------------------------------------------------------------------------------
async def _understand(svc: Any, t: Turn) -> None:
    conversation = t.conversation
    t.pending_field = svc.question_planner.current_pending_field(conversation)
    fast: TurnAnalysis | None = None
    task = None
    if svc.analyzer is not None and t.language == "en":
        earlier = [m.content for m in conversation.messages if m.role == "assistant"]
        offered_at = conversation.case_facts.get("handoff_offer_turn")
        fast = fast_analysis(
            t.text,
            handoff_just_offered=bool(offered_at) and str(offered_at) == str(len(earlier)),
            kb_would_answer=kb_respond(
                t.text, recent_text=" ".join(m.content for m in conversation.messages[-6:]),
                state=SlotState(conversation.case_facts), focus=focus_lane(conversation.case_facts),
                last_assistant=earlier[-1] if earlier else "", answered_before=earlier[-3:],
            ) is not None,
            turn_analysis_cls=TurnAnalysis,
        )
    if svc.analyzer is not None and fast is None:
        last_assistant = next((m.content for m in reversed(conversation.messages) if m.role == "assistant"), "")
        task = asyncio.create_task(svc.analyzer.analyze(
            text=redact_message(t.text),
            last_assistant=last_assistant,
            pending_field=t.pending_field,
            known={
                k: v for k, v in conversation.case_facts.items()
                if not isinstance(v, dict) and v not in (None, "") and k in cs._ANALYZER_CONTEXT_FIELDS
            },
            state=state_snapshot(conversation),
        ))

    # The redacted message is saved while the model reads it.
    t.user_message = svc.store.append_message(conversation, "user", redact_message(t.text), t.language)
    analysis = fast
    if task is not None:
        analysis = await task
        if analysis is None:
            # The extraction model was unavailable: read what code can, rather than nothing.
            earlier = [m for m in conversation.messages[:-1] if m.role == "assistant"]
            offered_at = conversation.case_facts.get("handoff_offer_turn")
            analysis = fallback_analysis(
                t.text, TurnAnalysis, pending_slot=conversation.case_facts.get("pending_slot") or None,
                lanes=lanes_active(conversation.case_facts), focus=focus_lane(conversation.case_facts),
                handoff_just_offered=bool(offered_at) and str(offered_at) == str(len(earlier)),
            )
            logger.warning("turn_analysis unavailable conversation=%s; using the code reading", conversation.id)
    if analysis is not None:
        # The model read a redacted copy; the specialty word itself is read here, in code.
        analysis = reinforce(analysis, t.text, conversation.case_facts.get("pending_slot"))
        logger.info(
            "turn_analysis conversation=%s intent=%s category=%s fact_keys=%s pending=%s",
            conversation.id, analysis.intent, analysis.category, sorted(analysis.facts), t.pending_field,
        )
    t.analysis = analysis
    global_audit_store.log_transcript(
        session_id=conversation.session_id, conversation_id=conversation.id,
        sequence=len(conversation.messages), role="user", content=redact_message(t.text), language=t.language,
    )


# ---- 2. remember --------------------------------------------------------------------------------
def _facts(t: Turn, writes) -> list[FactValue]:
    return [
        FactValue(field_name=key, value=str(value), status=FactStatus.CONFIRMED,
                  source_message_id=t.user_message.id, confidence=1.0)
        for key, value in writes
    ]


async def _remember(svc: Any, t: Turn) -> None:
    conversation = t.conversation
    # G11: the state object must be present, valid and current. If it is not, it is cleared and
    # rebuilt from the visitor's recent messages (addendum 5.2), never silently trusted.
    problems = state_problems(conversation.case_facts)
    if problems:
        logger.warning("turn_guard G11 conversation=%s problems=%s", conversation.id, problems)
        svc.store.save_fact_updates(conversation, _facts(t, [
            ("slot_meta", "{}"), ("lanes_active", ""), ("focus_lane", ""), ("pending_slot", ""),
            ("flow_state", "DISCOVERY"), ("previous_flow_state", ""),
        ]))
    if not conversation.case_facts.get("visitor_language"):
        svc.store.save_fact_updates(conversation, _facts(t, [("visitor_language", t.language)]))
    if t.analysis is not None:
        writes = apply_analysis(conversation, t.analysis, user_turn_count(conversation))
        t.slot_changes = [
            (BY_KEY[k].label, str(v)) for k, v in writes
            if k in BY_KEY and v and str(v).lower() not in {"unsure", "declined"}
            and str(conversation.case_facts.get(k)) != str(v)  # only what is new this turn
        ]
        if writes:
            svc.store.save_fact_updates(conversation, _facts(t, writes))
    # Recovery (addendum 5.2): the state is empty after several turns, so rebuild it from what
    # was said, mark every value HEARD, and have Hayat confirm it with the visitor.
    if svc.analyzer is not None and t.analysis is not None:
        lost = user_turn_count(conversation) >= 3 and not lanes_active(conversation.case_facts) and not t.analysis.slots
        if lost or problems:
            rebuilt = await rebuild_writes(svc.analyzer, conversation)
            if rebuilt:
                t.recap = True
                svc.store.save_fact_updates(conversation, _facts(t, rebuilt))
    # Nothing else writes the visitor's details: the slot store is the only writer.
    t.profile = svc.store.save_fact_updates(conversation, [])


# ---- 3. inspect ---------------------------------------------------------------------------------
def _inspect(svc: Any, t: Turn) -> None:
    conversation = t.conversation
    decision = inspect_input(
        t.text, conversation=conversation, pending_field=t.pending_field, extracted_facts=[],
        language=t.language,
        allow_clinical_context=(svc.collect_diagnosis and t.pending_field == "condition_context_for_advisor"),
    )
    if t.analysis is not None and decision.reason in {"out_of_scope", "unsolicited_clinical_detail", "medical_advice"}:
        # The model's reading decides what is on topic; the keyword rule behind these canned
        # refusals cannot tell "do you cover dental?" from "who is the president?".
        decision = GuardrailDecision()
    if decision.blocked:
        if decision.reason in ("possible_emergency", "EF-9"):
            conversation.emergency_locked = True
            conversation.state = "escalated"
        elif decision.reason in ("crisis_self_harm", "EF-10"):
            conversation.crisis_locked = True
            conversation.state = "escalated"
    # Appendix B persona is kept on the conversation for the coordinator card.
    persona_name, persona_status, _note = cs.global_policy_engine.evaluate_persona(conversation.case_facts)
    conversation.persona_name, conversation.persona_status = persona_name, persona_status
    t.decision = decision


# ---- 4. decide ----------------------------------------------------------------------------------
def _decide(svc: Any, t: Turn) -> None:
    conversation, analysis = t.conversation, t.analysis
    t.progress = svc.store.consultation_progress(conversation)
    plan = svc.question_planner.plan(
        text=t.text, conversation=conversation, decision=t.decision, progress=t.progress,
        visitor=t.visitor, intent=analysis.intent if analysis else None,
        submitted=bool(conversation.consultation_id), analysis=analysis,
    )
    marks: list[tuple[str, str]] = []
    assistants_after = sum(1 for m in conversation.messages if m.role == "assistant") + 1
    if plan.decision_type == "signup_handoff":
        marks += [("handoff_offered", "yes"), ("handoff_offer_turn", str(assistants_after))]
    elif plan.decision_type == "handoff_declined":
        marks += [("handoff_declined", "yes"), ("decline_turn", str(user_turn_count(conversation)))]
    elif plan.decision_type == "stop_intake":
        marks.append(("under_18", "yes"))
    elif plan.decision_type == "opt_out":
        marks.append(("opt_out_requested", "yes"))
        logger.warning("opt_out_requested conversation=%s", conversation.id)
    if analysis is not None:
        if plan.slot_id:  # the slot this turn asks about, so its answer lands in the right place
            marks.append(("pending_slot", plan.slot_id))
        marks += [(k, str(v)) for k, v in stuck_slot_writes(conversation, user_turn_count(conversation), {})]
    if plan.decision_type == "confirm_change":
        marks += change_asked_write(conversation.case_facts)
    pasted_secret = t.decision.reason in {"credential_payment_pasted", "EF-6"}
    candidate = "SAFETY_HOLD" if pasted_secret else flow_state_for(
        plan, conversation.case_facts, analysis.intent if analysis else None,
    )
    marks += next_flow_state(conversation.case_facts, candidate, returnable=pasted_secret)
    if len(lanes_active(conversation.case_facts)) > 1:
        marks.append(("two_lanes_named", "yes"))
    svc.store.save_fact_updates(conversation, _facts(t, marks))
    svc.store.set_conversation_state(conversation, svc._state_for_plan(plan, conversation))
    t.plan = plan


# ---- 5. source ----------------------------------------------------------------------------------
def _source(svc: Any, t: Turn) -> None:
    """Safety scripts S13 to S15 and the definition are used as written; every other scenario
    script is a style example (Addendum 7.2). The knowledge playbook answers the situations
    the Signature Programmes document covers, with its own text and question."""
    conversation, plan, analysis = t.conversation, t.plan, t.analysis
    if t.language != "en":
        return
    scripted = svc._scenario_reply(plan, analysis, t.decision, conversation)
    if scripted is not None:
        text, chips, verbatim = scripted
        if verbatim:
            t.verbatim, t.chips, t.source_kind = text, list(chips), "script"
        else:
            t.style_ref, t.chips = text, list(chips)
    if (
        t.verbatim is None and not t.decision.blocked and analysis is not None
        and plan.decision_type in {"collect_detail", "answer", "clarify_category", "clarify_lane"}
        and analysis.intent not in cs._KB_SKIP_INTENTS
    ):
        earlier = [m.content for m in conversation.messages[:-1] if m.role == "assistant"]
        kb = kb_respond(
            t.text, recent_text=" ".join(m.content for m in conversation.messages[-6:]),
            state=SlotState(conversation.case_facts), focus=focus_lane(conversation.case_facts),
            last_assistant=earlier[-1] if earlier else "", answered_before=earlier[-3:],
        )
        if kb is not None:
            t.verbatim, t.chips, t.source_kind = house_style(kb.text), list(kb.chips), "playbook"
            svc.store.save_fact_updates(conversation, _facts(t, [("pending_slot", kb.slot or "")]))
            logger.info("kb_playbook conversation=%s topic=%s", conversation.id, kb.topic)


# ---- 6. compose ---------------------------------------------------------------------------------
async def _compose(svc: Any, t: Turn) -> None:
    conversation, plan, analysis, decision = t.conversation, t.plan, t.analysis, t.decision
    if t.verbatim is not None:
        t.reply = t.verbatim  # source_kind was set when the script or playbook entry was chosen
        if t.source_kind == "playbook":
            # The document's own text is used as written; the guard still reads it so that a
            # repeated answer or a stray format problem shows up in the turn record (log only).
            from ..turn_guard import check as guard_check

            history = [m.content for m in conversation.messages[:-1] if m.role == "assistant"]
            seen = guard_check(
                t.verbatim, user_text=t.text, plan=plan, state=SlotState(conversation.case_facts),
                focus=focus_lane(conversation.case_facts), active=lanes_active(conversation.case_facts),
                assistant_history=history, knowledge=t.verbatim, turn=user_turn_count(conversation),
            )
            t.guard = {"failures": seen.failures, "log_only": True}
        return
    if decision.reason == "out_of_scope":
        t.reply, t.source_kind = cs._out_of_scope(t.language), "policy"
        return
    if decision.reply:
        t.reply, t.source_kind = decision.reply, "policy"
        return

    # Facts only from approved knowledge (Addendum 6.1): instructions to Hayat inside the documents
    # and the old built-in passages that no approved document backs are never shown as facts.
    scored = await svc.retriever.retrieve_scored(t.text, limit=6)
    t.scored_chunks = [
        (score, chunk) for score, chunk in scored
        if chunk.source.document_id not in _UNAPPROVED_BUILTINS and not _GUIDANCE.search(chunk.text)
    ][:2]
    t.chunks = [chunk for _, chunk in t.scored_chunks]
    # Stale documents can still say AAfiya or Medical Advisor: correct them first.
    knowledge = house_style("\n\n".join(chunk.text for chunk in t.chunks))
    if analysis is not None and analysis.intent in {"answering", "declines", "off_topic"} and not cs._PROGRAMME_NAME_RE.search(t.text):
        knowledge = ""  # a plain answer needs no company evidence, and it stops embellishment
    # The composer asks for the reply in four labelled parts when the model supports JSON.
    structured = getattr(svc.model, "supports_json", False) is True
    messages = svc._handoff_prompt(
        conversation, plan, analysis, t.language, knowledge, t.chunks, t.text,
        t.document_context, t.style_ref, t.recap, structured=structured,
    )
    if t.shadow_ai and not t.use_ai:
        svc._start_shadow(conversation.id, messages, t.language)
    if t.use_ai:
        try:
            generated = await (svc.model.complete(messages, json_mode=True) if structured else svc.model.complete(messages))
            if generated:
                generated, model_chips, t.parts = cs.read_model_output(generated)
                t.chips = model_chips or t.chips  # the scenario's own chips are the fallback
            reply = validate_output(generated, t.language) if generated else None
            if reply:
                reply, t.safe_fallback = await svc._guarded(
                    reply, t.text, plan, conversation, knowledge, messages, t.language, t.slot_changes,
                    report=t.guard,
                )
                # A chat message: no markdown, bullets or paragraph breaks.
                reply = re.sub(r"[*_`#]+", "", reply)
                reply = re.sub(r"(?m)^\s*(?:[-•]|\d+[.)])\s+", "", reply)
                reply = re.sub(r"\s*\n+\s*", " ", reply).strip()
            t.reply = reply or None
            t.used_knowledge = t.reply is not None and bool(t.chunks)
        except (LLMError, TypeError, ValueError) as exc:
            logger.warning(
                "reply model unavailable (%s: %s); using a natural fallback",
                type(exc).__name__, type(exc.__cause__).__name__ if exc.__cause__ else "-",
            )
            t.reply = None

    if t.reply is None:
        t.source_kind = "fallback"
        # Never an error in the chat (addendum 5.2): a short reply that still refers to what
        # the visitor said. With the AI switched off, the flow's own question follows it.
        t.model_outage = t.use_ai and svc._model_is_live()
        outage_line = _outage_line(svc, t) if t.model_outage and t.language == "en" else None
        if t.style_ref and t.model_outage:
            t.reply = t.style_ref
        elif outage_line:
            t.reply = outage_line
        elif plan.decision_type == "close":
            t.reply = (
                "شكراً لك على وقتك. الاستشارة المجانية متاحة متى شئت. 😊" if t.language == "ar"
                else "Thank you for chatting with me. The free consultation is there whenever you want it, "
                "and I'm here if anything else comes up. 😊"
            )
        elif t.language == "ar":
            t.reply = "شكراً لك على مشاركة ذلك، أنا أستمع."
        else:
            t.reply = safe_reply(
                user_turn_count(conversation),
                next((m.content for m in reversed(conversation.messages[:-1]) if m.role == "assistant"), ""),
                [] if "?" in t.text else t.slot_changes,
                user_text=t.text,
            )
        if not t.model_outage:
            t.safe_fallback = False

    # The flow's question is added only when the reply asks nothing. The model's own question is
    # never swapped for the template: the guard already removes questions about settled slots,
    # and the Addendum lets Hayat ask the empty slot that follows most naturally (5.3).
    if not decision.reply and decision.reason != "out_of_scope":
        planned = plan
        if t.language == "ar" and plan.question_text in cs.ARABIC_QUESTIONS:
            from dataclasses import replace

            planned = replace(plan, question_text=cs.ARABIC_QUESTIONS[plan.question_text])
        if t.safe_fallback:
            pass  # the guard's safe reply asks nothing (addendum 5.2)
        elif t.model_outage and (plan.answer_first or "?" in t.text or plan.decision_type not in {"collect_detail", "clarify_category"}):
            pass  # while the model is down, a question the visitor asked is not followed by ours
        elif not plan.answer_first:
            # With the model down, the flow's own question keeps the conversation moving
            # instead of a string of "I'm listening" replies (live evaluation, scenario 15).
            last_assistant = next((m.content for m in reversed(conversation.messages[:-1]) if m.role == "assistant"), "")
            pattern = cs._GOAL_KEYWORDS.get(getattr(plan, "target_field", None) or "")
            already_asked = bool(pattern and "?" in last_assistant and re.search(pattern, last_assistant, re.I))
            if not already_asked:
                t.reply = cs.append_planned_question(t.reply, planned)
        else:
            t.reply = cs.enforce_single_question(t.reply)


def _outage_line(svc: Any, t: Turn) -> str | None:
    """While the model is unavailable, the steps that have approved wording still get it: the
    offer and its answers, a person request, a not sure or a no thanks, a health detail."""
    from ..training_scripts import SCRIPTS

    kind = t.plan.decision_type
    category = t.conversation.case_facts.get("customer_category")
    if kind == "signup_handoff":
        return SCRIPTS["S7" if category == "wellness" else "S6"].text
    if kind == "handoff_declined":
        return SCRIPTS["S8"].text
    if kind == "handoff_link":
        return "Wonderful, here is where you can create your free account or log in to book it. 😊"
    if kind == "human_request":
        return SCRIPTS["S10"].text.split(" If you'd prefer")[0]
    if t.analysis is not None and t.analysis.note == "instruction attempt":
        return "I can only help with your health and wellness plans, so I'll carry on from there. 😊"
    if t.analysis is not None and t.analysis.intent == "clinical_detail":
        return SCRIPTS["S3"].text
    statuses = {entry.get("status") for entry in (t.analysis.slots.values() if t.analysis else [])}
    if "DECLINED" in statuses:
        return "Of course, no need to share that. 😊"
    if "UNSURE" in statuses:
        return "No problem at all, that can be decided later. 😊"
    return None


# ---- 7. finish ----------------------------------------------------------------------------------
async def _finish(svc: Any, t: Turn) -> dict[str, object]:
    conversation, plan, decision, language = t.conversation, t.plan, t.decision, t.language
    reply = t.reply or ""
    # The signup link is given once the visitor has agreed, never with the offer itself.
    if (
        svc.signup_url
        and plan.decision_type in {"handoff_link", "handoff_declined", "close", "human_request"}
        and svc.signup_url not in reply
    ):
        reply += (
            f" You can sign in or create your free account here: {svc.signup_url}" if language == "en"
            else f" يمكنك تسجيل الدخول أو إنشاء حسابك المجاني من هنا: {svc.signup_url}"
        )
    if (
        t.first_message and not any(m.role == "assistant" for m in conversation.messages[:-1])
        and not decision.escalation_required
        and decision.reason not in ("possible_emergency", "crisis_self_harm", "EF-9", "EF-10")
        and not cs._GREETING_START_RE.match(reply)
    ):
        reply = cs._opening(language) + reply
    reply = house_style(reply)
    if not (decision.blocked or decision.escalation_required):
        reply = cs.humanize_reply(reply)  # approved policy scripts stay word for word

    assistant_message = svc.store.append_message(conversation, "assistant", reply, language)
    global_audit_store.log_transcript(
        session_id=conversation.session_id, conversation_id=conversation.id,
        sequence=len(conversation.messages), role="assistant", content=reply, language=language,
    )

    # Sources only when the reply relied on retrieved approved knowledge (score 2.0 or more).
    sources: list[dict[str, str]] = []
    if not decision.reply and decision.reason is None and t.used_knowledge:
        seen: set[str] = set()
        for score, chunk in t.scored_chunks:
            if score < 2.0 or chunk.source.document_id in seen:
                continue
            seen.add(chunk.source.document_id)
            sources.append({"document_id": chunk.source.document_id, "title": chunk.source.title,
                            "version": chunk.source.version})
            if len(sources) >= 3:
                break

    chips = t.chips
    if not chips and plan.decision_type not in cs._NO_CHIP_STEPS:
        chips = cs._fallback_chips(plan, conversation)  # the model left them out: never none
    suggestions = [
        ChatAction(action_id=f"next_{i}", type="message", label=house_style(chip), payload=house_style(chip),
                   relevance="follows from the reply")
        for i, chip in enumerate(chips, start=1)
    ]
    handoff, programme_enquiry = await asyncio.gather(
        asyncio.to_thread(svc.store.get_handoff_for_conversation, conversation.id),
        asyncio.to_thread(svc.store.get_programme_enquiry_for_conversation, conversation.id),
    )
    progress = t.progress
    result: dict[str, object] = {
        "user_message": t.user_message,
        "assistant_message": assistant_message,
        "language": language,
        "escalation_required": decision.escalation_required,
        "escalation_reason": decision.reason,
        "sources": sources,
        "policy_version": cs.POLICY_VERSION,
        "fact_updates": [],
        "persona_profile": t.profile,
        "conversation_state": conversation.state,
        "next_action": plan.decision_type,
        "suggestions": suggestions,
        "consultation_progress": progress,
        "answer": reply,
        "reply": reply,
        "follow_up_question": plan.question_text,
        "follow_up_target": plan.target_field or plan.question_goal,
        "profile_updates": [],
        "missing_required_fields": progress.missing_fields,
        "submission_status": progress.request_status,
        "consultation": None,
        "coordinator_handoff": handoff,
        "programme_enquiry": programme_enquiry,
        "service_category": "international_medical_travel",
        "ai_status": "unavailable" if t.model_outage else "ok",
        "reference": enquiry_reference(conversation) if conversation.case_facts.get("handoff_offered") else None,
    }
    result["suggested_actions"] = result["suggestions"]
    _record(t, reply, sources)
    svc.store.cache_chat(conversation.id, t.client_message_id, result)
    return result


def _record(t: Turn, reply: str, sources: list[dict[str, str]]) -> None:
    """One TurnRecord per reply (Addendum part 8): what was said, the state before and after,
    the decision, the guard results and the knowledge passages relied on. Admin module only."""
    conversation = t.conversation
    try:
        global_audit_store.log_turn({
            "conversation_id": str(conversation.id),
            "turn": user_turn_count(conversation),
            "visitor_message": redact_message(t.text),
            "intent": t.analysis.intent if t.analysis else None,
            "next_action": t.plan.decision_type,
            "flow_state": conversation.case_facts.get("flow_state"),
            "state_before": t.state_before,
            "state_after": state_snapshot(conversation),
            "reply": reply,
            "reply_source": t.source_kind,
            "structured": t.parts is not None,
            "guard": t.guard,
            "passage_ids": [c.source.document_id for c in t.chunks],
            "sources_shown": [s["document_id"] for s in sources],
            "model_outage": t.model_outage,
            "latency_ms": int((time.monotonic() - t.started) * 1000),
        })
    except Exception:  # the log must never break the chat
        logger.exception("could not write the turn record")
