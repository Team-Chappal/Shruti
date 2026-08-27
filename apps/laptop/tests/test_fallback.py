"""Tests for the fallback ladder."""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest

from shruti_array.fallback import (
    RUNG_BATCH_FILE,
    RUNG_LIVE_STREAM,
    RUNG_RED_LIGHT,
    list_batch_files,
    next_rung,
    pick_most_recent_per_phone,
    read_wav,
)


def test_next_rung_walks_the_ladder() -> None:
    assert next_rung(RUNG_LIVE_STREAM) is RUNG_BATCH_FILE
    assert next_rung(RUNG_BATCH_FILE) is RUNG_RED_LIGHT
    assert next_rung(RUNG_RED_LIGHT) is RUNG_RED_LIGHT  # bottom is sticky


def test_read_wav_roundtrips(tmp_path) -> None:
    sr = 48_000
    samples = (np.arange(sr, dtype=np.float32) / sr * 0.1)
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    p = tmp_path / "test_read.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)
    r_sr, r_data = read_wav(p)
    assert r_sr == sr
    assert r_data.shape == (sr,)
    assert np.max(np.abs(r_data - samples)) < 1e-3


def test_list_batch_files_returns_wavs(tmp_path: Path) -> None:
    (tmp_path / "0_capture.wav").write_bytes(b"fake")
    (tmp_path / "1_capture.wav").write_bytes(b"fake")
    (tmp_path / "notes.txt").write_bytes(b"ignore")
    files = list_batch_files(tmp_path)
    assert len(files) == 2
    assert all(f.suffix == ".wav" for f in files)


def test_list_batch_files_filters_by_phone(tmp_path: Path) -> None:
    (tmp_path / "0_capture.wav").write_bytes(b"")
    (tmp_path / "1_capture.wav").write_bytes(b"")
    files = list_batch_files(tmp_path, phone_id=1)
    assert len(files) == 1
    assert files[0].stem.startswith("1_")


def test_pick_most_recent_per_phone(tmp_path: Path) -> None:
    (tmp_path / "0_a.wav").write_bytes(b"")
    (tmp_path / "0_b.wav").write_bytes(b"")
    (tmp_path / "1_a.wav").write_bytes(b"")
    picked = pick_most_recent_per_phone(tmp_path)
    assert set(picked.keys()) == {0, 1}


def test_pick_most_recent_per_phone_empty() -> None:
    assert pick_most_recent_per_phone(Path("/nonexistent")) == {}
