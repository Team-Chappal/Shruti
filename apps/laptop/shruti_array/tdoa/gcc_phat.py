"""GCC-PHAT (Generalised Cross-Correlation with Phase Transform).

Given two synchronised audio channels, estimate the time-difference-of-arrival
(TDOA) between them. The PHAT weighting whitens the spectrum before the
inverse FFT, so the cross-correlation is dominated by the relative phase
rather than the energy in any particular frequency band. This makes the
peak much sharper in reverberant environments.

The function returns a fractional-sample TDOA. The result is in samples
of the input sample rate; convert to seconds or metres with
`/ sample_rate_hz` or `* speed_of_sound / sample_rate_hz`.
"""
from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def gcc_phat(
    x: NDArray[np.float32],
    y: NDArray[np.float32],
    *,
    max_tau_samples: int | None = None,
) -> float:
    """Return the time-difference-of-arrival of `y` relative to `x`, in samples.

    A positive return value means `y` is delayed relative to `x` (i.e., the
    signal at `x` was observed at `y`'s position `tau` samples earlier).
    Equivalently, shifting `y` forward by `tau` samples aligns it with `x`.

    The irfft of `X * conj(Y)` is a cross-correlation whose peak index,
    interpreted as a signed lag in (-n_fft/2, n_fft/2], gives the TDOA
    directly: for y delayed by +tau, the peak is at index +tau.
    """
    if x.size != y.size:
        raise ValueError("GCC-PHAT requires equal-length inputs")
    n = x.size
    n_fft = 1
    while n_fft < 2 * n:
        n_fft <<= 1
    X = np.fft.rfft(x, n=n_fft)
    Y = np.fft.rfft(y, n=n_fft)
    R = X * np.conj(Y)
    eps = 1e-12
    R /= np.maximum(np.abs(R), eps)
    cc = np.fft.irfft(R, n=n_fft)
    if max_tau_samples is not None and max_tau_samples < n_fft // 2:
        cc = cc.copy()
        cc[max_tau_samples + 1 : n_fft - max_tau_samples] = 0.0
    peak = int(np.argmax(cc))
    if peak == 0 or peak == n_fft - 1:
        signed_lag = 0.0
    else:
        y_m1 = cc[(peak - 1) % n_fft]
        y_0 = cc[peak]
        y_p1 = cc[(peak + 1) % n_fft]
        denom = y_m1 - 2.0 * y_0 + y_p1
        if abs(denom) < 1e-12:
            delta = 0.0
        else:
            delta = 0.5 * (y_m1 - y_p1) / denom
        # Clamp the parabolic refinement to a sane sub-sample range.
        # On noisy PHAT peaks the raw delta can be huge and overshoot
        # the true peak by tens of samples; the peak index itself is
        # the reliable answer.
        delta = max(-0.5, min(0.5, delta))
        refined = peak + delta
        signed_lag = refined if refined <= n_fft // 2 else refined - n_fft
    return float(signed_lag)


def gcc_phat_batch(
    x: NDArray[np.float32],
    y: NDArray[np.float32],
    *,
    frame_size: int,
    hop: int,
    max_tau_samples: int | None = None,
) -> NDArray[np.float32]:
    """Run GCC-PHAT on a sliding window of (x, y). Returns one TDOA per hop."""
    n = x.size
    if y.size != n:
        raise ValueError("x and y must have the same length")
    if frame_size > n:
        raise ValueError("frame_size larger than input")
    out: list[float] = []
    for start in range(0, n - frame_size + 1, hop):
        tau = gcc_phat(
            x[start : start + frame_size], y[start : start + frame_size],
            max_tau_samples=max_tau_samples,
        )
        out.append(tau)
    return np.asarray(out, dtype=np.float32)
