"""Safety eval: sends every prompt through Hayat the way the website would if the AI were on.

    uv run python scripts/safety_eval/run.py --model offline          # no network, checks the harness
    uv run python scripts/safety_eval/run.py --model groq --out report.md

It uses an in-memory store only. Prompts are made up, never real visitor text.
A prompt passes when the reply the visitor would see meets every check for it.
Replies that came from a script, not the AI, count as passed but say nothing
about the AI, so the report counts them separately.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from cases import CASES, Case
from checks import CHECKS, is_script

from hayat_backend.chat_service import ChatService
from hayat_backend.config import get_settings
from hayat_backend.llm import GroqChatModel, OfflineChatModel
from hayat_backend.memory_store import MemoryStore

# The model's own words are held to the content rules too, to show what Hayat's
# output checks are saving. Emergency, helpfulness and storage checks only apply
# to the final reply.
CONTENT_CHECKS = {
    "no_provider_names", "no_ranking", "no_diagnosis", "no_invented_facts",
    "no_contact_request", "no_prompt_leak", "no_offtopic_answer",
}


class Recorder:
    """Wraps the model to remember what it said, or why it failed, for the current case."""

    def __init__(self, inner):
        self.inner = inner
        self.reset()

    def reset(self):
        self.raw: str | None = None
        self.error: str | None = None

    async def complete(self, messages):
        try:
            self.raw = await self.inner.complete(messages)
            return self.raw
        except Exception as exc:
            self.error = type(exc).__name__
            raise


@dataclass
class Result:
    case: Case
    reply: str
    status: str  # "ai", "scripted" or "model_error"
    failures: list[str] = field(default_factory=list)
    raw: str | None = None
    raw_failures: list[str] = field(default_factory=list)


async def run_case(service: ChatService, recorder: Recorder, case: Case) -> Result:
    session, _ = service.store.create_guest_session(case.lang)
    conversation = service.store.create_conversation(session.id)
    recorder.reset()
    try:
        outcome = await service.respond(
            conversation, case.prompt, None, visitor="guest", contactable=False, reply_language=case.lang, use_ai=True
        )
        reply = outcome["assistant_message"].content
        failures = []
        stored = next((m.content for m in reversed(conversation.messages) if m.role == "user"), "")
    except Exception as exc:  # a crash is a failure to report, not a reason to stop the run
        reply, stored, failures = "", "", [f"crashed: {type(exc).__name__}: {exc}"]

    status = "ai" if recorder.raw is not None else "model_error" if recorder.error else "scripted"
    failures += [f"{name}: {reason}" for name in case.checks if (reason := CHECKS[name](case, reply, stored))]
    raw_failures = []
    if recorder.raw and not is_script(recorder.raw):
        raw_failures = [f"{name}: {reason}" for name in case.checks if name in CONTENT_CHECKS and (reason := CHECKS[name](case, recorder.raw))]
    return Result(case, reply, status, failures, recorder.raw, raw_failures)


async def run_all(cases: list[Case], model, delay: float, retries: int) -> list[Result]:
    recorder = Recorder(model)
    service = ChatService(MemoryStore(), recorder)
    results = []
    for index, case in enumerate(cases, 1):
        result = await run_case(service, recorder, case)
        for attempt in range(1, retries + 1):
            if result.status != "model_error":
                break
            await asyncio.sleep(20 * attempt)  # most often a rate limit: wait, then ask again
            result = await run_case(service, recorder, case)
        results.append(result)
        print(f"[{index}/{len(cases)}] {case.id}: {'PASS' if not result.failures else 'FAIL'} ({result.status})", flush=True)
        if result.status != "scripted":
            await asyncio.sleep(delay)
    return results


def percent(part: int, whole: int) -> str:
    return f"{100 * part / whole:.0f}%" if whole else "-"


def report(results: list[Result], model_name: str) -> str:
    by_category: dict[str, list[Result]] = defaultdict(list)
    for result in results:
        by_category[result.case.category].append(result)
    failed = [r for r in results if r.failures]
    errors = [r for r in results if r.status == "model_error"]
    lines = [
        "# Hayat safety eval",
        "",
        f"- Run: {datetime.now(UTC):%Y-%m-%d %H:%M} UTC",
        f"- Model: {model_name}",
        f"- Prompts: {len(results)} ({sum(r.case.lang == 'en' for r in results)} English, {sum(r.case.lang == 'ar' for r in results)} Arabic)",
        f"- **Passed: {len(results) - len(failed)} of {len(results)} ({percent(len(results) - len(failed), len(results))})**",
        f"- Answered by the AI: {sum(r.status == 'ai' for r in results)}. Answered by a script without the AI: {sum(r.status == 'scripted' for r in results)}. "
        f"AI failed, so Hayat fell back to a script: {len(errors)}",
        "",
        "A pass means the reply the visitor would see met every check. A script reply passes the content checks, so read the AI column too.",
        "",
        "| Category | Prompts | AI answered | Passed | Failed | Pass rate | AI broke a rule before Hayat's checks |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for category, items in sorted(by_category.items()):
        bad = sum(bool(r.failures) for r in items)
        lines.append(
            f"| {category} | {len(items)} | {sum(r.status == 'ai' for r in items)} | {len(items) - bad} | {bad} | "
            f"{percent(len(items) - bad, len(items))} | {sum(bool(r.raw_failures) for r in items)} |"
        )
    if errors:
        lines += ["", f"**{len(errors)} prompts could not be tested on the AI** (it failed, often a rate limit): " + ", ".join(r.case.id for r in errors)]
    lines += ["", "## Failures", ""]
    if not failed:
        lines.append("None.")
    for r in failed:
        lines += [f"### {r.case.id} ({r.status})", f"- Prompt: {r.case.prompt}", f"- Reply: {r.reply!r}", *[f"- {f}" for f in r.failures], ""]
    leaks = [r for r in results if r.raw_failures and not r.failures]
    lines += ["## Caught by Hayat's own checks", "", "The AI broke a rule, and Hayat's output check stopped it from reaching the visitor.", ""]
    if not leaks:
        lines.append("None.")
    for r in leaks:
        lines += [f"- {r.case.id}: {r.raw_failures[0]}"]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", choices=("groq", "offline"), default="offline")
    parser.add_argument("--category", action="append", help="only this category (repeatable)")
    parser.add_argument("--lang", choices=("en", "ar"))
    parser.add_argument("--limit", type=int, help="only the first N prompts")
    parser.add_argument("--delay", type=float, default=2.0, help="seconds to wait after each AI call (rate limits)")
    parser.add_argument("--retries", type=int, default=2, help="times to retry a prompt when the AI fails")
    parser.add_argument("--out", type=Path, help="write the report here (Markdown)")
    parser.add_argument("--strict", action="store_true", help="exit 1 if any prompt fails")
    args = parser.parse_args()

    cases = [c for c in CASES if (not args.category or c.category in args.category) and (not args.lang or c.lang == args.lang)]
    if args.limit:
        cases = cases[: args.limit]
    if args.model == "groq":
        settings = get_settings()
        model, name = GroqChatModel(settings), f"Groq {settings.groq_model}"
    else:
        model, name = OfflineChatModel(), "offline test model (no AI)"

    results = asyncio.run(run_all(cases, model, args.delay if args.model == "groq" else 0, args.retries if args.model == "groq" else 0))
    text = report(results, name)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"\nReport written to {args.out}")
    print("\n" + text)
    return 1 if args.strict and any(r.failures for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
