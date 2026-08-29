"""Tests for the ASR and TTS interfaces (mock engines)."""
from __future__ import annotations

import numpy as np
import pytest

from shruti_array.asr import MockASR, make_asr
from shruti_array.config import AsrConfig
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


# T06: the make_asr factory + AsrConfig engine switch.
def test_make_asr_default_is_mock() -> None:
    """The default AsrConfig has engine='mock', so the factory
    returns a MockASR without needing any model files. CI
    relies on this — pytest must not require a 300 MB
    model download to pass."""
    asr = make_asr(AsrConfig())
    assert isinstance(asr, MockASR)


def test_make_asr_rejects_unknown_engine() -> None:
    """A typo in the engine name must raise, not silently
    fall back to mock. The fallback decision (issue T06:
    "If the model fights back, ship the fallback") is
    the operator's, not the tool's."""
    from shruti_array.asr import make_asr as _make
    with pytest.raises(ValueError, match="unknown ASR engine"):
        _make(AsrConfig(engine="definitely-not-a-engine"))  # type: ignore[arg-type]


def test_make_asr_honours_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """The env var override lets the operator swap engines
    without a config change."""
    monkeypatch.setenv("SHRUTI_ASR_ENGINE", "mock")
    asr = make_asr(AsrConfig())
    assert isinstance(asr, MockASR)
    # Unsetting the env var falls back to the config's value.
    monkeypatch.delenv("SHRUTI_ASR_ENGINE", raising=False)
    asr2 = make_asr(AsrConfig())
    assert isinstance(asr2, MockASR)


def test_make_asr_constructs_sherpa_engine_when_requested() -> None:
    """When engine='sherpa' and the model files don't exist
    yet, the factory should still construct the wrapper
    (loading happens lazily on the first transcribe call)."""
    from shruti_array.asr.sherpa_onnx import SherpaOnnxASR
    asr = make_asr(AsrConfig(
        engine="sherpa",
        sherpa_encoder="/nonexistent/encoder.onnx",
        sherpa_decoder="/nonexistent/decoder.onnx",
        sherpa_joiner="/nonexistent/joiner.onnx",
        sherpa_tokens="/nonexistent/tokens.txt",
    ))
    assert isinstance(asr, SherpaOnnxASR)
    # The recognizer is lazy: it must NOT have loaded yet.
    assert asr._recognizer is None  # noqa: SLF001
    # First transcribe call must fail with a clear error, not
    # silently mis-transcribe.
    with pytest.raises(RuntimeError, match="sherpa-onnx"):
        asr.transcribe(np.zeros(160, dtype=np.float32), 16_000)
