"""Delay-and-sum beamformer.

The simplest spatial filter: align every channel to the steering direction
(by integer-sample delay), then average. Robust, near-zero tuning, and good
enough to be the demo's "RAW -> BEAMFORMED" toggle moment.

Fractional-sample delays are handled with a frequency-domain phase shift,
which is exact for the given DFT length.
"""
from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from ..config import ArrayGeometry, BeamConfig
from .steering import delays_for_direction


def delay_and_sum(
    channels: list[NDArray[np.float32]],
    azimuth_rad: float,
    geometry: ArrayGeometry,
    sample_rate_hz: int = 48_000,
    config: BeamConfig | None = None,
) -> NDArray[np.float32]:
    """Beamform a batch of N equal-length channels steered at azimuth_rad.

    Returns a single mono signal of the same length as each input channel.
    """
    if not channels:
        raise ValueError("no channels supplied")
    n_samples = channels[0].size
    for c in channels:
        if c.size != n_samples:
            raise ValueError("all channels must have the same length")

    delays = delays_for_direction(azimuth_rad, geometry, config, sample_rate_hz)
    if len(delays) != len(channels):
        raise ValueError(
            f"geometry has {len(delays)} elements, got {len(channels)} channels"
        )

    n_fft = 1
    while n_fft < 2 * n_samples:
        n_fft <<= 1
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sample_rate_hz)
    accum = np.zeros(n_fft // 2 + 1, dtype=np.complex128)
    for ch, delay in zip(channels, delays, strict=False):
        spec = np.fft.rfft(ch, n=n_fft)
        # Negative delay in samples -> positive phase shift in frequency.
        accum += spec * np.exp(1j * 2 * np.pi * freqs * delay)
    accum /= len(channels)
    out = np.fft.irfft(accum, n=n_fft).astype(np.float32)
    return out[:n_samples]
