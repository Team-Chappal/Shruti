"""Chirp signal generation for ultrasonic clock sync.

One phone plays the chirp on its speaker; every other phone records it on its
mic. The recording phone cross-correlates the reference chirp against its
capture to estimate the playback-to-capture offset to a fraction of a sample.

The chirp is a PRBS-modulated sine swept across the ultrasonic band
(typically 17.5-22 kHz). The PRBS modulation gives the chirp a sharp
auto-correlation peak, so the offset is unambiguous even in the presence of
ambient room noise.
"""
from __future__ import annotations

import numpy as np

from ..config import ChirpConfig


def generate_chirp(config: ChirpConfig | None = None) -> np.ndarray:
    """Render the reference chirp as a float64 array in [-1, 1]."""
    cfg = config or ChirpConfig()
    n_samples = int(round(cfg.duration_s * 48_000))  # 48 kHz is the source rate
    t = np.arange(n_samples) / 48_000.0
    # Linear chirp from f_low to f_high across the duration.
    k = (cfg.f_high_hz - cfg.f_low_hz) / cfg.duration_s
    phase = 2 * np.pi * (cfg.f_low_hz * t + 0.5 * k * t * t)
    carrier = np.sin(phase)

    # PRBS modulation: chip the carrier with a pseudo-random +/- 1 sequence
    # at a chip rate well below the carrier frequency. The PRBS is generated
    # with a 16-bit LFSR seeded from config.prbs_seed.
    chips = _lfsr_sequence(cfg.prbs_seed, n_samples)
    # Upsample: each chip covers 96 samples (48 kHz / 500 chips per second).
    chip_len = 96
    modulation = np.repeat(chips, chip_len)[:n_samples].astype(np.float64)
    if modulation.size < n_samples:
        # Defensive: pad if n_samples is not a multiple of chip_len.
        modulation = np.pad(modulation, (0, n_samples - modulation.size))

    return (carrier * modulation * cfg.amplitude).astype(np.float32)


def _lfsr_sequence(seed: int, n_chips: int) -> np.ndarray:
    """16-bit maximal-length LFSR -> +/-1 sequence of length n_chips."""
    state = seed & 0xFFFF
    if state == 0:
        state = 0xACE1  # LFSR must not start in the all-zero state
    out = np.empty(n_chips, dtype=np.int8)
    for i in range(n_chips):
        bit = ((state >> 0) ^ (state >> 2) ^ (state >> 3) ^ (state >> 5)) & 1
        state = ((state >> 1) | (bit << 15)) & 0xFFFF
        out[i] = 1 if (state & 1) else -1
    return out


def resample_to(signal: np.ndarray, src_hz: int, dst_hz: int) -> np.ndarray:
    """Resample a chirp to a target sample rate using FFT-based interpolation.

    The chirp is rendered once at 48 kHz and reused for any other rate the
    phones might capture at. Linear would be fine for a chirp, but FFT keeps
    the phase relationship exact, which matters for the cross-correlation peak.
    """
    if src_hz == dst_hz:
        return signal
    n_src = signal.shape[0]
    n_dst = int(round(n_src * dst_hz / src_hz))
    # Pad to next power of 2 to avoid cyclic artefacts in the resample.
    n_fft = 1
    while n_fft < n_src + n_dst:
        n_fft <<= 1
    spec = np.fft.rfft(signal, n=n_fft)
    # Rescale frequency bins to the new sample rate.
    np.fft.rfftfreq(n_fft, d=1.0 / src_hz)
    dst_freqs = np.fft.rfftfreq(n_fft, d=1.0 / dst_hz)
    new_spec = np.zeros_like(spec)
    for i, f in enumerate(dst_freqs):
        if f > src_hz / 2:
            break
        # Find the closest source bin to interpolate from.
        j = int(round(f * n_fft / src_hz))
        if 0 <= j < spec.size:
            new_spec[i] = spec[j]
    resampled = np.fft.irfft(new_spec, n=n_fft)[:n_dst]
    return (resampled * (n_dst / n_src)).astype(signal.dtype)
