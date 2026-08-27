"""Synthetic multi-channel audio generators for the regression harness.

A real noisy-room corpus comes from recording actual rooms; the synthetic
generator here lets the harness run anywhere, deterministically, and is
what every CI run uses. The generator models:

  - A speaker at a known azimuth, emitting speech-band noise.
  - Spatially uncorrelated diffuse background noise.
  - Per-element per-channel gain + a small per-element delay to simulate
    the array's actual geometry.

The output is a list of channels, each as a float32 array. The caller
controls the random seed so runs are reproducible.
"""
from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from ..beamform.steering import delays_for_direction
from ..config import ArrayGeometry, BeamConfig


def speech_band_noise(
    n_samples: int,
    sample_rate_hz: int = 48_000,
    *,
    f_low_hz: float = 200.0,
    f_high_hz: float = 3_500.0,
    rng: np.random.Generator,
) -> NDArray[np.float32]:
    """Band-limited white noise approximating the long-term spectrum of speech.

    Cheap and good enough for harness purposes; not a substitute for real
    speech recordings, but it has the right spectral shape to make
    GCC-PHAT behave realistically.
    """
    n_fft = 1
    while n_fft < 2 * n_samples:
        n_fft <<= 1
    spec = np.fft.rfft(rng.standard_normal(n_samples), n=n_fft)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sample_rate_hz)
    mask = (freqs >= f_low_hz) & (freqs <= f_high_hz)
    spec *= mask
    return np.fft.irfft(spec, n=n_fft)[:n_samples].astype(np.float32)


def far_field_signal(
    source: NDArray[np.float32],
    geometry: ArrayGeometry,
    azimuth_rad: float,
    sample_rate_hz: int = 48_000,
    config: BeamConfig | None = None,
    snr_db: float = 20.0,
    rng: np.random.Generator | None = None,
) -> list[NDArray[np.float32]]:
    """Place `source` in the far field of `geometry` and add diffuse noise.

    Returns one channel per element. The source arrives at each element
    delayed by the propagation path difference from the chosen azimuth.
    """
    rng = rng or np.random.default_rng()
    n_samples = source.size
    len(geometry.elements)
    delays = delays_for_direction(azimuth_rad, geometry, config, sample_rate_hz)
    channels: list[NDArray[np.float32]] = []
    for delay in delays:
        # Apply the propagation delay (in samples, can be fractional) with
        # a frequency-domain phase shift.
        n_fft = 1
        while n_fft < 2 * n_samples:
            n_fft <<= 1
        spec = np.fft.rfft(source, n=n_fft)
        freqs = np.fft.rfftfreq(n_fft, d=1.0 / sample_rate_hz)
        spec *= np.exp(-1j * 2 * np.pi * freqs * delay)
        ch = np.fft.irfft(spec, n=n_fft)[:n_samples].astype(np.float32)
        # Add uncorrelated background noise to hit the requested SNR.
        noise = rng.standard_normal(n_samples).astype(np.float32)
        noise *= np.linalg.norm(ch) / (np.linalg.norm(noise) * 10 ** (snr_db / 20.0))
        ch = ch + noise
        channels.append(ch)
    return channels


def two_speaker_scene(
    n_samples: int,
    sample_rate_hz: int,
    geometry: ArrayGeometry,
    *,
    azimuths_rad: tuple[float, ...] = (np.deg2rad(20.0), np.deg2rad(-40.0)),
    snr_db: float = 15.0,
    seed: int = 1234,
) -> tuple[list[NDArray[np.float32]], list[NDArray[np.float32]]]:
    """Render a scene with N speakers at known azimuths. Returns (channels, sources).

    The `sources` list is the ground-truth clean signal at each azimuth,
    useful for SI-SNR computation in the regression harness.
    """
    rng = np.random.default_rng(seed)
    sources = [speech_band_noise(n_samples, sample_rate_hz, rng=rng) for _ in azimuths_rad]
    channels: list[NDArray[np.float32]] | None = None
    for source, az in zip(sources, azimuths_rad, strict=False):
        chs = far_field_signal(
            source, geometry, az, sample_rate_hz, snr_db=snr_db, rng=rng
        )
        if channels is None:
            channels = chs
        else:
            for c, new in zip(channels, chs, strict=False):
                c += new
    assert channels is not None
    return channels, sources
