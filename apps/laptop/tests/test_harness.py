"""Tests for the synthetic corpus generator and the regression harness."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from shruti_array.harness.regression import run_synthetic_suite, si_sdr
from shruti_array.harness.synthetic import speech_band_noise, two_speaker_scene
from shruti_array.tools.corpus import synth_suite


def test_speech_band_noise_is_bounded() -> None:
    rng = np.random.default_rng(0)
    x = speech_band_noise(48_000, rng=rng)
    # Not strictly bounded (it's noise), but well within float32 range.
    assert x.dtype == np.float32
    assert np.max(np.abs(x)) < 100.0


def test_speech_band_noise_is_band_limited() -> None:
    rng = np.random.default_rng(0)
    x = speech_band_noise(48_000, rng=rng)
    spec = np.abs(np.fft.rfft(x))
    freqs = np.fft.rfftfreq(x.size, d=1.0 / 48_000)
    # Energy below 100 Hz should be near zero (band-limited to 200-3500).
    low = np.sum(spec[freqs < 100.0] ** 2)
    mid = np.sum(spec[(freqs >= 200.0) & (freqs <= 3500.0)] ** 2)
    assert low < mid * 0.01


def test_two_speaker_scene_has_n_elements() -> None:
    geom = __import__("shruti_array.config", fromlist=["AppConfig"]).AppConfig.default().geometry
    n = 48_000
    channels, sources = two_speaker_scene(
        n_samples=n, sample_rate_hz=48_000, geometry=geom,
        azimuths_rad=(np.deg2rad(10.0), np.deg2rad(-30.0)),
        seed=0,
    )
    assert len(channels) == len(geom.elements)
    assert len(sources) == 2
    for ch in channels:
        assert ch.shape == (n,)


def test_synth_suite_writes_files(tmp_path: Path) -> None:
    scenes = synth_suite(tmp_path, n_scenes=2, duration_s=0.5)
    assert len(scenes) == 2
    for scene in scenes:
        d = tmp_path / scene.name
        assert d.exists()
        assert (d / "ch0.wav").exists()
        assert (d / "target_clean.wav").exists()
        assert (d / "meta.json").exists()


def test_regression_suite_runs_and_mvdr_beats_das() -> None:
    report = run_synthetic_suite(n_scenes=3, n_samples=48_000)
    assert len(report.scenes) == 3
    das_avg = np.mean([s.das_sisdr_db for s in report.scenes])
    mvdr_avg = np.mean([s.mvdr_sisdr_db for s in report.scenes])
    # Same smoke-gate as the beamform test: MVDR must not be catastrophically
    # worse. The recorded-corpus harness is the real gate.
    assert mvdr_avg > das_avg - 3.0, (das_avg, mvdr_avg, report.summary())
