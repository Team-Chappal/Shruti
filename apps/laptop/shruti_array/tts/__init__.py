"""Text-to-speech interface for readback.

The demo's transcript pane is a real-time subtitle; the optional TTS
readback speaks the latest line aloud. Like ASR, the real engine is
loaded on the device; the laptop processor holds only the interface
and a mock.
"""
from __future__ import annotations

import abc


class TTS(abc.ABC):
    """Abstract base class for TTS engines."""

    @abc.abstractmethod
    def speak(self, text: str, language: str = "en") -> bytes:
        """Return the synthesised speech as PCM bytes (16 kHz mono int16).

        The default mock implementation returns silence; a real engine
        returns the rendered waveform.
        """
        ...


class MockTTS(TTS):
    def speak(self, text: str, language: str = "en") -> bytes:
        # An empty or whitespace-only string returns no audio
        # (matches PiperTTS's contract on line 55-56 of
        # piper.py — the real engine also produces silence
        # for empty input).
        if not text.strip():
            return b""
        # 100 ms of silence per character, never less than 0.5s. Plenty
        # for the demo's "did it actually speak?" check.
        duration_s = max(0.5, 0.1 * len(text))
        n_samples = int(duration_s * 16_000)
        return b"\x00\x00" * n_samples
