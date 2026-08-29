"""Tests for the stem-replay module (T07)."""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest

from shruti_array.replay import _load_stem_channels
from shruti_array.replay import main as replay_main


def _write_wav(path: Path, samples: np.ndarray, sample_rate_hz: int) -> None:
    """Write a 16-bit mono PCM WAV (the format the replay module
    reads)."""
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate_hz)
        w.writeframes(pcm)


def test_load_stem_channels_rejects_fewer_than_two_phones(tmp_path: Path) -> None:
    """The replay rung of the fallback ladder needs at least 2
    channels; one phone means the beamformer can't run."""
    (tmp_path / "0_only.wav").write_bytes(b"")
    with pytest.raises(RuntimeError, match="at least 2 phones"):
        _load_stem_channels(tmp_path)


def test_load_stem_channels_supports_ch_prefix_convention(tmp_path: Path) -> None:
    """The `ch<phone_id>.wav` convention used by the synth-corpus
    generator must also work, since that's what the live demo's
    internal fixtures use."""
    sr = 48_000
    t = np.arange(sr) / sr
    samples = (0.3 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
    _write_wav(tmp_path / "ch0.wav", samples, sr)
    _write_wav(tmp_path / "ch1.wav", samples, sr)
    _write_wav(tmp_path / "ch2.wav", samples, sr)
    loaded_sr, channels = _load_stem_channels(tmp_path)
    assert loaded_sr == sr
    assert len(channels) == 3
    assert sorted(pid for pid, _ in channels) == [0, 1, 2]


def test_load_stem_channels_supports_phone_id_prefix_convention(tmp_path: Path) -> None:
    """The `<phone_id>_<...>.wav` convention used by the
    recorded-corpus batch rung must also work, since recorded
    stems use this naming."""
    sr = 48_000
    t = np.arange(sr) / sr
    samples = (0.3 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
    _write_wav(tmp_path / "0_room_a.wav", samples, sr)
    _write_wav(tmp_path / "1_room_a.wav", samples, sr)
    loaded_sr, channels = _load_stem_channels(tmp_path)
    assert loaded_sr == sr
    assert sorted(pid for pid, _ in channels) == [0, 1]


def test_load_stem_channels_rejects_sample_rate_mismatch(tmp_path: Path) -> None:
    """If two phones record at different rates, the beamformer
    can't combine them. Fail fast with a clear error."""
    sr_a, sr_b = 48_000, 44_100
    t_a = np.arange(sr_a) / sr_a
    t_b = np.arange(sr_b) / sr_b
    _write_wav(tmp_path / "ch0.wav", (0.3 * np.sin(2 * np.pi * 440.0 * t_a)).astype(np.float32), sr_a)
    _write_wav(tmp_path / "ch1.wav", (0.3 * np.sin(2 * np.pi * 440.0 * t_b)).astype(np.float32), sr_b)
    with pytest.raises(RuntimeError, match="sample rate mismatch"):
        _load_stem_channels(tmp_path)


def test_replay_cli_rejects_missing_directory(tmp_path: Path) -> None:
    """`shruti-array replay /no/such/dir` must fail with exit 2
    and a useful error, not crash."""
    rc = replay_main([str(tmp_path / "no_such_dir"), "--seconds", "0.1"])
    assert rc == 2
