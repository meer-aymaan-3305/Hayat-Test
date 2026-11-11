"""Groq streams WAV files with a placeholder length; joined replies must still be valid."""

import io
import struct
import wave

from hayat_backend.speech import join_wav


def _streamed_wav(samples: int) -> bytes:
    """A 24 kHz mono 16-bit WAV whose header declares the unknown length 0xFFFFFFFF."""
    pcm = b"\x01\x00" * samples
    header = (
        b"RIFF" + struct.pack("<L", 0xFFFFFFFF) + b"WAVE"
        + b"fmt " + struct.pack("<LHHLLHH", 16, 1, 1, 24000, 48000, 2, 16)
        + b"data" + struct.pack("<L", 0xFFFFFFFF)
    )
    return header + pcm


def test_single_provider_wav_is_rewritten_with_a_real_length():
    joined = join_wav([_streamed_wav(1200)])
    with wave.open(io.BytesIO(joined), "rb") as reader:
        assert reader.getnframes() == 1200
        assert reader.getframerate() == 24000


def test_several_provider_wavs_are_joined_in_order():
    joined = join_wav([_streamed_wav(1000), _streamed_wav(500), _streamed_wav(250)])
    with wave.open(io.BytesIO(joined), "rb") as reader:
        assert reader.getnframes() == 1750
