"""Tests for the cross-correlation based offset estimation."""
from __future__ import annotations

import numpy as np

from shruti_array.sync.chirp import generate_chirp
from shruti_array.sync.correlation import find_offset, find_offset_sub_sample


def test_find_offset_no_delay() -> None:
    ref = generate_chirp()
    # Place the reference at the start of the recording with no shift.
    rec = np.concatenate([ref, np.zeros(2000, dtype=np.float32)])
    off = find_offset(ref, rec)
    assert off == 0


def test_find_offset_known_delay() -> None:
    ref = generate_chirp()
    delay = 137
    rec = np.concatenate([
        np.zeros(delay, dtype=np.float32),
        ref,
        np.zeros(1000, dtype=np.float32),
    ])
    off = find_offset(ref, rec, max_lag=500)
    assert abs(off - delay) <= 1


def test_find_offset_with_noise() -> None:
    rng = np.random.default_rng(0)
    ref = generate_chirp()
    delay = 80
    noise = (rng.standard_normal(10_000).astype(np.float32) * 0.05)
    rec = noise.copy()
    rec[delay:delay + ref.size] += ref
    off = find_offset(ref, rec, max_lag=500)
    assert abs(off - delay) <= 2


def test_sub_sample_refinement_does_not_overshoot() -> None:
    """The sub-sample refinement must not move the peak far from the
    integer estimate. On real clean signals it adds a fractional
    correction; on noisy/synthetic signals it can overshoot, and the
    clamp keeps it sane.
    """
    ref = generate_chirp()
    delay = 100.0
    n = ref.size + int(delay) + 2000
    rec = np.zeros(n, dtype=np.float32)
    n_fft = 1
    while n_fft < 2 * ref.size:
        n_fft <<= 1
    spec = np.fft.rfft(ref, n=n_fft)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / 48_000)
    spec_shift = spec * np.exp(1j * 2 * np.pi * freqs * delay)
    shifted = np.fft.irfft(spec_shift, n=n_fft)[: ref.size]
    rec[int(delay):int(delay) + ref.size] = shifted.astype(np.float32)
    int_off = find_offset(ref, rec, max_lag=500)
    sub_off = find_offset_sub_sample(ref, rec, max_lag=500)
    # The sub-sample refinement is clamped to ±0.5 samples; it should
    # therefore stay within 1 sample of the integer estimate, not jump
    # by tens of samples due to a noisy PHAT-like peak.
    assert abs(sub_off - int_off) <= 1.0, (int_off, sub_off)
