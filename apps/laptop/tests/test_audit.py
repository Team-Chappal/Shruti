"""Tests for the device-audit analyzer."""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from shruti_array.tools.audit import analyze_directory, analyze_wav


def _write_wav(path: Path, samples: np.ndarray, sample_rate_hz: int) -> None:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate_hz)
        w.writeframes(pcm)


def test_analyze_wav_basic(tmp_path: Path) -> None:
    sr = 48_000
    t = np.arange(sr) / sr
    sig = (0.1 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    p = tmp_path / "0_capture.wav"
    _write_wav(p, sig, sr)
    r = analyze_wav(p, phone_id=0)
    assert r.phone_id == 0
    assert r.sample_rate_hz == sr
    assert abs(r.duration_s - 1.0) < 1e-3
    assert r.rms_dbfs < 0.0
    assert r.noise_floor_dbfs < 0.0


def test_analyze_directory_finds_files(tmp_path: Path) -> None:
    sr = 48_000
    for i in range(3):
        sig = (np.random.default_rng(i).standard_normal(sr).astype(np.float32) * 0.05)
        _write_wav(tmp_path / f"{i}_c.wav", sig, sr)
    reports = analyze_directory(tmp_path)
    assert len(reports) == 3
    assert {r.phone_id for r in reports} == {0, 1, 2}
