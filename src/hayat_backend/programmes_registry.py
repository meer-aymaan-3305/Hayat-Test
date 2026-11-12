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


@lru_cache
def programmes() -> tuple[Programme, ...]:
    path = Path(os.environ.get("PROGRAMMES_FILE") or _default_path())
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    return tuple(
        Programme(
            id=str(p["id"]), name=str(p["name"]), tagline=str(p.get("tagline", "")),
            former_names=tuple(str(n) for n in p.get("former_names", [])),
        )
        for p in data.get("programmes", [])
        if p.get("id") and p.get("name")
    )


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
