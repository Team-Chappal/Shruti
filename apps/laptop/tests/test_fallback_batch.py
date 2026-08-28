"""Tests for the fallback ladder.

The fallback module is what the team reaches for when the live
WebSocket stream is down. Two non-trivial paths:
  - `batch_ingest` does end-to-end: WAV discovery -> load -> TDOA ->
    beamform -> write. This test pins all of those.
  - `pick_most_recent_per_phone` must understand both the
    '<phone_id>_<...>.wav' convention (recorded corpus) and the
    'ch<phone_id>.wav' convention (synth corpus).
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest

from shruti_array.fallback import (
    RUNG_BATCH_FILE,
    RUNG_LIVE_STREAM,
    RUNG_RED_LIGHT,
    LadderRung,
    batch_ingest,
    next_rung,
    pick_most_recent_per_phone,
    read_wav,
)


def _write_wav(path: Path, samples: np.ndarray, sample_rate_hz: int = 48_000) -> None:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate_hz)
        w.writeframes(pcm)


def test_ladder_ordering_is_live_then_batch_then_red_light() -> None:
    """The ladder rung order is the contract that recipe.md and
    OPERATIONS.md both reference; a reorder silently breaks the
    fallback strategy."""
    assert next_rung(RUNG_LIVE_STREAM) is RUNG_BATCH_FILE
    assert next_rung(RUNG_BATCH_FILE) is RUNG_RED_LIGHT
    # Bottom rung is its own floor.
    assert next_rung(RUNG_RED_LIGHT) is RUNG_RED_LIGHT
    # All rungs are LadderRung instances.
    for r in (RUNG_LIVE_STREAM, RUNG_BATCH_FILE, RUNG_RED_LIGHT):
        assert isinstance(r, LadderRung)


def test_pick_most_recent_per_phone_handles_both_filenames_conventions(
    tmp_path: Path,
) -> None:
    """The synth corpus writes ch0.wav / ch1.wav / ch2.wav. The
    recorded-corpus convention is <phone_id>_<scene>.wav. A
    real on-site batch ingest will see both depending on how the
    files got there, so the helper must accept either.
    """
    sr = 48_000
    for i in range(3):
        _write_wav(tmp_path / f"ch{i}.wav", np.zeros(sr, dtype=np.float32))
    _write_wav(tmp_path / "0_classroom.wav", np.zeros(sr, dtype=np.float32))
    _write_wav(tmp_path / "1_classroom.wav", np.zeros(sr, dtype=np.float32))
    _write_wav(tmp_path / "2_classroom.wav", np.zeros(sr, dtype=np.float32))
    picks = pick_most_recent_per_phone(tmp_path)
    assert sorted(picks) == [0, 1, 2]
    # Filenames should match the convention seen first; with both
    # present we don't assert which one wins, just that the IDs are
    # 0/1/2 and the files exist.
    for _phone_id, path in picks.items():
        assert path.exists()
        assert path.suffix == ".wav"


def test_pick_most_recent_per_phone_skips_unparseable_names(
    tmp_path: Path,
) -> None:
    """Files that don't match either convention are ignored, not
    crash-causing. A junk .DS_Store or README.md in the directory
    must not break batch ingest."""
    _write_wav(tmp_path / "ch0.wav", np.zeros(48_000, dtype=np.float32))
    _write_wav(tmp_path / "ch1.wav", np.zeros(48_000, dtype=np.float32))
    (tmp_path / "README.md").write_text("not a wav")
    (tmp_path / ".DS_Store").write_bytes(b"\x00\x01")
    picks = pick_most_recent_per_phone(tmp_path)
    assert sorted(picks) == [0, 1]


def test_pick_most_recent_returns_empty_for_missing_directory(
    tmp_path: Path,
) -> None:
    """Missing directory is a recoverable case (the phone's sdcard
    hasn't synced yet), not a crash."""
    assert pick_most_recent_per_phone(tmp_path / "does-not-exist") == {}


def test_batch_ingest_writes_a_valid_wav(tmp_path: Path) -> None:
    """End-to-end: 2 phones, simple sine targets, batch beamform
    the directory, check the output WAV is a valid 48 kHz mono PCM
    of the right length."""
    sr = 48_000
    n = sr * 2  # 2 seconds
    rng = np.random.default_rng(0)
    # Both phones hear the same sine plus small independent noise.
    target = 0.5 * np.sin(2 * np.pi * 440.0 * np.arange(n) / sr)
    for pid in (0, 1):
        signal = target + 0.01 * rng.standard_normal(n).astype(np.float32)
        _write_wav(tmp_path / f"{pid}_classroom.wav", signal, sr)
    out = tmp_path / "out.wav"
    result = batch_ingest(tmp_path, out, beamform="das")
    assert result == out
    assert out.exists()
    with wave.open(str(out), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == sr
        assert w.getnframes() == n


def test_batch_ingest_mvdr_path_also_works(tmp_path: Path) -> None:
    """MVDR branch is a separate code path; pin it."""
    sr = 48_000
    n = sr * 2
    rng = np.random.default_rng(1)
    target = 0.5 * np.sin(2 * np.pi * 440.0 * np.arange(n) / sr)
    for pid in (0, 1, 2):
        signal = target + 0.01 * rng.standard_normal(n).astype(np.float32)
        _write_wav(tmp_path / f"{pid}_classroom.wav", signal, sr)
    out = tmp_path / "out_mvdr.wav"
    batch_ingest(tmp_path, out, beamform="mvdr")
    assert out.exists()


def test_batch_ingest_requires_at_least_two_phones(tmp_path: Path) -> None:
    """One phone is not enough to beamform; must error loudly,
    not silently produce a zero-length or self-equalised output."""
    _write_wav(tmp_path / "0_alone.wav", np.zeros(48_000, dtype=np.float32))
    with pytest.raises(RuntimeError, match="at least 2 phones"):
        batch_ingest(tmp_path, tmp_path / "out.wav")


def test_batch_ingest_rejects_sample_rate_mismatch(tmp_path: Path) -> None:
    """If the two phones captured at different rates, batch
    beamform must refuse rather than silently resample (which
    would defeat the point of an array calibration)."""
    _write_wav(tmp_path / "0_44k.wav", np.zeros(48_000, dtype=np.float32), 44_100)
    _write_wav(tmp_path / "1_44k.wav", np.zeros(48_000, dtype=np.float32), 48_000)
    with pytest.raises(RuntimeError, match="sample rate mismatch"):
        batch_ingest(tmp_path, tmp_path / "out.wav")


def test_read_wav_roundtrip(tmp_path: Path) -> None:
    """A 1-second 440 Hz sine written then read back must be the
    same float32 array (within int16 quantisation)."""
    sr = 48_000
    t = np.arange(sr) / sr
    original = 0.5 * np.sin(2 * np.pi * 440.0 * t).astype(np.float32)
    path = tmp_path / "rt.wav"
    _write_wav(path, original, sr)
    got_sr, got_samples = read_wav(path)
    assert got_sr == sr
    assert got_samples.shape == original.shape
    # int16 quantisation is ~1.5e-5; the difference is well below
    # anything the beamformer downstream cares about.
    assert np.max(np.abs(got_samples - original)) < 1e-4
