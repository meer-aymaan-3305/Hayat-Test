"""Small language helpers for English and Arabic responses."""

from __future__ import annotations


def detect_language(text: str) -> str:
    arabic = sum("\u0600" <= char <= "\u06ff" for char in text)
    letters = sum(char.isalpha() for char in text)
    return "ar" if letters and arabic / letters >= 0.2 else "en"

