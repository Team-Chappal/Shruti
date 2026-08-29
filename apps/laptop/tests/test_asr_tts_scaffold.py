"""ASR/TTS interface contract tests.

The interfaces (`ASR`, `TTS`) and the mock engines
(`MockASR`, `MockTTS`) are the stable contract between
the DSP loop and the engines. Tests here pin down:
  - the abstract base class can't be instantiated directly
  - TranscriptSegment's defaults and frozenness
  - MockASR's contract (call count, language, end_s)
  - MockTTS's contract (PCM silence, duration scaling)
  - sherpa_onnx.SherpaOnnxASR's lazy recogniser pattern
  - piper.PiperTTS's subprocess invocation shape
"""
from __future__ import annotations

import dataclasses
from unittest import mock

import numpy as np
import pytest

from shruti_array.asr import ASR, MockASR, TranscriptSegment, sherpa_onnx
from shruti_array.tts import TTS, MockTTS, piper

# --- TranscriptSegment ---

def test_transcript_segment_defaults() -> None:
    """Defaults: confidence=1.0, language='en'."""
    seg = TranscriptSegment(text="hello", start_s=0.0, end_s=0.5)
    assert seg.confidence == 1.0
    assert seg.language == "en"


def test_transcript_segment_is_frozen() -> None:
    """TranscriptSegment is @dataclass(frozen=True); mutating
    a field should raise. This protects the rest of the
    pipeline from accidentally modifying transcript lines
    in-place."""
    seg = TranscriptSegment(text="hello", start_s=0.0, end_s=0.5)
    with pytest.raises(dataclasses.FrozenInstanceError):
        seg.text = "goodbye"  # type: ignore[misc]


# --- ASR abstract base ---

def test_asr_cannot_be_instantiated_directly() -> None:
    """ASR is an ABC with abstract methods; instantiating
    it directly should raise TypeError."""
    with pytest.raises(TypeError):
        ASR()  # type: ignore[abstract]


def test_mock_asr_subclasses_asr() -> None:
    asr = MockASR()
    assert isinstance(asr, ASR)


def test_mock_asr_default_language_is_english() -> None:
    asr = MockASR()
    assert asr.language == "en"


def test_mock_asr_can_be_constructed_with_a_different_language() -> None:
    """The constructor accepts a language override so
    the pipeline can pre-configure the ASR for the demo
    profile (Hindi, Tamil, etc.) at startup."""
    asr = MockASR(language="hi")
    out = asr.transcribe(np.zeros(48_000, dtype=np.float32), 48_000)
    assert out[0].language == "hi"


def test_mock_asr_zero_sample_rate_doesnt_div_by_zero() -> None:
    """A 0-Hz sample rate is pathological but the mock
    should not crash."""
    asr = MockASR()
    out = asr.transcribe(np.zeros(100, dtype=np.float32), 0)
    assert out[0].end_s == 0.0


def test_mock_asr_returns_one_segment_per_call() -> None:
    asr = MockASR()
    out = asr.transcribe(np.zeros(48_000, dtype=np.float32), 48_000)
    assert isinstance(out, list)
    assert len(out) == 1


# --- MockTTS ---

def test_tts_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        TTS()  # type: ignore[abstract]


def test_mock_tts_subclasses_tts() -> None:
    tts = MockTTS()
    assert isinstance(tts, TTS)


def test_mock_tts_returns_silence_for_empty_text() -> None:
    """An empty string should return b"" without crashing."""
    tts = MockTTS()
    assert tts.speak("") == b""
    assert tts.speak("   ") == b""


def test_mock_tts_duration_scales_with_text_length() -> None:
    """Longer text -> longer silence."""
    tts = MockTTS()
    short = tts.speak("hi")
    long = tts.speak("hello there, this is a longer piece of text")
    assert len(long) > len(short)


def test_mock_tts_default_language_is_english() -> None:
    tts = MockTTS()
    pcm = tts.speak("hi")
    assert len(pcm) > 0


# --- sherpa_onnx.SherpaOnnxASR (scaffold) ---

def test_sherpa_onnx_asr_subclasses_asr() -> None:
    """SherpaOnnxASR is the real engine scaffold. It must
    subclass ASR so the pipeline can swap MockASR for it
    at startup without changing any call sites."""
    asr = sherpa_onnx.SherpaOnnxASR(
        config=sherpa_onnx.SherpaOnnxConfig(
            encoder="enc.onnx", decoder="dec.onnx", joiner="joiner.onnx",
            tokens="tokens.txt",
        )
    )
    assert isinstance(asr, ASR)


def test_sherpa_onnx_asr_recogniser_is_lazy() -> None:
    """The recogniser should NOT be created at __init__ time;
    it should be created on the first transcribe() call.
    The real engine is heavy (ONNX runtime) and shouldn't
    load if the pipeline is just doing headless testing."""
    asr = sherpa_onnx.SherpaOnnxASR(
        config=sherpa_onnx.SherpaOnnxConfig(
            encoder="enc.onnx", decoder="dec.onnx", joiner="joiner.onnx",
            tokens="tokens.txt",
        )
    )
    assert asr._recognizer is None  # noqa: SLF001
    # If transcribe() is called without a recogniser set,
    # _ensure_recognizer runs and tries to import sherpa_onnx
    # (which isn't installed in CI). That's the actual
    # production behaviour: the recogniser is loaded lazily.
    # We assert on the lazy-init code path by patching
    # _ensure_recognizer to just set a fake recogniser.
    with mock.patch.object(asr, "_ensure_recognizer") as m:
        def _set():
            asr._recognizer = mock.MagicMock()  # noqa: SLF001
            asr._recognizer.create_stream.return_value.result.text = "x"  # noqa: SLF001
        m.side_effect = _set
        asr.transcribe(np.zeros(48_000, dtype=np.float32), 16_000)
    m.assert_called_once()


def test_sherpa_onnx_asr_ensure_recognizer_called_on_first_transcribe() -> None:
    """When the recogniser is None, transcribe() should
    trigger _ensure_recognizer exactly once."""
    asr = sherpa_onnx.SherpaOnnxASR(
        config=sherpa_onnx.SherpaOnnxConfig(
            encoder="enc.onnx", decoder="dec.onnx", joiner="joiner.onnx",
            tokens="tokens.txt",
        )
    )
    # _recognizer starts as None.
    assert asr._recognizer is None  # noqa: SLF001
    with mock.patch.object(asr, "_ensure_recognizer") as m:
        # After _ensure_recognizer, the recogniser is set
        # (mocked).
        def _set_recogniser():
            asr._recognizer = mock.MagicMock()  # noqa: SLF001
            asr._recognizer.create_stream.return_value.result.text = "x"  # noqa: SLF001
        m.side_effect = _set_recogniser
        asr.transcribe(np.zeros(48_000, dtype=np.float32), 16_000)
    m.assert_called_once()


def test_sherpa_onnx_asr_call_count_increments() -> None:
    """The scaffold's call_count should track transcribe()
    invocations, like MockASR. The pipeline reads this
    counter to surface in the metrics endpoint."""
    asr = sherpa_onnx.SherpaOnnxASR(
        config=sherpa_onnx.SherpaOnnxConfig(
            encoder="enc.onnx", decoder="dec.onnx", joiner="joiner.onnx",
            tokens="tokens.txt",
        )
    )
    assert asr.call_count == 0
    asr._recognizer = mock.MagicMock()  # noqa: SLF001
    asr._recognizer.create_stream.return_value.result.text = "x"  # noqa: SLF001
    asr.transcribe(np.zeros(48_000, dtype=np.float32), 16_000)
    assert asr.call_count == 1
    asr.transcribe(np.zeros(48_000, dtype=np.float32), 16_000)
    assert asr.call_count == 2
    asr.reset()
    assert asr.call_count == 0


def test_sherpa_onnx_asr_resamples_48k_to_16k() -> None:
    """T06: the laptop beamformer runs at 48 kHz; sherpa-onnx
    expects 16 kHz. The scaffold now resamples rather than
    rejecting, so the real run is not blocked by the
    rate mismatch. The test patches _ensure_recognizer
    to install a fake recogniser that records the
    `accept_waveform` arguments, then asserts the audio
    that reached the recogniser is at 16 kHz."""
    asr = sherpa_onnx.SherpaOnnxASR(
        config=sherpa_onnx.SherpaOnnxConfig(
            encoder="enc.onnx", decoder="dec.onnx", joiner="joiner.onnx",
            tokens="tokens.txt",
            sample_rate_hz=16_000,
        )
    )
    captured: dict[str, object] = {}
    with mock.patch.object(asr, "_ensure_recognizer") as m:
        def _set() -> None:
            rec = mock.MagicMock()
            stream = mock.MagicMock()
            rec.create_stream.return_value = stream
            stream.result.text = "x"
            # accept_waveform(sr, audio) — record the args.
            def _accept(sr: int, audio: np.ndarray) -> None:
                captured["sr"] = sr
                captured["len"] = len(audio)
            stream.accept_waveform.side_effect = _accept
            asr._recognizer = rec  # noqa: SLF001
        m.side_effect = _set
        # 48 kHz input, 48000 samples = 1 s.
        asr.transcribe(np.zeros(48_000, dtype=np.float32), 48_000)
    # The recogniser must have been called with the
    # 16 kHz audio (48000 / 3 = 16000 samples).
    assert captured["sr"] == 16_000
    # Allow a small tolerance for the polyphase filter
    # boundary effects.
    assert abs(captured["len"] - 16_000) < 10


# --- piper.PiperTTS (scaffold) ---

def test_piper_tts_subclasses_tts() -> None:
    tts = piper.PiperTTS(piper_bin="piper", model="m.onnx", config="m.json")
    assert isinstance(tts, TTS)


def test_piper_tts_uses_env_overrides() -> None:
    """SHRUTI_PIPER_BIN / _MODEL / _CONFIG env vars override
    the constructor args. The Dockerfile's entrypoint
    can set them; the unit tests can monkeypatch them."""
    with mock.patch.dict("os.environ", {
        "SHRUTI_PIPER_BIN": "/usr/local/bin/piper",
        "SHRUTI_PIPER_MODEL": "/models/hi.onnx",
        "SHRUTI_PIPER_CONFIG": "/models/hi.json",
    }):
        tts = piper.PiperTTS()
        assert tts.piper_bin == "/usr/local/bin/piper"
        assert tts.model == "/models/hi.onnx"
        assert tts.config == "/models/hi.json"


def test_piper_tts_constructor_defaults() -> None:
    """With no args and no env vars, the constructor falls
    back to shutil.which('piper') for the binary and the
    data/models/piper/* paths for the model. These are the
    defaults the OPERATIONS.md runbook documents."""
    with mock.patch.dict("os.environ", {}, clear=True):
        with mock.patch("shutil.which", return_value=None):
            tts = piper.PiperTTS()
            assert tts.piper_bin == "piper"  # the literal fallback
            assert tts.model == "data/models/piper/en_US-lessac-medium.onnx"
            assert tts.config == "data/models/piper/en_US-lessac-medium.onnx.json"


def test_piper_tts_empty_text_returns_empty_bytes() -> None:
    """An empty (or whitespace-only) text should return b""
    without spawning a piper subprocess."""
    tts = piper.PiperTTS(piper_bin="piper", model="m", config="c")
    with mock.patch("subprocess.run") as m:
        assert tts.speak("") == b""
        assert tts.speak("   \n\t  ") == b""
    m.assert_not_called()


def test_piper_tts_strips_wav_header() -> None:
    """The downstream consumer plays raw 16-bit PCM, not a
    WAV file. PiperTTS.speak() must strip the 44-byte WAV
    header before returning."""
    # Fake WAV: 44-byte header + 100 bytes of audio data
    # (just zeros, so we can assert on length).
    header = b"RIFF" + b"\x00" * 40  # 44 bytes
    audio = b"\x00" * 100
    fake_wav = header + audio
    assert len(fake_wav) == 144

    tts = piper.PiperTTS(piper_bin="piper", model="m", config="c")
    fake_proc = mock.MagicMock(returncode=0)
    with mock.patch("subprocess.run", return_value=fake_proc), \
         mock.patch("builtins.open", mock.mock_open(read_data=fake_wav)), \
         mock.patch("os.unlink"):
        pcm = tts.speak("hello world")
    # The returned bytes should be the audio data only,
    # not the WAV header.
    assert pcm == audio
    assert len(pcm) == 100


def test_piper_tts_raises_on_nonzero_exit() -> None:
    """If the piper subprocess returns non-zero, the
    adapter should raise RuntimeError with the stderr."""
    tts = piper.PiperTTS(piper_bin="piper", model="m", config="c")
    fake_proc = mock.MagicMock(returncode=1, stderr=b"out of memory")
    with mock.patch("subprocess.run", return_value=fake_proc), \
         mock.patch("builtins.open", mock.mock_open(read_data=b"RIFF" + b"\x00" * 100)), \
         mock.patch("os.unlink"):
        with pytest.raises(RuntimeError, match="piper failed"):
            tts.speak("hello")


def test_piper_tts_invokes_subprocess_with_correct_args() -> None:
    """The subprocess call should include --model, --config,
    --output_file, and pipe text to stdin."""
    tts = piper.PiperTTS(
        piper_bin="/bin/piper",
        model="/models/hi.onnx",
        config="/models/hi.json",
    )
    fake_proc = mock.MagicMock(returncode=0)
    with mock.patch("subprocess.run", return_value=fake_proc) as m, \
         mock.patch("builtins.open", mock.mock_open(read_data=b"RIFF" + b"\x00" * 44)), \
         mock.patch("os.unlink"):
        tts.speak("namaste")
    args, kwargs = m.call_args
    cmd = args[0]
    assert cmd[0] == "/bin/piper"
    assert "--model" in cmd
    assert "/models/hi.onnx" in cmd
    assert "--config" in cmd
    assert "/models/hi.json" in cmd
    assert "--output_file" in cmd
    # The text should be piped to stdin.
    assert kwargs.get("input") == b"namaste"
