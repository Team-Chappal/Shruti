"""Cross-correlation based offset estimation.

Given the reference chirp and a recording that contains it, return the
sample offset where the recording best aligns with the reference. The
correlation is computed in the frequency domain (FFT-based) so it's O(N
log N) rather than O(N^2), and works for long recordings without breaking
a sweat.
"""
from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def find_offset(
    reference: NDArray[np.float32],
    recording: NDArray[np.float32],
    *,
    max_lag: int | None = None,
) -> int:
    """Return the signed sample offset that aligns `recording` to `reference`,
    using the convention:

        recording[n] ~= reference[n - offset]

    i.e. a positive `offset` means the reference is shifted RIGHT relative to
    the recording — the chirp arrived `offset` samples LATE in the recording
    (the recording was started `offset` samples before the chirp).

    The cross-correlation `xcorr[k] = sum_n reference[n] * recording[n - k]`
    is computed via the Wiener-Khinchin relation; its peak (after
    windowing to `max_lag` on each side) gives the lag `k` such that the
    recording is the reference shifted LEFT by `k`. Therefore the returned
    offset is the negative of that lag.
    """
    if reference.size == 0 or recording.size == 0:
        raise ValueError("empty input")
    n_fft = _next_pow2(reference.size + recording.size)
    ref_f = np.fft.rfft(reference, n=n_fft)
    rec_f = np.fft.rfft(recording, n=n_fft)
    # `xcorr[k] = sum_n reference[n] * recording[(n - k) mod n_fft]`.
    # We want the lag `k` that maximises the linear (non-wrapping) correlation.
    # The irfft places the zero-lag at index 0; positive lags occupy [0, n/2]
    # and negative lags wrap to the end of the array.
    xcorr = np.fft.irfft(ref_f * np.conj(rec_f), n=n_fft)
    if max_lag is not None:
        xcorr = _window_lag(xcorr, max_lag)
    peak = int(np.argmax(xcorr))
    n = xcorr.size
    # Map the circular lag index to a signed lag in (-n/2, n/2].
    lag = peak if peak <= n // 2 else peak - n
    return -lag


def find_offset_sub_sample(
    reference: NDArray[np.float32],
    recording: NDArray[np.float32],
    *,
    max_lag: int | None = None,
) -> float:
    """Like `find_offset`, but refines the integer peak with parabolic
    interpolation on the surrounding three samples, giving sub-sample
    precision. Useful for reporting the 100-microsecond number on the demo.
    """
    n_fft = _next_pow2(reference.size + recording.size)
    ref_f = np.fft.rfft(reference, n=n_fft)
    rec_f = np.fft.rfft(recording, n=n_fft)
    xcorr = np.fft.irfft(ref_f * np.conj(rec_f), n=n_fft)
    if max_lag is not None:
        xcorr = _window_lag(xcorr, max_lag)

    peak = int(np.argmax(xcorr))
    n = xcorr.size
    # Parabolic refinement in the wrapped (circular) domain.
    if peak == 0 or peak == n - 1:
        lag = peak if peak <= n // 2 else peak - n
        return float(-lag)
    y_m1 = xcorr[(peak - 1) % n]
    y_0 = xcorr[peak]
    y_p1 = xcorr[(peak + 1) % n]
    denom = y_m1 - 2.0 * y_0 + y_p1
    if abs(denom) < 1e-12:
        delta = 0.0
    else:
        delta = 0.5 * (y_m1 - y_p1) / denom
    refined_peak = peak + delta
    lag = refined_peak if refined_peak <= n // 2 else refined_peak - n
    return float(-lag)


def _next_pow2(n: int) -> int:
    p = 1
    while p < n:
        p <<= 1
    return p


def _window_lag(xcorr: NDArray, max_lag: int) -> NDArray:
    """Zero out everything outside [-max_lag, max_lag] of the zero-lag point.

    The zero-lag position is at index 0 in the irfft output. Negative lags
    wrap to the high end of the array. We zero the regions we don't want.
    """
    out = xcorr.copy()
    n = out.size
    if max_lag < n // 2:
        out[max_lag + 1 : n - max_lag] = 0
    return out
