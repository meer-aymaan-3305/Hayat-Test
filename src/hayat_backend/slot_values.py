"""Allowed values per slot (Addendum 2.1 and 2.3), checked in code.

The extraction model proposes a value; this module decides what is stored. A value that fits the
slot's allowed form is normalised and kept as the model said (CONFIRMED or HEARD). A value that
does not fit (a vague phrase, a figure in a count slot) is kept in the visitor's own short words
as HEARD, so Hayat echoes it lightly instead of treating it as settled. A value that must never be
stored (a programme the knowledge base does not have) is dropped.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from .programmes_registry import programmes

CONFIRMED, HEARD = "CONFIRMED", "HEARD"

_COUNTRIES = {
    "afghanistan", "albania", "algeria", "argentina", "armenia", "australia", "austria", "azerbaijan",
    "bahrain", "bangladesh", "belarus", "belgium", "bhutan", "bolivia", "bosnia", "brazil", "brunei",
    "bulgaria", "cambodia", "canada", "chile", "china", "colombia", "costa rica", "croatia", "cuba",
    "cyprus", "czech republic", "czechia", "denmark", "dominican republic", "ecuador", "egypt", "estonia",
    "ethiopia", "finland", "france", "georgia", "germany", "ghana", "greece", "hungary", "iceland", "india",
    "indonesia", "iran", "iraq", "ireland", "israel", "italy", "jamaica", "japan", "jordan", "kazakhstan",
    "kenya", "kuwait", "kyrgyzstan", "laos", "latvia", "lebanon", "libya", "lithuania", "luxembourg",
    "malaysia", "maldives", "malta", "mauritius", "mexico", "moldova", "monaco", "mongolia", "montenegro",
    "morocco", "myanmar", "nepal", "netherlands", "new zealand", "nigeria", "north macedonia", "norway",
    "oman", "pakistan", "palestine", "panama", "peru", "philippines", "poland", "portugal", "qatar",
    "romania", "russia", "rwanda", "saudi arabia", "serbia", "seychelles", "singapore", "slovakia",
    "slovenia", "south africa", "south korea", "korea", "spain", "sri lanka", "sudan", "sweden",
    "switzerland", "syria", "taiwan", "tajikistan", "tanzania", "thailand", "tunisia", "turkey", "turkiye",
    "uganda", "ukraine", "united arab emirates", "united kingdom", "united states", "uruguay",
    "uzbekistan", "venezuela", "vietnam", "yemen", "zambia", "zimbabwe", "bali", "dubai", "abu dhabi",
}
_COUNTRY_ALIASES = {
    "uae": "United Arab Emirates", "u.a.e": "United Arab Emirates", "emirates": "United Arab Emirates",
    "uk": "United Kingdom", "u.k.": "United Kingdom", "britain": "United Kingdom", "england": "United Kingdom",
    "usa": "United States", "us": "United States", "u.s.": "United States", "america": "United States",
    "ksa": "Saudi Arabia", "saudi": "Saudi Arabia", "türkiye": "Turkey", "turkiye": "Turkey",
    "holland": "Netherlands", "the netherlands": "Netherlands",
}
_REGIONS = {
    "europe", "asia", "middle east", "the middle east", "gulf", "the gulf", "gcc", "americas", "the americas",
    "north america", "south america", "latin america", "south east asia", "southeast asia", "east asia",
    "africa", "north africa", "east africa", "scandinavia", "the mediterranean", "mediterranean",
    "caribbean", "the caribbean", "eastern europe", "western europe", "central asia", "south asia",
}
_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "a couple": 2, "couple": 2, "pair": 2,
}
_SOLO = re.compile(r"^(?:just |only )?(?:me|myself|alone|solo|on my own|by myself|i'?ll go alone|1|one)(?: person)?$", re.I)
_WITH_ONE = re.compile(
    r"^(?:me|myself) (?:and|with|\+) (?:my |a )?(?:wife|husband|partner|spouse|sister|brother|mum|mom|mother|"
    r"dad|father|friend|son|daughter|colleague|fiance|fiancée|fiance?e|companion)$", re.I,
)
_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|november|december|"
    "jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)
_WINDOW = re.compile(
    rf"\b({_MONTHS}|spring|summer|autumn|fall|winter|ramadan|eid|christmas|new year|"
    r"next (?:week|month|year|few (?:weeks|months))|this (?:month|year|summer|winter|spring|autumn)|"
    r"later this year|early next year|end of (?:the )?year|(?:within|in|over) (?:the next )?\w+ (?:days|weeks|months)|"
    r"\d+ (?:days|weeks|months)|q[1-4]|20\d\d|asap|as soon as possible|soon|flexible|any ?time|"
    r"in a few (?:weeks|months)|couple of (?:weeks|months))\b",
    re.I,
)
_DURATION = re.compile(
    r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|a|a couple of|a few)\s*"
    r"(nights?|days?|weeks?)\b|\b(long weekend|weekend|a week|fortnight|flexible)\b",
    re.I,
)
_BAND = re.compile(
    r"\d|\b(low|lower|mid|middle|medium|high|higher|premium|luxury|economy|budget|moderate|affordable|"
    r"flexible|under|below|up to|around|about|between|less than|more than|no limit|not sure)\b",
    re.I,
)
_SPECIALTY_LABELS = {
    "orthopaedics": ("orthop", "knee", "hip", "joint", "spine", "spinal", "shoulder", "bone"),
    "cardiology": ("cardi", "heart", "valve", "bypass"),
    "dental": ("dental", "dentist", "teeth", "tooth", "implant", "veneer"),
    "fertility": ("fertil", "ivf", "egg freezing"),
    "ophthalmology": ("ophthal", "eye", "cataract", "lasik", "retina"),
    "oncology": ("oncolog", "cancer", "tumour", "tumor"),
    "bariatric surgery": ("bariatric", "weight loss", "gastric"),
    "aesthetics": ("aesthetic", "cosmetic", "plastic", "rhinoplasty", "liposuction", "hair transplant"),
    "neurology": ("neuro", "brain"),
    "nephrology and transplant": ("kidney", "renal", "transplant", "dialysis"),
    "urology": ("urolog", "prostate"),
    "gastroenterology": ("gastro", "liver", "colon"),
    "general surgery": ("general surgery", "hernia", "gallbladder"),
    "check up": ("check up", "checkup", "check-up", "health screening", "screening"),
    "longevity and preventive care": ("preventive", "longevity clinic"),
}
_GOALS = {
    "relaxation": ("relax", "rest", "calm", "unwind", "destress", "de-stress", "stress", "peace", "recharge", "reset"),
    "fitness": ("fitness", "fit", "energy", "strength", "active", "weight", "movement"),
    "longevity": ("longevity", "healthy ageing", "healthy aging", "ageing", "aging", "live longer"),
    "executive performance": ("executive", "performance", "leadership", "productivity", "founder"),
    "social": ("social", "connection", "friends", "meet people", "community"),
    "travel experience": ("travel", "explore", "adventure", "culture", "fresh start", "experience"),
}
_EXPERIENCES = {
    "retreat": ("retreat",), "fitness": ("fitness", "bootcamp"), "longevity": ("longevity",),
    "rest": ("rest", "relax", "spa", "unwind"), "detox": ("detox", "cleanse"), "yoga": ("yoga", "meditation"),
}


class Checked(NamedTuple):
    value: str | None  # None: store nothing
    status: str


def _title(text: str) -> str:
    return " ".join(w if w.isupper() and len(w) <= 4 else w.capitalize() for w in text.split())


def _places(raw: str) -> list[str] | None:
    """Every part of a place answer, normalised, or None if any part is not a known place."""
    parts = [p.strip(" .!") for p in re.split(r",|/|\bor\b|\band\b|&", raw, flags=re.I) if p.strip(" .!")]
    out: list[str] = []
    for part in parts:
        low = re.sub(r"^(?:in|to|maybe|probably|perhaps|somewhere in|ideally)\s+", "", part.lower()).strip()
        if low in _COUNTRY_ALIASES:
            out.append(_COUNTRY_ALIASES[low])
        elif low in _COUNTRIES:
            out.append(_title(low))
        elif low in _REGIONS:
            out.append(_title(low.removeprefix("the ")))
        else:
            return None
    return out or None


def _count(raw: str) -> int | None:
    low = raw.strip().lower().rstrip(".!")
    if _SOLO.match(low):
        return 1
    if _WITH_ONE.match(low):
        return 2
    match = re.search(r"\b(\d{1,2})\b", low)
    if match:
        return int(match.group(1))
    for word, number in _WORDS.items():
        if re.search(rf"\b{word}\b", low):
            return number
    return None


def _label(raw: str, table: dict[str, tuple[str, ...]]) -> str | None:
    low = raw.lower()
    for label, cues in table.items():
        if low == label or any(cue in low for cue in cues):
            return label
    return None


def check(slot_id: str, raw: str, status: str) -> Checked:
    """The value to store for this slot, and its status after the allowed-value check."""
    raw = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not raw:
        return Checked(None, status)
    heard = Checked(raw[:60], HEARD)

    if slot_id in {"s.residence_country", "m.destination_country", "w.destination"}:
        places = _places(raw)
        if places is None:
            return heard  # "somewhere warm": echo it lightly, never treat it as settled
        if slot_id == "s.residence_country" and len(places) > 1:
            return heard
        return Checked(" and ".join(places), status)

    if slot_id in {"m.travellers_count", "w.participants_count"}:
        number = _count(raw)
        if number is None or not 1 <= number <= 30:
            return heard
        return Checked(str(number), status)

    if slot_id in {"m.timeline_window", "w.dates_window"}:
        if not _WINDOW.search(raw):
            return heard
        return Checked(raw[:60], status)

    if slot_id == "w.duration_nights":
        if re.fullmatch(r"\d{1,2}", raw):
            return Checked(f"{raw} nights", status)
        return Checked(raw[:40], status) if _DURATION.search(raw) else heard

    if slot_id in {"m.budget_band", "w.budget_band"}:
        return Checked(raw[:60], status) if _BAND.search(raw) else heard

    if slot_id == "w.programme_interest":
        low = raw.lower().replace("é", "e")
        for programme in programmes():
            names = [programme.name, *programme.former_names] + (["hayat 100"] if programme.id == "hayat-100" else [])
            if any(n.lower().replace("é", "e") in low for n in names):
                return Checked(programme.name, status)
        return Checked(None, status)  # not in the knowledge base: never stored (Addendum 6.2)

    if slot_id == "m.service_category":
        label = _label(raw, _SPECIALTY_LABELS)
        return Checked(label, status) if label else Checked(raw[:40], HEARD)

    if slot_id == "w.goal_category":
        label = _label(raw, _GOALS)
        return Checked(label, status) if label else heard

    if slot_id == "w.experience_type":
        label = _label(raw, _EXPERIENCES)
        return Checked(label, status) if label else Checked(raw[:40], status)

    if slot_id == "s.preferred_name":
        first = re.sub(r"[^A-Za-zÀ-ɏ؀-ۿ'-]", "", raw.split()[0]) if raw.split() else ""
        return Checked(first.capitalize() if first.isascii() else first, status) if first else Checked(None, status)

    return Checked(raw[:80], status)
