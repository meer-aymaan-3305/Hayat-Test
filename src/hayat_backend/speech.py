"""Speech-to-text and text-to-speech adapters.

STT uses Groq Whisper (whisper-large-v3) which supports English and Arabic.
TTS uses Groq PlayAI TTS. Both reuse GROQ_API_KEY and fail closed (503) when
unconfigured or on provider errors. Only validated assistant replies are
synthesized — never raw model output or internal instructions.
"""

from __future__ import annotations

import asyncio
import io
import re
import wave
from typing import Protocol

import httpx

from .config import Settings

GROQ_BASE = "https://api.groq.com/openai/v1"

# Groq documents a 200-character input limit per Orpheus request (English and
# Arabic). Longer replies are spoken as several requests joined into one WAV.
TTS_MAX_INPUT_CHARS = 200
TTS_MAX_CHUNKS = 15
_SENTENCE_END = re.compile(r"(?<=[.!?\u061f\u2026\u3002])\s+")


class SpeechError(RuntimeError):
    """Raised when a speech provider call fails or is unconfigured."""


class EmptyTranscriptError(SpeechError):
    """The recording was understood as silence: there is no text in it."""


class SpeechInputTooLongError(SpeechError):
    """The text is too long to be spoken, even when split into chunks."""


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
        try:
            body = res.json()
        except ValueError as exc:
            raise SpeechError("Speech recognition returned an invalid response.") from exc
        if not isinstance(body, dict):
            raise SpeechError("Speech recognition returned an invalid response.")
        text = body.get("text") or ""
        if not isinstance(text, str):
            raise SpeechError("Speech recognition returned an invalid response.")
        text = text.strip()
        if not text:
            raise EmptyTranscriptError("Speech recognition returned empty transcript.")
        return text, body.get("language")


class GroqPlayAITTS:
    """Orpheus TTS (PlayAI was decommissioned by Groq on 2025-12-31)."""

    def __init__(self, settings: Settings) -> None:
        self._key = settings.groq_api_key.get_secret_value() if settings.groq_api_key else None
        self._model_en = settings.groq_tts_model_en
        self._model_ar = settings.groq_tts_model_ar
        self._voice_en = settings.groq_tts_voice_en
        self._voice_ar = settings.groq_tts_voice_ar
        # Vocal direction for the English model only (the Arabic model ignores tags).
        self._style_en = (settings.groq_tts_style_en or "").strip()

    async def synthesize(self, text: str, language: str) -> tuple[bytes, str]:
        if not self._key:
            raise SpeechError("Text-to-speech is not configured.")
        arabic = language == "ar"
        model = self._model_ar if arabic else self._model_en
        voice = self._voice_ar if arabic else self._voice_en
        tag = f"[{self._style_en}] " if self._style_en and not arabic else ""
        pieces = split_for_tts(text, limit=TTS_MAX_INPUT_CHARS - len(tag))
        if not pieces:
            raise SpeechError("There is no text to synthesize.")
        if len(pieces) > TTS_MAX_CHUNKS:
            raise SpeechInputTooLongError("This reply is too long to be read aloud.")

        async def speak(client: httpx.AsyncClient, piece: str) -> bytes:
            res = await client.post(
                f"{GROQ_BASE}/audio/speech",
                headers={"Authorization": f"Bearer {self._key}"},
                json={
                    "model": model,
                    "voice": voice,
                    "input": f"{tag}{piece}",
                    "response_format": "wav",
                },
            )
            if res.status_code >= 400 or not res.content:
                raise SpeechError(f"Speech synthesis failed ({res.status_code}).")
            return res.content

        try:
            # Pieces are independent, so they are spoken in parallel (order is kept).
            async with httpx.AsyncClient(timeout=30.0) as client:
                wavs = list(await asyncio.gather(*(speak(client, piece) for piece in pieces)))
        except httpx.HTTPError as exc:
            raise SpeechError("Speech synthesis request failed.") from exc
        return join_wav(wavs), "audio/wav"


def split_for_tts(text: str, limit: int = TTS_MAX_INPUT_CHARS) -> list[str]:
    """Split text into sentence-based pieces of at most `limit` characters."""
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(" ".join(text.split())):
        while len(sentence) > limit:
            cut = sentence.rfind(" ", 0, limit + 1)
            cut = cut if cut > 0 else limit
            head, sentence = sentence[:cut].strip(), sentence[cut:].strip()
            if current:
                pieces.append(current)
                current = ""
            pieces.append(head)
        if not sentence:
            continue
        if current and len(current) + 1 + len(sentence) > limit:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return [piece for piece in pieces if piece]


def _pcm_and_format(part: bytes) -> tuple[bytes, tuple[int, int, int]]:
    """PCM bytes and (channels, sample width, rate) of one WAV from the provider.

    Groq streams its WAV with a placeholder length in the header (0xFFFFFFFF), which
    breaks the standard reader when frames are counted. The audio is simply everything
    after the "data" chunk header, so it is read directly (and clipped to the declared
    size when that size is real)."""
    try:
        with wave.open(io.BytesIO(part), "rb") as reader:
            fmt = (reader.getnchannels(), reader.getsampwidth(), reader.getframerate())
    except (wave.Error, EOFError) as exc:
        raise SpeechError("Speech synthesis returned invalid audio.") from exc
    marker = part.find(b"data", 12)
    if marker < 0 or len(part) < marker + 8:
        raise SpeechError("Speech synthesis returned invalid audio.")
    declared = int.from_bytes(part[marker + 4 : marker + 8], "little")
    pcm = part[marker + 8 :]
    if 0 < declared < len(pcm):
        pcm = pcm[:declared]
    return pcm, fmt


def join_wav(parts: list[bytes]) -> bytes:
    """Concatenate WAV files that share one audio format into one well-formed WAV."""
    out = io.BytesIO()
    fmt: tuple[int, int, int] | None = None
    try:
        with wave.open(out, "wb") as writer:
            for part in parts:
                pcm, part_fmt = _pcm_and_format(part)
                if fmt is None:
                    fmt = part_fmt
                    writer.setnchannels(fmt[0])
                    writer.setsampwidth(fmt[1])
                    writer.setframerate(fmt[2])
                elif part_fmt != fmt:
                    raise SpeechError("Speech synthesis returned mismatched audio.")
                writer.writeframes(pcm)
    except (wave.Error, EOFError) as exc:
        raise SpeechError("Speech synthesis returned invalid audio.") from exc
    return out.getvalue()


def create_stt(settings: Settings) -> SpeechToText:
    return GroqWhisperSTT(settings) if settings.groq_api_key else UnavailableSTT()


def create_tts(settings: Settings) -> TextToSpeech:
    return GroqPlayAITTS(settings) if settings.groq_api_key else UnavailableTTS()
