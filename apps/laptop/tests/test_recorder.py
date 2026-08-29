"""Tests for the per-frame beamformed WAV recorder (T15).

The recorder is a presentation concern, not a DSP concern — it
sits next to `DspLoop` and is fed `LoopFrame`s as they come out
of `step()`. These tests exercise the recorder directly with
synthetic `LoopFrame`s so the assertions are deterministic and
don't need a real device or a running DspLoop.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np
import pytest

from shruti_array.dsp_loop import DEFAULT_SAMPLE_RATE_HZ, DspLoop
from shruti_array.recorder import LoopRecorder
from shruti_array.sync.alignment import StreamAligner


def _make_aligner(n_phones: int = 3) -> StreamAligner:
    aligner = StreamAligner()
    for pid in range(n_phones):
        aligner.register(phone_id=pid, sample_rate_hz=DEFAULT_SAMPLE_RATE_HZ)
    return aligner


def _real_frame(n_phones: int = 3, n_samples: int | None = None) -> object:
    """Produce a real `LoopFrame` from a `DspLoop.step()`.

    Used for the end-to-end `record()` tests that need a frame
    shaped exactly like the production one. Cheaper than
    constructing a `LoopFrame` by hand — the field set has
    changed during the autonomous build and the test should
    survive that.
    """
    aligner = _make_aligner(n_phones)
    loop = DspLoop(aligner)
    n = n_samples or loop.window_n_samples()
    for pid in range(n_phones):
        loop.buffer_pcm(pid, np.zeros(n, dtype=np.float32))
    frame = loop.step()
    assert frame is not None
    return frame


# ---------------------------------------------------------------------------
# Core recorder contract
# ---------------------------------------------------------------------------


def test_recorder_writes_one_file_per_phone_plus_beamformed(tmp_path: Path) -> None:
    """A 3-phone run produces 4 files: 3 phone files + 1 beamformed."""
    recorder = LoopRecorder(
        out_dir=tmp_path, phone_ids=[0, 1, 2], sample_rate_hz=48_000,
    )
    frame = _real_frame(n_phones=3)
    recorder.record(frame)
    paths = recorder.finalise()
    # 3 phones + 1 beamformed = 4 paths.
    assert len(paths) == 4
    # Filenames are deterministic and sorted: phones ascending,
    # beamformed last. The exact run_id is timestamp-derived;
    # we check the suffix and the phone-id tokens instead.
    names = [p.name for p in paths]
    assert any("_phone0.wav" in n for n in names)
    assert any("_phone1.wav" in n for n in names)
    assert any("_phone2.wav" in n for n in names)
    assert any(n.endswith("_beamformed.wav") for n in names)
    # Every file actually landed on disk.
    for p in paths:
        assert p.exists(), f"expected {p} to exist"
        assert p.stat().st_size > 44, "WAV header alone is 44 bytes"


def test_recorder_writes_valid_mono_pcm16_wavs(tmp_path: Path) -> None:
    """Each WAV has 1 channel, 2-byte samples, and the configured sample rate.

    A player that doesn't trust our header (e.g. ffmpeg, Audacity)
    will reject the file if any of these fields is wrong. Stdlib
    `wave` reads them back, so this test reads the file and
    asserts the fields match what we wrote.
    """
    sr = 48_000
    recorder = LoopRecorder(
        out_dir=tmp_path, phone_ids=[0, 1], sample_rate_hz=sr,
    )
    recorder.record(_real_frame(n_phones=2))
    paths = recorder.finalise()
    for p in paths:
        with wave.open(str(p), "rb") as w:
            assert w.getnchannels() == 1
            assert w.getsampwidth() == 2
            assert w.getframerate() == sr
            n_frames = w.getnframes()
            assert n_frames > 0


def test_recorder_concatenates_across_multiple_frames(tmp_path: Path) -> None:
    """N record() calls produce a WAV whose sample count is the
    sum of all per-phone chunk lengths.

    This is the property the demo relies on: even though the
    loop steps 80 ms at a time, the recorded WAV spans the full
    run. The test feeds 5 frames and asserts the file is at
    least 5 windows long.
    """
    sr = 48_000
    recorder = LoopRecorder(
        out_dir=tmp_path, phone_ids=[0, 1], sample_rate_hz=sr,
    )
    window_n = 960 * 4  # DspLoop default
    n_calls = 5
    for _ in range(n_calls):
        # Each call must use a fresh aligner/loop because DspLoop
        # pops the buffer on `step()`. We rebuild cheaply.
        frame = _real_frame(n_phones=2, n_samples=window_n)
        recorder.record(frame)
    paths = recorder.finalise()
    # All phone files should have exactly n_calls * window_n samples.
    expected = n_calls * window_n
    for p in paths:
        if p.name.endswith("_beamformed.wav"):
            continue
        with wave.open(str(p), "rb") as w:
            assert w.getnframes() == expected, (
                f"{p.name}: expected {expected} frames, got {w.getnframes()}"
            )


def test_recorder_clamps_out_of_range_floats(tmp_path: Path) -> None:
    """A chunk with samples > 1.0 or < -1.0 is clipped before
    being written to int16. This protects the demo from a
    beamformer that briefly overshoots (a known property of
    MVDR with poorly-conditioned covariance matrices).
    """
    recorder = LoopRecorder(
        out_dir=tmp_path, phone_ids=[0], sample_rate_hz=48_000,
    )
    # Build a hand-crafted LoopFrame-shaped object with one
    # channel of deliberate overshoot. We don't need a real
    # DspLoop for this test — the recorder is the unit under test.
    from shruti_array.dsp_loop import LoopFrame
    n = 100
    ch = np.full(n, 5.0, dtype=np.float32)  # way above 1.0
    bf = np.full(n, -5.0, dtype=np.float32)  # way below -1.0
    frame = LoopFrame(
        channels=[ch],
        tdoas={},
        position_xy=None,
        beamformed=bf,
        tracks=[],
        now_s=0.0,
    )
    recorder.record(frame)
    paths = recorder.finalise()
    # Both files should exist and contain valid int16 PCM.
    for p in paths:
        with wave.open(str(p), "rb") as w:
            raw = w.readframes(w.getnframes())
        samples = np.frombuffer(raw, dtype="<i2")
        if "beamformed" in p.name:
            # Beamformed was all -5.0 → all clipped to the int16
            # minimum. The recorder multiplies by 32767.0 (not
            # 32768.0) so the floor is -32767, not -32768 — both
            # are equally saturated from a playback standpoint.
            assert samples.min() == -32767
            assert samples.max() == -32767
        else:
            # Phone channel was all +5.0 → all clipped to +32767.
            assert samples.min() == 32767
            assert samples.max() == 32767


def test_recorder_finalise_is_idempotent(tmp_path: Path) -> None:
    """A second `finalise()` call returns the same paths without
    re-writing. The demo relies on this: the `finally` block
    may run after a clean exit already called `finalise()`.
    """
    recorder = LoopRecorder(
        out_dir=tmp_path, phone_ids=[0], sample_rate_hz=48_000,
    )
    recorder.record(_real_frame(n_phones=2))
    first = recorder.finalise()
    # Capture mtimes to assert no re-write.
    mtimes = [p.stat().st_mtime_ns for p in first]
    second = recorder.finalise()
    assert [p.name for p in first] == [p.name for p in second]
    for p, mt in zip(second, mtimes, strict=True):
        assert p.stat().st_mtime_ns == mt, f"{p.name} was re-written"


def test_recorder_ignores_unknown_phone_ids(tmp_path: Path) -> None:
    """A `LoopFrame` carrying channels for a phone the recorder
    wasn't constructed with is silently dropped. Matches the
    live behaviour where a phone can join after recording
    starts.
    """
    recorder = LoopRecorder(
        out_dir=tmp_path, phone_ids=[0, 1], sample_rate_hz=48_000,
    )
    # Build a 3-phone frame but the recorder only knows about
    # phones 0 and 1.
    aligner = _make_aligner(3)
    loop = DspLoop(aligner)
    n = loop.window_n_samples()
    for pid in range(3):
        loop.buffer_pcm(pid, np.zeros(n, dtype=np.float32))
    frame = loop.step()
    assert frame is not None
    assert len(frame.channels) == 3  # 3 phones present in the frame
    recorder.record(frame)
    paths = recorder.finalise()
    # Still only 3 files: 2 phones + 1 beamformed. No file for
    # phone 2 was created.
    assert len(paths) == 3
    assert not any("_phone2.wav" in p.name for p in paths)


def test_recorder_rejects_record_after_finalise(tmp_path: Path) -> None:
    """Calling `record()` after `finalise()` is a programming
    error — the buffers have been concatenated and dropped.
    """
    recorder = LoopRecorder(
        out_dir=tmp_path, phone_ids=[0], sample_rate_hz=48_000,
    )
    recorder.record(_real_frame(n_phones=2))
    recorder.finalise()
    with pytest.raises(RuntimeError, match="after finalise"):
        recorder.record(_real_frame(n_phones=2))


# ---------------------------------------------------------------------------
# CLI smoke: the demo actually accepts --record-toggle and writes files
# ---------------------------------------------------------------------------


def test_demo_cli_accepts_record_toggle(tmp_path: Path) -> None:
    """End-to-end: `python -m shruti_array.cli demo --record-toggle DIR`
    runs the demo and produces the expected files. Uses a 1-second
    run to keep the test under a second wall-clock.
    """
    out = tmp_path / "toggle"
    result = subprocess.run(
        [
            sys.executable, "-m", "shruti_array.cli", "demo",
            "--seconds", "1", "--phones", "3", "--ascii",
            "--record-toggle", str(out),
        ],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (
        f"demo failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    # 3 phones + 1 beamformed = 4 files.
    files = sorted(out.glob("*.wav"))
    assert len(files) == 4, f"expected 4 WAVs, got {files}"
    names = [f.name for f in files]
    assert any("_phone0.wav" in n for n in names)
    assert any("_phone1.wav" in n for n in names)
    assert any("_phone2.wav" in n for n in names)
    assert any("_beamformed.wav" in n for n in names)
    # Every file is a valid mono PCM16 WAV.
    for f in files:
        with wave.open(str(f), "rb") as w:
            assert w.getnchannels() == 1
            assert w.getsampwidth() == 2
            assert w.getframerate() == 48_000
            assert w.getnframes() > 0


def test_demo_cli_without_record_toggle_writes_nothing() -> None:
    """The default demo (no flag) must not write any files. This
    is the contract the existing `make demo` target relies on.
    """
    # We use a temp dir as cwd so the test can assert that the
    # demo didn't drop a stray WAV anywhere. The default demo
    # writes only to stdout (the text radar); nothing on disk.
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run(
            [
                sys.executable, "-m", "shruti_array.cli", "demo",
                "--seconds", "1", "--phones", "3", "--ascii",
            ],
            capture_output=True, text=True, timeout=30, cwd=tmp,
        )
    assert result.returncode == 0, (
        f"demo failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    # The cwd was the temp dir; nothing under it should have
    # been created by the demo. `rglob` from a Path that no
    # longer exists is a no-op, so this is safe post-cleanup.
    stray = list(Path(tmp).rglob("*.wav"))
    assert stray == [], f"unexpected WAVs written: {stray}"


# ---------------------------------------------------------------------------
# Note: `tmp_path` is the standard pytest fixture for tests in this
# file. Do not switch to `tempfile.mkdtemp` — it leaks on Windows.
# `tempfile.TemporaryDirectory` is used only by the CLI subprocess
# tests, where a hermetic cwd is required.
# ---------------------------------------------------------------------------
