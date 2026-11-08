"""Speech-to-text and text-to-speech adapters.

STT uses Groq Whisper (whisper-large-v3) which supports English and Arabic.
TTS uses Groq PlayAI TTS. Both reuse GROQ_API_KEY and fail closed (503) when
unconfigured or on provider errors. Only validated assistant replies are
synthesized — never raw model output or internal instructions.
"""

from __future__ import annotations

from typing import Protocol

import httpx

from .config import Settings

GROQ_BASE = "https://api.groq.com/openai/v1"


class SpeechError(RuntimeError):
    """Raised when a speech provider call fails or is unconfigured."""


class SpeechToText(Protocol):
    async def transcribe(self, audio: bytes, filename: str, content_type: str) -> tuple[str, str | None]:
        """Return (transcript, detected_language)."""


class TextToSpeech(Protocol):
    async def synthesize(self, text: str, language: str) -> tuple[bytes, str]:
        """Return (audio_bytes, media_type)."""


class UnavailableSTT:
    async def transcribe(self, audio: bytes, filename: str, content_type: str) -> tuple[str, str | None]:
        raise SpeechError("Speech-to-text is not configured.")


class UnavailableTTS:
    async def synthesize(self, text: str, language: str) -> tuple[bytes, str]:
        raise SpeechError("Text-to-speech is not configured.")


class GroqWhisperSTT:
    def __init__(self, settings: Settings) -> None:
        self._key = settings.groq_api_key.get_secret_value() if settings.groq_api_key else None
        self._model = settings.groq_stt_model
        self._language = settings.groq_stt_language

    async def transcribe(self, audio: bytes, filename: str, content_type: str) -> tuple[str, str | None]:
        if not self._key:
            raise SpeechError("Speech-to-text is not configured.")
        data = {"model": self._model, "response_format": "verbose_json"}
        if self._language:
            data["language"] = self._language
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(
                    f"{GROQ_BASE}/audio/transcriptions",
                    headers={"Authorization": f"Bearer {self._key}"},
                    data=data,
                    files={"file": (filename, audio, content_type)},
                )
        except httpx.HTTPError as exc:
            raise SpeechError("Speech recognition request failed.") from exc
        if res.status_code >= 400:
            raise SpeechError(f"Speech recognition failed ({res.status_code}).")
        body = res.json()
        text = (body.get("text") or "").strip()
        if not text:
            raise SpeechError("Speech recognition returned empty transcript.")
        return text, body.get("language")


class GroqPlayAITTS:
    """Orpheus TTS (PlayAI was decommissioned by Groq on 2025-12-31)."""

    def __init__(self, settings: Settings) -> None:
        self._key = settings.groq_api_key.get_secret_value() if settings.groq_api_key else None
        self._model_en = settings.groq_tts_model_en
        self._model_ar = settings.groq_tts_model_ar
        self._voice_en = settings.groq_tts_voice_en
        self._voice_ar = settings.groq_tts_voice_ar

    async def synthesize(self, text: str, language: str) -> tuple[bytes, str]:
        if not self._key:
            raise SpeechError("Text-to-speech is not configured.")
        arabic = language == "ar"
        model = self._model_ar if arabic else self._model_en
        voice = self._voice_ar if arabic else self._voice_en
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(
                    f"{GROQ_BASE}/audio/speech",
                    headers={"Authorization": f"Bearer {self._key}"},
                    json={
                        "model": model,
                        "voice": voice,
                        "input": text,
                        "response_format": "wav",
                    },
                )
        except httpx.HTTPError as exc:
            raise SpeechError("Speech synthesis request failed.") from exc
        if res.status_code >= 400 or not res.content:
            raise SpeechError(f"Speech synthesis failed ({res.status_code}).")
        return res.content, "audio/wav"


def create_stt(settings: Settings) -> SpeechToText:
    return GroqWhisperSTT(settings) if settings.groq_api_key else UnavailableSTT()


def create_tts(settings: Settings) -> TextToSpeech:
    return GroqPlayAITTS(settings) if settings.groq_api_key else UnavailableTTS()
