"""Tests for the chirp generator."""
from __future__ import annotations

import numpy as np

from shruti_array.config import ChirpConfig
from shruti_array.sync.chirp import generate_chirp, resample_to


def test_chirp_is_in_amplitude_bound() -> None:
    cfg = ChirpConfig(amplitude=0.4)
    x = generate_chirp(cfg)
    assert x.dtype == np.float32
    assert np.max(np.abs(x)) <= cfg.amplitude + 1e-6
    assert x.size == int(round(cfg.duration_s * 48_000))


def test_chirp_prbs_is_not_constant() -> None:
    x = generate_chirp()
    # The PRBS modulation should make the chirp deviate from a pure tone;
    # the variance should be well above zero.
    assert np.std(x) > 0.05


def test_resample_to_preserves_length_ratio() -> None:
    x = generate_chirp(ChirpConfig(duration_ms=20.0))
    y16 = resample_to(x, src_hz=48_000, dst_hz=16_000)
    # The number of samples should be close to src/dst ratio.
    assert abs(y16.size - x.size * 16_000 // 48_000) <= 2
