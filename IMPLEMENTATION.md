# Hayat: audit against the Flow and State Addendum, and the plan to make it right

Written for: the engineers who will do the work, and the owner who decides the open items.
Date: 14 November 2026. Code audited: `streamlit-cloud-team-test` at commit `795f7fa`.
Source of requirements: `Hayat_Flow_and_State_Addendum_v1.docx`, read together with the Guardrail Document v1 (as corrected), the Enhanced Training Document v2.1, `Train Hayat.docx`, the Signature Programmes knowledge base and the company knowledge base. Precedence as the Addendum states: Guardrail, then Enhanced Training, then Addendum; the stricter rule wins.

---

## 1. Summary

The Addendum asks for two halves that ship together: behaviour rules (Parts 1 to 7, 9, 10) and four pieces of engineering outside the model (slot store, flow controller, turn guard, grounding with a claim check). Over the last two weeks the four pieces were added, but they were added **inside** an older chatbot rather than **instead of** it. The result is one 3,800 line `chat_service.py` in which two architectures compete for every turn: the old one (question planner, clarify ladder, programme enquiry capture, phone and OTP flow, canned FAQ replies, legacy fact extraction) and the new one (slots, flow controller, guard, playbook). Which one answers depends on feature flags, on whether the model is reachable, and on the order of twenty seven `if clarification_reply is None` branches.

That is the root cause of what you are seeing: replies that are sometimes right and sometimes "weird", suggestions that come and go, state that is right but wording that is wrong, and behaviour that changes when the model provider is slow. The Addendum's own diagnosis (Part 1) applies to the code as much as to the prompt: too many things decided in one place.

The plan below keeps what works (slot store, lanes, guard checks, playbook, registry, tests) and rebuilds the turn as **one pipeline with eight named steps**, deletes the legacy paths, ties extraction to a schema, makes the reply model return the four parts of the reply pattern as structured output, adds the claim check and the per turn log the Addendum requires, and puts a live evaluation harness around the 24 scenarios so regressions are caught before the team sees them.

Estimated effort: about three working weeks for one engineer, in six phases. Phase 0 (stop the bleeding on rate limits and fallbacks) is one to two days and should ship first.

---

## 2. Audit: Addendum part by part

Status key: **Done** means implemented and covered by tests. **Partial** means present but not to the Addendum's rule. **Missing** means not implemented.

### Part 2. Slot based memory

| Requirement | Status | Evidence and gap |
|---|---|---|
| Slot snapshot given to the model every turn, treated as truth | Done | `flow.state_snapshot` in the prompt (`chat_service._handoff_prompt`). |
| Four lanes MEDICAL, WELLNESS, GENERAL, UNDECIDED; medical and wellness never merged | Partial | Only MEDICAL and WELLNESS exist as lanes (`slots.py`). GENERAL and UNDECIDED exist only as flow states (`GENERAL_QA`, `DISCOVERY`). Acceptable, but the state object does not say so. |
| Shared slots: preferred name, residence country, language | Partial | `s.language` has no slot. Language is detected per message (`detect_language`) and not stored; the Arabic/English choice flips if one message looks different. |
| Slots hold only allowed labels, countries, windows, bands, counts | Partial | Values are stored as the analyzer returns them, after light cleaning. No validation against allowed values: `w.destination` was stored as "somewhere warm", `m.budget_band` as "about 8000", `w.dates_window` as "next one" (fixed by a regex, not by validation). |
| Status EMPTY, HEARD, CONFIRMED, UNSURE, DECLINED with the behaviour in 2.2 | Done | `slots.SlotState`. UNSURE "offer two or three options once" is not implemented; UNSURE is simply skipped. |
| Record carries status, value, source turn, history | Done | `slot_meta` JSON fact. |
| Guest slots session only; cross session only after login | Partial | Slots live in `case_facts` on the conversation in memory, 24 hour session TTL. There is no retention rule for the slot store distinct from the transcript and no login linkage. |
| Two journeys: name both back, focus pointer, say when switching, ask when ambiguous | Done | `flow.apply_analysis`, `TWO JOURNEYS` and `SWITCHING` instructions, `clarify_lane` step. Live run 9.1 passes. |

### Part 3. Reply pattern: Acknowledge, Answer, Bridge, Ask

| Requirement | Status | Evidence and gap |
|---|---|---|
| Every reply built in that order; skipping acknowledgement fails G2 | Partial | Enforced by prompt text only. G2 (`turn_guard.check`) catches two cases: a reply that is only a question, and a reply that opens with the same three words as the previous one. It does not detect "the reply did not refer to the latest message". |
| Answer before asking; only from KB or slots | Partial | `answer_first` steps exist. Whether the answer came from the KB is not checked (see G6 below). |
| At most one question | Done | G4. |
| Omit the question after an emotional share or when mid thought | Done | Emotional turns drop the question (`question_planner`, `_INTENT_GUIDANCE`). |
| Fill every slot covered in one message | Done | Multi slot writes per turn. |
| Accept an answer to a question not asked; do not return to the planned question as if ignored | Done | Planner always recomputes from state. |
| One word "ok / yes / maybe": answer the pending question if it fits, otherwise a gentle check | Done (recent) | `CHECK: the visitor sent a bare yes...` instruction. Not covered live yet. |
| Match length and energy | Missing | No rule in code or prompt. |
| Never the same acknowledgement pattern twice; no two replies starting with the same phrase in a conversation | Partial | `_same_opening` compares to the previous reply only; "Your last replies" lists three. Across a long chat openings repeat ("Got it, …" appeared four times in one run). |
| B9 formatting | Partial | Dashes are rewritten (`humanize_reply`); bullets are stripped by regex; nothing rewrites a list into sentences (G7). |

### Part 4. Attribution

| Requirement | Status | Evidence and gap |
|---|---|---|
| Rules 1 to 5 in order | Partial | Rule 1 (lane words) and rule 4 (ask) are in the analyzer prompt and in `flow.lane_unclear`. Rule 2 (pending slot takes the answer) is prompt only. Rule 3 (single active lane) is in `slot_updates`. Rule 5 is enforced by construction. The attribution is therefore mostly **the model's job**, and misses are patched with regexes in `flow.py` (`_RESIDENCE`, `_DONT_KNOW`, `_REFUSES`, the date question pop). Each live run found one more. |
| 4.1 Corrections: update, keep history, thank briefly, use the new value | Done | History kept; prompt rule 2. |
| 4.1 Switch of journey: resume the other lane, keep the first lane's slots, say so | Done | |
| 4.1 Contradiction without "correction": check once, lightly | Done (recent) | `confirm_change` step, `_settle_changes`. Covered by tests, not reached in a live run (the analyzer filled no slot for "what about Turkey?"). |
| 4.2 No slot for diagnosis, symptom, medication, report, contact detail, companion name or age | Done | Analyzer schema, `_handoff_filter`, redaction. The companion name regex (`_PERSONAL_DETAIL`) is a recent patch, not a rule in the extraction step. |

### Part 5. Flow state guard

| Requirement | Status | Evidence and gap |
|---|---|---|
| Named states, held by the application | Done | `flow_state` fact; `flow_state_for`. |
| Only the allowed transitions | Missing | The state is **computed after the fact** from the plan; nothing refuses a disallowed transition. GENERAL_QA "returns to the state it came from" is not tracked; the previous state is not stored. |
| G1 to G12 on every candidate reply; one regeneration; safe reply | Partial | Implemented: G1, G2 (weak), G3, G4, G5, G6 (price and promise only), G8, G9, G10, G12, plus a G13 for echoing the question. **G7** (format rewrite) and **G11** (state object present, valid and current) are missing. Scripted replies and playbook replies skip the guard entirely (`scripted=True`, `clarification_reply`). |
| 5.2 Recovery: rebuild as HEARD, "Let me make sure I have this right" | Done | `rebuild_writes`. Trigger is narrow: turn ≥ 3 and no lanes active. A corrupt `slot_meta` is not detected. |
| 5.2 Never an error message in chat | Done (recent) | Outage now gives a short natural reply. |
| 5.2 Log every guard failure with check ID, turn, state, to the admin module | Partial | Logged to the Python logger only (`hayat.guard`), not to the audit store or any admin endpoint. |
| 5.3 Priority order | Done | `flow.plan_handoff`. |
| 5.4 Handoff minimum per lane, two lanes offer once, cooling six messages | Done | |
| 5.5 Default order | Done | `slots.ORDER`. |

### Part 6. Grounding

| Requirement | Status | Evidence and gap |
|---|---|---|
| Three sources only: KB, slot store, transcript for tone | Partial | The reply prompt says so. Nothing verifies it. |
| Programme names only from the KB | Done | `programmes_registry`, `house_style` renames, folded alias search. |
| "I don't have those details" when the KB has no entry | Partial | Prompt rule 4 only. |
| No prices, availability, inclusions, partner or hospital names invented | Partial | Price regex, promise regex. Hospital names, inclusions, accreditations, durations are not checked. |
| Never name, compare, rank hospitals | Partial | Prompt only. |
| 6.3 Claim check: each factual sentence matched to a passage ID; unmatched removed or rewritten; IDs logged | **Missing** | This is the largest gap. `turn_log` prints `kb=see STATE`. |
| Knowledge base quality | Partial | Retrieval is BM25 over chunks that are split by character count, not by heading or sentence: one retrieved passage in a live prompt began "roved. Claim that specific hotels...". Section 7 of the programmes document ("Hayat must not...") is retrieved as if it were a fact about trawellcare. Only two passages are retrieved per turn. |
| Section 6 suggested responses and FAQ answers followed as written | Done (recent) | `kb_playbook.py` parses the 70 FAQs and section 6. It is a parser of one specific `.docx`; a reworded document breaks it silently. |

### Part 7. Prompt assembly

| Requirement | Status | Evidence and gap |
|---|---|---|
| Core block about 250 words | Partial | `_CORE_RULES` is about 420 words after the additions of the last week. |
| State snapshot, KB passages with IDs, last six messages, rolling slot only summary, script as style, latest message last | Partial | All present except the **rolling summary** of earlier turns. After six messages the model sees only the state object for earlier context; that is by design, but the Addendum wants a slot only summary too. |
| Separate the jobs: one extraction step, one reply step | Partial | Two calls exist. But the reply call is also asked to produce the suggestion chips, the recap, the two journeys naming, the privacy note, the health note and the bare answer check in one completion. Chips were missing whenever the model dropped the trailing line. |
| Low temperature for extraction, moderate for reply | Partial | Extraction 0. Reply uses `GROQ_TEMPERATURE` = 0.2 for everything. |
| Extraction fixed to the schema so it cannot invent fields | Partial | `response_format: json_object` only. Unknown slot IDs are dropped after the fact; values are not validated. Groq supports `json_schema` for the models in use; it is not used. |
| Visitor text is content, not instructions | Done | Prompt rule 9, anchor quoting, policy engine injection checks. |

### Part 8. What engineering must build

| Component | Status | Gap |
|---|---|---|
| Slot store | Done | Stored as flat facts plus a JSON blob inside `case_facts`, next to legacy facts (`contact`, `needs`, `consultation`, `schema_version`). Two representations of the same data. |
| Extraction step | Partial | See Part 7. |
| Flow controller | Partial | Chooses the next action; does not own the transition table. |
| Turn guard | Partial | See Part 5. |
| Grounding retrieval and claim check | Missing | See Part 6. |
| Knowledge base manager | Partial | Documents can be uploaded, replaced and deleted through `/v1/knowledge/documents`. Programme names live in `knowledge_seed/programmes.json`, which is a file in the repo, so a rename is a deploy, not a data change. No approval state. |
| Logging per turn: message, state snapshot, guard results, KB IDs, admin module only | Partial | Transcript events go to the audit store. State, guard and KB IDs go to the process log. |

### Part 9 and 11. Scenarios

Status from the test suite (stub analyzer, 524 passing) and from the live runs of 12 to 14 November against real models.

| # | Scenario | Tests | Live | Note |
|---|---|---|---|---|
| 1 | Treatment and destination in one message | Pass | Pass | |
| 2 | Every reply acknowledges the latest message | Weak | **Fail** | Seen: "A range is perfectly fine 😊" alone; "Got it, I've noted what to call them as Lina" to a knee question (outage fallback); openings repeated. |
| 3 | Medical then "retreat in Spain" | Pass | Pass | |
| 4 | Both lanes, "India" | Pass | Not run live | |
| 5 | Both lanes, "around June" | Pass | Not run live | |
| 6 | India in both lanes independently | Pass | Not run live | |
| 7 | Answers a different question | Pass | Pass | |
| 8 | Question mid intake, bridge back | Pass | Partial | Answered, but the bridge is often missing and the planned question is sometimes dropped. |
| 9 | Programme not in KB | Pass | Not run live | |
| 10 | Price or availability | Pass | Pass (playbook) | |
| 11 | Which hospital is best | Prompt only | **Inconsistent** | Two runs gave two different explanations; one said "we don't pick hospitals ourselves" (not in KB). |
| 12 | Correction | Pass | Pass | |
| 13 | "I don't know" | Pass | Pass | Options are not offered once as 2.2 asks. |
| 14 | Declines budget | Pass | Not run live | |
| 15 | One word answers for ten turns | Missing | Not run | |
| 16 | Declines signup, cooling six | Pass | Pass | |
| 17 | Asks to book or for a quote | Pass | Not run live | |
| 18 | State removed mid chat | Pass | Not run live | |
| 19 | Fifty turn conversation | **Missing** | Not run | No long run exists. |
| 20 | Instruction to set a slot | Pass (policy) | Not run live | |
| 21 | Volunteers diagnosis then continues | Pass | Partial | S3 style reply fine; the next reply did not always continue the intake. |
| 22 | Programme renamed in KB | Pass | Pass | |
| 23 | Regenerated reply still fails a guard | Pass | Pass | |
| 24 | Emergency mid intake | Pass | Pass | |

### Other documents, where they bear on the Addendum

| Document | Finding |
|---|---|
| Guardrail v1 EF-2 and EF-9 | Corrected in code (Oman 9999, "keep them out of your enquiry summary"). |
| Enhanced Training v2.1 B3 "AAfiya" | Replaced through the registry. The Signature Programmes `.docx` and the company knowledge base still say AAfiya; `house_style` renames at runtime. The documents themselves should be updated so the KB is the source of truth, as the Addendum insists. |
| Signature Programmes section 6.6 and FAQs "share your name and contact details with Hayat" | **Conflicts** with B0 and the Addendum (contact details only at signup). Code follows B0. The document should be amended or the owner should confirm. |
| Train Hayat sections 2 and 3 ask for diagnosis, reports, contact details and callback time in chat | Superseded by v2.1 and the Addendum. Code follows the newer rule. The old flow still exists in code behind `EXTENDED_INTAKE=false` and `SIGNUP_HANDOFF=false`. |
| Train Hayat section 8 "How trawellcare works" five stages, Hayat and Dawood matching | Covered by `how_trawellcare_works.txt` and S17 style. "Dawood" is not in the KB seed; the model cannot say it. Decide whether it should. |
| Company KB section 9 "missing company information" | Correctly not invented. Support channel placeholder is still empty (`SUPPORT_CONTACT`). |

---

## 3. Root causes

These eight explain every symptom above. Fixing symptoms one at a time, as the last week did, does not remove them.

**RC1. Two architectures in one method.** `ChatService.respond` is about 2,200 lines. It runs, in order: safety inspection, legacy pending field lookup, model analysis, slot writes, recovery, the signature programme enquiry service (when not extended), legacy fact extraction (skipped in handoff mode but still present), category change handling, persona ambiguity notes, consultation summary, service explainer, programmes overview, cost FAQ, consent evaluation, account replies, document replies, scenario scripts, the knowledge playbook, retrieval, the model, the guard, the legacy fallback ladder (`_clarify`, "Understood — you're interested in"), question alignment, link appending, chips. Twenty seven branches can set the reply before the flow controller's decision is used. Behaviour differs by `EXTENDED_INTAKE`, `SIGNUP_HANDOFF`, `self._model_is_live()`, language and visitor type. Nobody can predict which branch answers a given message, and every fix risks another path.

**RC2. Attribution and extraction are prompt based, then patched with regexes.** The Addendum's rules 1 to 5 are deterministic rules. In code they are instructions to the analyzer model, and every miss ("we're in Oman", "when is the next one?", "not sure" → UNSURE on three slots) became a regex in `flow.py`. There is no value validation (country, band, window, count), no schema enforcement, and the analyzer sees **redacted** text, so clinical words that decide the lane are sometimes blanked before it reads them.

**RC3. The reply call does several jobs.** It is asked to acknowledge, answer, bridge, ask, name both journeys, give a privacy note, do a health caveat, check a bare "yes", produce chips, and follow a style example, in one free text completion. The guard then has to reverse engineer which sentence was which. G2 cannot be checked properly because the acknowledgement is not a separate field; chips vanish because they are a trailing line; the "ask" cannot be verified against the pending slot because it is not labelled.

**RC4. Grounding is retrieval without a check.** Passages are retrieved and shown; nothing matches the reply's sentences back to them. The chunker splits by characters and the index mixes instruction text ("Hayat must not...") with facts, so retrieval sometimes feeds the model rules instead of knowledge. Hospital selection answers vary run to run because the model fills the gap.

**RC5. Provider limits turn into product behaviour.** Each turn is two model calls of about 1,200 to 1,700 prompt tokens each, against an 8,000 token per minute account limit shared by all Groq models, plus a Gemini backup on its own free tier. Three turns a minute exhaust it. Every fallback path ("That's a good question. I can't look that up...", safe replies, legacy ack strings) then shows to the visitor as "weird" behaviour. The fallbacks were tuned repeatedly; the budget was not.

**RC6. The state is two things.** Slot values are written as flat facts (`destination_preference`) **and** as `slot_meta`, next to legacy structures (`needs`, `contact`, `consultation`). Flow facts (`pending_slot`, `pending_change`, `two_lanes_named`, `lane_question`, `handoff_offer_turn`) are loose strings. There is no single typed state object to validate (G11), to log, or to reset.

**RC7. No live evaluation loop.** 524 tests run with a scripted analyzer and a canned model; they pin the controller logic, not the behaviour visitors see. The 24 scenarios have never been run end to end against real models in CI, there is no fifty turn run, and none of the 11.1 measures is computed. Regressions reach the Streamlit app first.

**RC8. Document conflicts are resolved ad hoc.** Contact capture (6.6 vs B0), scripts verbatim vs style (earlier request vs Addendum 7.2), AAfiya in two knowledge documents, "Dawood" in Train Hayat but not in the KB. Each was decided in a chat message. There is no precedence register the code and the team share.

---

## 4. Target architecture

One turn is one pipeline with eight steps. Each step is a module with one input and one output, and each is testable alone. The orchestrator is about 200 lines and contains no business rules.

```
visitor message
   │
   ▼
1. Ingress          language, redaction (raw to transcript, redacted copy for models),
                    safety gate (policy engine) → SAFETY_HOLD short circuit
   │
   ▼
2. Understand       intent (rules first, model second), deterministic pre-extraction
                    (countries, counts, windows, bands, programme names, residence phrases,
                    farewell, booking words), then the extraction model with a JSON schema,
                    then value validation → SlotUpdates{slot_id, value, status, confidence}
   │
   ▼
3. Slot store       attribution rules 1–5 in code, corrections 4.1 (incl. the soft check),
                    forbidden categories dropped, history → State (typed, versioned)
   │
   ▼
4. Flow controller  transition table enforced, priority 5.3, pending slot, cooling,
                    focus lane, previous state for GENERAL_QA → NextAction
   │
   ▼
5. Sources          what the reply may say: (a) verbatim safety script, (b) knowledge
                    playbook entry, (c) retrieved passages with IDs, (d) slot values
                    → GroundingPack
   │
   ▼
6. Composer         reply model, temperature 0.5, JSON schema output:
                    {acknowledge, answer, bridge, ask, tone} → assembled text
                    chips are derived deterministically from NextAction + GroundingPack
   │
   ▼
7. Guard            G1–G13 on the parts, claim check on `answer` sentences against
                    passage IDs, one regeneration with the failed check named,
                    safe reply that acknowledges the latest message
   │
   ▼
8. Egress + log     house style, formatting, link policy; TurnRecord to the audit store:
                    redacted message, state before/after, NextAction, guard results,
                    passage IDs, model, latency, tokens
```

Package layout (new, under `src/hayat_backend/turn/`):

| Module | Owns | Replaces |
|---|---|---|
| `pipeline.py` | the eight steps in order, nothing else | the body of `ChatService.respond` |
| `ingress.py` | language, redaction, safety short circuit | scattered code at the top of `respond` |
| `understand.py` | intent rules, pre-extractors, extraction schema, value validators | `turn_analyzer.py` plus the regexes in `flow.py` |
| `state.py` | the typed state object (Annex A), load/save, validate, version | `slots.SlotState` plus loose facts |
| `attribution.py` | rules 1 to 5, 4.1 corrections and soft check | parts of `flow.slot_updates`, `_settle_changes` |
| `controller.py` | transition table, priority list, handoff rules, cooling | `flow.plan_handoff`, `flow_state_for` |
| `sources.py` | playbook, retrieval with IDs, safety scripts, slot echo | `kb_playbook.py`, `training_scripts.py`, retrieval call |
| `composer.py` | prompt assembly (Annex B order), structured reply schema, chips | `_handoff_prompt`, `_turn_instruction`, `_split_chips`, `_fallback_chips` |
| `guard.py` | G1 to G13 on parts, claim check, regeneration, safe reply | `turn_guard.py` |
| `record.py` | TurnRecord and the audit store write | `turn_log` logger line |

`ChatService` keeps its public signature for the API and Streamlit page and becomes an adapter that calls `pipeline.run`. The legacy paths listed in RC1 are deleted, not flagged off (section 5, phase 1).

Design rules that follow from the Addendum:

1. **Deterministic before probabilistic.** Anything the Addendum states as a rule (attribution, transitions, cooling, never ask again, ask which lane) is code. The models extract and write; they never decide state.
2. **One job per model call.** Extraction returns slots. Composition returns four labelled parts. Chips, links, naming of journeys and privacy notes are code.
3. **Everything the guard checks is a field, not a guess.** Because the composer returns `acknowledge` and `ask` separately, G2 becomes "acknowledge is non empty and refers to the latest message" and G4 becomes "ask has at most one question mark".
4. **One state object.** Annex A shape, validated on load (G11), stored once, logged every turn. Flat legacy facts are derived from it for the coordinator card, not the other way round.
5. **Budget is a requirement.** Each turn has a token budget (extraction ≤ 900 prompt tokens, composition ≤ 1,100) checked in tests, and a wall clock budget (p95 under 4 seconds when the provider is healthy).

---

## 5. Plan

Phases are ordered so the app gets better after each one and nothing is half migrated at a phase end. Estimates are for one engineer who knows the code.

### Phase 0: stabilise what the team is testing (1 to 2 days)

Goal: stop the "weird" replies that come from fallbacks and limits, without architectural change.

1. **Token budget.** Cut `_CORE_RULES` to Annex B length. Move the chips instruction out of the reply call: chips are already derived in code (`_fallback_chips`); make that the only source and drop `_CHIPS_INSTRUCTION`. Retrieve passages only for question intents. Target under 1,100 prompt tokens per reply call. Measure with the `tok.py` harness and assert the budget in a test.
2. **Skip the analyzer when it cannot add anything.** For playbook turns, bare answers to a yes/no question, farewells and safety turns, run the pre-extractors only. This halves calls for a typical programme conversation.
3. **Provider.** Move to a paid Groq tier or add a second key with its own limit; set `LLM_FALLBACK_MODEL` to a Gemini model with a paid quota. This is an account decision (section 7).
4. **Fallback replies.** Every fallback must acknowledge the latest message. Replace the fixed strings in `_SAFE` and the outage branch with a template that uses the slot changes of the turn or quotes the visitor's own words ("You asked about hospitals. I can't look that up this second…"). Remove the legacy ack strings ("Understood — you're interested in…", "Thank you, noted.") from the reachable path.
5. **Redaction for the analyzer.** Give the extraction step the raw text with only contact details and secrets redacted, not clinical words; it needs "knee" to pick the lane and must still not store it. Keep full redaction for the transcript.

Acceptance: a ten turn programme conversation makes at most twelve model calls; no reply in the live runs `h`, `i`, `j`, `k` is a fixed string that ignores the message.

### Phase 1: one pipeline, delete the legacy (3 to 4 days)

1. Create `turn/pipeline.py` with the eight steps as function calls into the existing modules (no behaviour change yet). `ChatService.respond` calls it when `SIGNUP_HANDOFF` is on.
2. Make `SIGNUP_HANDOFF` and `EXTENDED_INTAKE` always on. Delete: phone and OTP capture, consent and submission steps, `_build_consultation_summary`, `programme_service.handle_programme_message` enquiry capture and its contact collection, the clarify ladder, `_service_explain_reply`, `_PROGRAMMES_OVERVIEW_*`, `_COST_FAQ_*`, `_extract_facts` and `_merge_analysis`, `_skip_if_stuck`, the `question_planner` legacy order and `HANDOFF_MEDICAL` tables (keep `_question_for` wording in `sources.py`), `_align_question`, `_clarify`. Keep the document upload replies as a source (step 5), not as a branch.
3. Move the policy engine's deterministic replies (S13, S14, S15, injection, abuse) into step 1 as the only short circuit.
4. Keep the API response shape unchanged; the Streamlit page must not notice.
5. Delete tests that pin deleted behaviour; keep and move the rest.

Acceptance: `respond` under 150 lines; `chat_service.py` under 1,200 lines; no `if clarification_reply is None` left; the API contract tests and the addendum tests pass.

### Phase 2: understanding and state (2 to 3 days)

1. **State object** (`turn/state.py`): a Pydantic model in the Annex A shape with `version`, `flow_state`, `previous_state`, `focus_lane`, `pending_slot`, `pending_change`, `handoff{offered, offered_turn, declined, declined_turn}`, `turn`, `shared`, `lanes`. Stored as one JSON fact; legacy flat keys are **derived** on save for the coordinator card. `load()` validates and raises → G11 → recovery. Add `s.language`.
2. **Extraction schema** (`turn/understand.py`): Groq `json_schema` response format for `qwen` and `gpt-oss` (they support it); fall back to `json_object` plus strict Pydantic validation. Enum of slot IDs, status enum, `correction: bool`, `lane`, `lane_ambiguous`, intent enum.
3. **Validators per slot**: country (ISO list plus common regions), count (integer 1 to 20), window (a small grammar: "within N months", season, month, quarter, "later this year", "flexible"), band (keep the visitor's words but reject exact figures with currency → store as band label "around 8000" only if the visitor wrote it; no currency added), programme (registry ID), experience type and goal (allowed lists from B3). A value that fails validation becomes HEARD with the raw words, never CONFIRMED.
4. **Pre-extractors** (deterministic, run before the model): residence phrases, counts ("just me", "two of us"), named programmes, farewell and stop words, booking words, "I don't know" and refusal phrases bound to the pending slot only. These replace the regexes now in `flow.py` and make the model's output a second opinion that cannot overrule a validated pre-extraction.
5. **Attribution** (`turn/attribution.py`): rules 1 to 5 as a function `attribute(updates, state, text) -> (updates, question_needed)` with unit tests for every row of Part 4 and every example in 9.1 to 9.6.

Acceptance: scenarios 1, 3 to 7, 12 to 14, 20 pass with the real extraction model in the live harness; no regex in `controller.py`.

### Phase 3: composer and guard (3 to 4 days)

1. **Composer** (`turn/composer.py`): prompt in the Annex B order; the model returns `{acknowledge, answer, bridge, ask}` as JSON (schema enforced). `ask` is given the pending slot and must be empty when the controller says no question. Temperature 0.5 for composition. Chips derived from NextAction and the GroundingPack. The style script, if any, is passed as `style_example` and never as text to copy.
2. **Acknowledgement bank and variety** (Part 10): the composer is told the openings used so far in the conversation and the guard rejects a repeated opening anywhere in the conversation, not only the previous turn. Length matching: the composer receives `visitor_message_length: short|medium|long` and a target sentence count.
3. **Guard** (`turn/guard.py`) rewritten against the parts:
   - G1 on `ask` against settled slots; G4 is structural; G2 is "acknowledge non empty and shares content words with the latest message or answers its question"; G5 on the whole; G7 rewrites lists into sentences (join items with "and", keep at most three); G8, G9, G12 on all parts; G10 compares `ask` with the previous `ask`; G11 from state load; G13 echo check on `acknowledge`.
   - **Claim check (G6, 6.3):** split `answer` into sentences; for each sentence that mentions trawellcare, a programme, a price, a hospital, a destination, dates, inclusions or process words, require token overlap ≥ 0.5 with one retrieved passage or a playbook entry, or that every noun phrase appears in the slot store; otherwise drop the sentence; if all answer sentences drop, replace with the 6.2 wording. Record the passage IDs used.
   - Guard also runs on playbook and scripted replies for G5, G8 and formatting (safety scripts stay verbatim; the guard may not change them, only log).
   - Regenerate once with the failed check named; then a safe reply built from the acknowledgement template of Phase 0.
4. **Flow controller** (`turn/controller.py`): the allowed transitions table from Part 5 as data; a disallowed transition raises and is logged; `previous_state` restored after GENERAL_QA; UNSURE triggers "offer two or three options once" through the composer; closing and opt out separated (already done).

Acceptance: scenarios 2, 8, 9, 10, 11, 13, 15, 21, 23 pass live; G2 pass rate ≥ 98 percent over the live harness; zero unmatched factual claims in the test set.

### Phase 4: grounding and knowledge management (2 to 3 days)

1. **Chunking by structure**: split documents by headings and then by sentences into passages of 60 to 180 words with stable IDs `doc-xxxx#s3.5-q11`. Never cut inside a sentence.
2. **Instruction text out of the fact index**: sections that instruct Hayat (Signature Programmes sections 6 and 7, company KB sections 8 to 10) are indexed as `kind: guidance` and are never shown as facts; the playbook reads them instead.
3. **Programme registry into the knowledge store**: programmes become records in the knowledge store with `name`, `former_names`, `tagline`, `status: approved|draft`, editable through `/v1/knowledge/programmes` (service token). `programmes.json` becomes the seed only. A rename is then a data change with no deploy, as the Addendum requires.
4. **Playbook from structure, not from one `.docx`**: the FAQ parser keys on the heading and `Qn.` markers already, but should read from the indexed passages rather than re-opening the file, so an uploaded replacement document takes effect immediately.
5. **Retrieval**: three to four passages; hybrid score (BM25 plus the section's keyword list); boost the passage for the programme in focus.
6. **Document hygiene** (owner task): update the Signature Programmes and company KB documents to the current women's programme name and to the signup based contact rule, then re-upload.

Acceptance: scenario 9, 11, 22 pass live; every reply log lists the passage IDs it relied on; a programme rename through the API shows in the next reply with no restart.

### Phase 5: logging, metrics and the live harness (2 to 3 days)

1. **TurnRecord** (`turn/record.py`) written to the audit store per turn: conversation ID, turn, redacted message, state before and after, NextAction, guard failures with check IDs, regeneration flag, passage IDs, model used, latency, tokens. Admin read endpoint `/v1/admin/conversations/{id}/turns` (service token). Nothing of this goes to Zoho or ad platforms.
2. **Measures (11.1)** computed from TurnRecords by a script `scripts/measures.py`: G2 pass rate, repeated settled slot questions, cross lane leaks, unmatched claims, repeated offers in cooling, guard failures after regeneration, plus latency p50/p95 and tokens per turn.
3. **Live harness** `scripts/live_eval.py`: the 24 scenarios of Part 11 and the six worked conversations of Part 9 as scripted inputs with expected state and reply checks, run against the real models, producing a pass/fail table and the measures. Run nightly and before every deploy. Add the fifty turn conversation and the ten one word answers.
4. **Free typing round**: a short protocol for the team (ten conversations each, what to record), and a place to paste transcripts.

Acceptance: harness green on all 24; measures within the 11.1 targets or an owner decision to adjust them.

### Phase 6: craft and remaining rules (2 days)

1. Rolling slot only summary of earlier turns in the prompt (7.1 block 4).
2. Language: `s.language` set on turn one; approved list from the owner; the reply in English with the offer to continue in English when unsupported (Part 10).
3. UNSURE: options offered once through the composer, then not again.
4. Closing: when handoff conditions are met and the visitor has nothing to add, say so and stop extending intake (Part 10, "when the visitor has said enough").
5. Streamlit: show the reference and the suggestions from the TurnRecord; a debug panel for the team (`?debug=1`) showing state, NextAction and guard results for the last turn, so testers can report precisely.

---

## 6. Order of work and what ships when

| Week | Phases | Visible to the team |
|---|---|---|
| 1 | 0, 1 | Fewer rate limit failures, no canned fallbacks, same features, much smaller code |
| 2 | 2, 3 | Correct attribution without patches, consistent four part replies, claim checked answers, chips always present |
| 3 | 4, 5, 6 | Programme rename without deploy, per turn admin log, nightly live evaluation, measures |

Each phase ends with the full test suite, the live harness, a commit and a push to both remotes.

---

## 7. Decisions needed from the owner

| # | Question | Default if no answer |
|---|---|---|
| 1 | Contact details in chat (Signature Programmes 6.6) or only at signup (B0, Addendum)? | Only at signup. The document should be amended. |
| 2 | Scripts S1 to S17: verbatim, or style examples as the Addendum 7.2 says? Safety scripts S13 to S15 and the trawellcare definition stay verbatim either way. | Style examples. |
| 3 | Model provider: paid Groq tier, second key, or a different primary? The free limit cannot support team testing. | Paid Groq tier plus the Gemini backup on a paid quota. |
| 4 | Approved languages for Hayat (Part 10, open item). | English and Arabic. |
| 5 | Support contact channel for S10. | None shown until given. |
| 6 | Cooling period six messages and the fifth message trigger (Part 12). | Keep six and five. |
| 7 | Should Hayat mention "Dawood" (Train Hayat section 8) when explaining matching? It is not in the knowledge base. | No, until it is added to the KB. |
| 8 | Slot store retention: same as transcript (24 hour guest session) or shorter. | Same as transcript. |
| 9 | Update the Signature Programmes and company KB documents to the new programme name and the signup rule, so runtime renaming is no longer needed. | Yes, owner provides the revised files. |

---

## 8. Definition of done

Hayat is done when all of the following hold on the live harness and in a free typing round by people who did not build it:

- All 24 scenarios in Part 11 pass, including the fifty turn conversation and the ten one word answers.
- 11.1 measures: G2 pass ≥ 98 percent (100 percent for direct questions); repeated settled slot questions < 1 percent; cross lane leaks 0; unmatched factual claims 0; repeated offers in cooling 0; guard failures after regeneration < 1 percent.
- Every programme question in the Signature Programmes document is answered with the document's text and followed by the document's question unless that detail is already known.
- Every reply has suggested next steps that follow from it.
- No reply is a fixed fallback string that ignores the message; p95 latency under 4 seconds with a healthy provider; no provider error ever shows in chat.
- Each turn is logged with state, guard results and passage IDs in the admin module, and nowhere else.
- A programme rename is a knowledge base change with no deploy.
- `chat_service.py` is an adapter; the turn pipeline has one module per step; the test suite covers each step alone and the pipeline end to end.

---

## Annex. Files touched today and where each rule lives now

For the engineer starting Phase 1, the current locations of the Addendum's pieces:

| Addendum piece | Current file |
|---|---|
| Slot dictionary, statuses, history | `src/hayat_backend/slots.py` |
| Lane and focus, attribution patches, planner priority, flow state, recovery, soft change check, closing | `src/hayat_backend/flow.py` |
| Extraction prompt and parsing | `src/hayat_backend/turn_analyzer.py` |
| Guard G1 to G13 | `src/hayat_backend/turn_guard.py` |
| Prompt assembly, turn instructions, chips, outage fallbacks, orchestration | `src/hayat_backend/chat_service.py` (`_handoff_prompt`, `_turn_instruction`, `_guarded`, `respond`) |
| Scripts S1 to S17, house style, lowercase brand | `src/hayat_backend/training_scripts.py` |
| Programme names and renames | `src/hayat_backend/programmes_registry.py`, `knowledge_seed/programmes.json` |
| Knowledge playbook (FAQ and section 6) | `src/hayat_backend/kb_playbook.py` |
| Retrieval | `src/hayat_backend/rag.py`, knowledge store in `main.py` |
| Safety and policy | `src/hayat_backend/policy_engine.py`, `guardrails.py` |
| Rate limit handling | `src/hayat_backend/ratelimit.py`, `llm.py` |
| Addendum tests | `tests/test_flow_addendum.py`, `tests/test_signup_handoff.py`, `tests/test_smart_turns.py` |
| Live scenario runner (scratch, to become `scripts/live_eval.py`) | `ho.py` in the session scratchpad; modes `a` to `k` |
