"""Signature programme names, from data and not from code.

The addendum is explicit: programme names come only from the knowledge base, so a rename is a
data change. The registry file sits with the knowledge documents (PROGRAMMES_FILE overrides
the location). Hayat's replies, the page and the prompts all read the names from here.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Programme:
    id: str
    name: str
    tagline: str
    former_names: tuple[str, ...]


def _default_path() -> Path:
    return Path(__file__).resolve().parents[2] / "knowledge_seed" / "programmes.json"


_ROOT: list[str] = []  # set by the app to the knowledge store's folder


def set_knowledge_root(root: str) -> None:
    _ROOT[:] = [root]
    reload()


def knowledge_root() -> Path:
    if _ROOT:
        return Path(_ROOT[0])
    return Path(os.environ.get("KNOWLEDGE_DIR") or "data/knowledge")


def _data_path() -> Path:
    """Where the team's edits live (the knowledge data folder), so a rename needs no deploy."""
    return knowledge_root() / "programmes.json"


def registry_path() -> Path:
    if os.environ.get("PROGRAMMES_FILE"):
        return Path(os.environ["PROGRAMMES_FILE"])
    return _data_path() if _data_path().exists() else _default_path()


def _read() -> list[dict]:
    try:
        data = json.loads(registry_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [p for p in data.get("programmes", []) if isinstance(p, dict)]


@lru_cache
def programmes() -> tuple[Programme, ...]:
    """Approved programmes only (Enhanced Training B3: a programme enters after approval)."""
    return tuple(
        Programme(
            id=str(p["id"]), name=str(p["name"]), tagline=str(p.get("tagline", "")),
            former_names=tuple(str(n) for n in p.get("former_names", [])),
        )
        for p in _read()
        if p.get("id") and p.get("name") and p.get("status", "approved") == "approved"
    )


def all_records() -> list[dict]:
    """Every record, drafts included, for the team's knowledge base manager."""
    return _read()


def save_records(records: list[dict]) -> None:
    """Replace the registry with the team's edited records and use them from the next reply."""
    seen: set[str] = set()
    clean: list[dict] = []
    for record in records:
        pid, name = str(record.get("id", "")).strip(), str(record.get("name", "")).strip()
        if not pid or not name:
            raise ValueError("Every programme needs an id and a name.")
        if pid in seen:
            raise ValueError(f"Programme id {pid} is used twice.")
        seen.add(pid)
        status = str(record.get("status", "approved"))
        if status not in {"approved", "draft"}:
            raise ValueError("Status must be approved or draft.")
        clean.append({
            "id": pid, "name": name, "tagline": str(record.get("tagline", "")).strip(),
            "former_names": [str(n).strip() for n in record.get("former_names", []) if str(n).strip()],
            "status": status,
        })
    path = Path(os.environ["PROGRAMMES_FILE"]) if os.environ.get("PROGRAMMES_FILE") else _data_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"programmes": clean}, indent=2, ensure_ascii=False), encoding="utf-8")
    reload()


def reload() -> None:
    """Drop every cached copy of the names, so the next reply uses the current ones."""
    from . import kb_playbook

    programmes.cache_clear()
    _rename_rules.cache_clear()
    kb_playbook.faqs.cache_clear()


@lru_cache
def _rename_rules() -> tuple[tuple[re.Pattern[str], str], ...]:
    rules = []
    for programme in programmes():
        for old in programme.former_names:
            rules.append((re.compile(rf"\b{re.escape(old)}\b", re.IGNORECASE), programme.name))
    return tuple(rules)


def apply_renames(text: str) -> str:
    """Replace any former programme name with its current name."""
    for pattern, new in _rename_rules():
        text = pattern.sub(new, text)
    return text


def alias_pattern() -> str:
    """Regex alternation of every programme name and former name, accent tolerant."""
    names = []
    for programme in programmes():
        names += [programme.name, *programme.former_names]
    return "|".join(re.escape(n).replace("é", "[eé]") for n in names) or r"(?!x)x"


def knowledge_block() -> str:
    """The programme list as the model should know it, former names included."""
    lines = []
    for programme in programmes():
        former = f" (formerly {', '.join(programme.former_names)})" if programme.former_names else ""
        lines.append(f"{programme.name}{former}: {programme.tagline}")
    return "; ".join(lines)


def reset() -> None:  # for tests
    programmes.cache_clear()
    _rename_rules.cache_clear()
