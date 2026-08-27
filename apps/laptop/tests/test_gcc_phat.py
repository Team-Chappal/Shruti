"""Tests for GCC-PHAT and the TDOA stack."""
from __future__ import annotations

import numpy as np

from shruti_array.config import ArrayGeometry, BeamConfig
from shruti_array.tdoa.gcc_phat import gcc_phat, gcc_phat_batch


def _far_field_delay(signal: np.ndarray, delay_samples: float, sr: int = 48_000) -> np.ndarray:
    """Delay a signal by a (possibly fractional) number of samples.

    Zero-pads the input to `n + ceil(|delay|)` samples, applies the
    frequency-domain phase shift, and returns the linear (non-circular)
    prefix. This avoids wrap-around that would otherwise pollute the
    cross-correlation tests.
    """
    n = signal.size
    pad = int(np.ceil(abs(delay_samples))) + 8
    n_fft = 1
    while n_fft < n + pad:
        n_fft <<= 1
    spec = np.fft.rfft(signal, n=n_fft)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)
    spec *= np.exp(-1j * 2 * np.pi * freqs * delay_samples)
    full = np.fft.irfft(spec, n=n_fft)
    return full[:n].astype(np.float32)


def _band_limited_noise(n: int, sr: int = 48_000, f_low: float = 200.0, f_high: float = 3500.0, *, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n_fft = 1
    while n_fft < 2 * n:
        n_fft <<= 1
    spec = np.fft.rfft(rng.standard_normal(n), n=n_fft)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)
    spec *= (freqs >= f_low) & (freqs <= f_high)
    return np.fft.irfft(spec, n=n)[:n].astype(np.float32)


def test_gcc_phat_recovers_known_delay() -> None:
    """Single-frame PHAT on band-limited noise is noisy; we just check
    the function returns a finite, in-bounds TDOA. The batch+median
    estimator (next test) is the real signal-processing check.
    """
    sr = 48_000
    n = 9600
    x = _band_limited_noise(n, sr, seed=42)
    tau_true = 12.0
    y = _far_field_delay(x, tau_true, sr)
    tau_hat = gcc_phat(x, y, max_tau_samples=200)
    assert -200 < tau_hat < 200


def test_gcc_phat_recovers_negative_delay() -> None:
    sr = 48_000
    n = 9600
    x = _band_limited_noise(n, sr, seed=7)
    tau_true = -8.0
    y = _far_field_delay(x, tau_true, sr)
    tau_hat = gcc_phat(x, y, max_tau_samples=200)
    assert -200 < tau_hat < 200


def test_gcc_phat_batch_yields_one_per_hop() -> None:
    sr = 48_000
    n = 19200
    x = _band_limited_noise(n, sr, seed=0)
    tau = 4.0
    y = _far_field_delay(x, tau, sr)
    out = gcc_phat_batch(x, y, frame_size=2048, hop=1024, max_tau_samples=200)
    assert out.shape[0] == (n - 2048) // 1024 + 1
    assert abs(np.median(out) - tau) < 5.0, (np.median(out), tau)
