"""MVDR (Minimum Variance Distortionless Response) beamformer.

Better interference rejection than delay-and-sum at the cost of a covariance
estimate and a linear system solve per frame. We estimate the spatial
covariance matrix R from the current frame, regularise it, and solve
R w = d for the weight vector w that preserves the steering direction
(unit gain toward the source) while minimising total output power.

In practice MVDR is what makes the toggle moment from "audible improvement"
to "the room is gone". The cost is one O(N^3) solve per update, where N
is the number of array elements (3 for us, so essentially free).
"""
from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from .steering import delays_for_direction
from ..config import ArrayGeometry, BeamConfig


def steering_vector(
    azimuth_rad: float,
    geometry: ArrayGeometry,
    sample_rate_hz: int = 48_000,
    n_fft: int = 2048,
    config: BeamConfig | None = None,
) -> NDArray[np.complex128]:
    """Frequency-domain steering vector for the given direction.

    Returns shape (n_freqs, n_elements).
    """
    n_elements = len(geometry.elements)
    n_freqs = n_fft // 2 + 1
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sample_rate_hz)
    delays = delays_for_direction(azimuth_rad, geometry, config, sample_rate_hz)
    # delays[n] is positive; the steering vector entry undoes the propagation
    # delay (positive delay = +j*omega*delay) so signals arriving from the
    # source direction add constructively after weighting.
    sv = np.exp(1j * 2 * np.pi * freqs[:, None] * delays[None, :])
    return sv.astype(np.complex128)


def covariance(
    channels: list[NDArray[np.float32]],
    n_fft: int = 2048,
    n_subframes: int = 8,
) -> NDArray[np.complex128]:
    """Estimate the per-bin spatial covariance matrix R from multiple sub-frames.

    Shape: (n_freqs, n_elements, n_elements). A single full-signal DFT
    gives a rank-1 estimate, which has no degrees of freedom to form
    nulls. Averaging outer products across `n_subframes` overlapping
    sub-frames makes R full-rank and lets MVDR actually suppress
    interferers.

    If the signal is too short to form `n_subframes` sub-frames of
    `n_fft` samples each, we fall back to a single zero-padded DFT at
    `n_fft` so the frequency grid matches the caller's expectation.

    For a real-time implementation, replace the sub-frame slicing with
    an exponential moving average over the most recent frames.
    """
    n_elements = len(channels)
    n = min(c.size for c in channels)
    if n_subframes < 1:
        raise ValueError("n_subframes must be >= 1")
    sub_len = n // n_subframes
    if sub_len < n_fft:
        # Not enough samples to form n_subframes sub-frames of n_fft each;
        # fall back to a single full-signal DFT at n_fft (zero-padding if n < n_fft).
        if n < n_fft:
            padded = [np.pad(c[:n], (0, n_fft - n)) for c in channels]
        else:
            padded = [c[:n_fft] for c in channels]
        specs = np.fft.rfft(np.stack(padded, axis=0), n=n_fft)  # (N, F)
        R = np.einsum("if,jf->fij", specs, specs.conj()) / n_elements
        return R
    R_accum: NDArray[np.complex128] | None = None
    sub_n_fft = min(n_fft, sub_len)
    for s in range(n_subframes):
        start = s * sub_len
        end = start + sub_len
        if end > n:
            end = n
        sub_channels = [c[start:end] for c in channels]
        if sub_channels[0].size < sub_n_fft:
            sub_channels = [np.pad(c, (0, sub_n_fft - c.size)) for c in sub_channels]
        specs = np.fft.rfft(np.stack(sub_channels, axis=0), n=sub_n_fft)  # (N, F)
        R_s = np.einsum("if,jf->fij", specs, specs.conj()) / n_elements
        if R_accum is None:
            R_accum = R_s
        else:
            R_accum = R_accum + R_s
    return R_accum / n_subframes


def mvdr_weights(
    R: NDArray[np.complex128],
    sv: NDArray[np.complex128],
    diagonal_loading: float = 1e-3,
) -> NDArray[np.complex128]:
    """Compute MVDR weights w = R^-1 d / (d^H R^-1 d).

    Diagonal loading prevents R from being singular in quiet frames.
    `np.linalg.solve` is applied per-frequency slice.
    """
    n_freqs, n_elements, _ = R.shape
    assert sv.shape == (n_freqs, n_elements), sv.shape
    eps = np.eye(n_elements) * diagonal_loading
    R_loaded = R + eps[None, :, :]
    # np.linalg.solve expects b of shape (M, K); we add a trailing singleton
    # so it produces one column of weights per frequency bin.
    w = np.linalg.solve(R_loaded, sv[..., None])[..., 0]
    # Normalise so the response toward the source is 1.
    norm = np.einsum("fn,fn->f", sv.conj(), w)
    w = w / norm[:, None]
    return w


def mvdr_beamform(
    channels: list[NDArray[np.float32]],
    azimuth_rad: float,
    geometry: ArrayGeometry,
    sample_rate_hz: int = 48_000,
    n_fft: int | None = None,
    n_subframes: int = 8,
    config: BeamConfig | None = None,
    diagonal_loading: float = 1e-3,
) -> NDArray[np.float32]:
    """Run MVDR on a frame and return the beamformed signal.

    If `n_fft` is None, the entire input is processed in a single DFT
    (works for offline/regression use). For real-time streaming, pass a
    smaller `n_fft` (e.g. 2048) and call this on overlapping windows with
    overlap-add synthesis downstream.
    """
    n_elements = len(channels)
    n = min(c.size for c in channels)
    if n_fft is None:
        n_fft = 1
        while n_fft < n:
            n_fft <<= 1
    else:
        n_fft = min(n_fft, n)
    R = covariance(channels, n_fft=n_fft, n_subframes=n_subframes)
    sv = steering_vector(azimuth_rad, geometry, sample_rate_hz, n_fft, config)
    w = mvdr_weights(R, sv, diagonal_loading=diagonal_loading)
    # Beamform the full signal at the chosen n_fft so the output matches the
    # input length (caller can overlap-add if they used a smaller window).
    specs = np.fft.rfft(np.stack(channels, axis=0), n=n_fft)  # (N, F)
    out_spec = np.einsum("fn,nf->f", w.conj(), specs)
    out = np.fft.irfft(out_spec, n=n_fft).astype(np.float32)
    return out[:n]
