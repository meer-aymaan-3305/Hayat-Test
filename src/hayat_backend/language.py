"""Small language helpers for English and Arabic responses."""

from __future__ import annotations


def detect_language(text: str) -> str:
    arabic = sum("\u0600" <= char <= "\u06ff" for char in text)
    letters = sum(char.isalpha() for char in text)
    return "ar" if letters and arabic / letters >= 0.2 else "en"


# Addendum part 10: Hayat replies in an approved language; anything else gets English and an
# offer. The approved list is an open item for Product and Compliance; English and Arabic until then.
APPROVED_LANGUAGES = ("en", "ar")
_OTHER_SCRIPTS = (
    ("\u0400", "\u04ff"),  # Cyrillic
    ("\u0900", "\u097f"),  # Devanagari
    ("\u0980", "\u09ff"),  # Bengali
    ("\u0a80", "\u0aff"),  # Gujarati
    ("\u0b80", "\u0bff"),  # Tamil
    ("\u0c00", "\u0c7f"),  # Telugu
    ("\u0d00", "\u0d7f"),  # Malayalam
    ("\u4e00", "\u9fff"),  # Chinese
    ("\u3040", "\u30ff"),  # Japanese kana
    ("\uac00", "\ud7af"),  # Korean
    ("\u0e00", "\u0e7f"),  # Thai
)
_LATIN_OTHER = (
    r"\b(bonjour|merci|hola|gracias|por favor|guten tag|danke|bitte|ciao|grazie|obrigad[oa]|ol[a\u00e1]|"
    r"merhaba|te\u015fekk\u00fcr|namaste|dhanyavaad)\b"
)


def unsupported_language(text: str) -> bool:
    """True when the message is clearly written in a language Hayat is not approved to use."""
    import re

    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    other = sum(1 for c in letters if any(lo <= c <= hi for lo, hi in _OTHER_SCRIPTS))
    if other / len(letters) >= 0.3:
        return True
    return bool(re.search(_LATIN_OTHER, text, re.IGNORECASE)) and len(text.split()) <= 12


LANGUAGE_NOTE = (
    "LANGUAGE: the visitor wrote in a language you are not approved to use. Reply in English, warmly, and "
    "say in one short sentence that you can carry on in English, or the team can help in their language "
    "on the free consultation."
)

