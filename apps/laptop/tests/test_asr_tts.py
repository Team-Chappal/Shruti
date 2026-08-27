"""Tests for the ASR and TTS interfaces (mock engines)."""
from __future__ import annotations

import numpy as np

from shruti_array.asr import MockASR
from shruti_array.tts import MockTTS


def test_mock_asr_reports_duration() -> None:
    asr = MockASR()
    samples = np.zeros(48_000, dtype=np.float32)  # 1 s
    out = asr.transcribe(samples, 48_000)
    assert len(out) == 1
    assert "duration=1.000s" in out[0].text
    assert "samples=48000" in out[0].text
    assert out[0].end_s == 1.0


def test_mock_asr_increments_call_count() -> None:
    asr = MockASR()
    asr.transcribe(np.zeros(480, dtype=np.float32), 48_000)
    asr.transcribe(np.zeros(480, dtype=np.float32), 48_000)
    assert asr.call_count == 2
    asr.reset()
    assert asr.call_count == 0


def test_mock_tts_returns_pcm_silence() -> None:
    tts = MockTTS()
    pcm = tts.speak("hi")
    # 0.1 s/char but min 0.5 s -> 0.5 s at 16 kHz int16 = 16000 samples.
    assert len(pcm) == 2 * 16_000 // 2
    # Silence = all zeros.
    assert pcm == b"\x00\x00" * (len(pcm) // 2)
