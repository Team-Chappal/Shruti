"""Speaker localisation from per-pair TDOAs.

Given the geometry and the TDOA between element pairs, return the (x, y)
position (in metres, in the array's local frame) of the speaker, or None
if the measurements don't converge.

For a 3-element planar array we have 3 pair-wise TDOAs; least-squares
over-determines the 2D position. The non-linear constraint is that the
speaker lies on a hyperbola for each pair; we solve by minimising the
squared residuals between the measured TDOAs and the ones predicted by
a candidate (x, y).
"""
from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from ..beamform.steering import azimuth_from_tdoa
from ..config import ArrayGeometry, BeamConfig


def pair_tdoas_to_azimuth(
    tdoas: dict[tuple[int, int], float],
    geometry: ArrayGeometry,
    sample_rate_hz: int = 48_000,
) -> float | None:
    """Estimate a single azimuth (radians) from a dictionary of TDOAs.

    `tdoas` maps (phone_i, phone_j) -> TDOA in samples. We pick the longest
    baseline as the most informative single measurement and return its
    azimuth. For a full 2D position use `localize_2d`.
    """
    if not tdoas:
        return None
    best: tuple[float, float] | None = None
    for (i, j), tau in tdoas.items():
        p_i = np.asarray(geometry.element(i), dtype=np.float64)
        p_j = np.asarray(geometry.element(j), dtype=np.float64)
        baseline = float(np.linalg.norm(p_i - p_j))
        if baseline < 1e-3:
            continue
        az = azimuth_from_tdoa(tau, baseline, sample_rate_hz)
        if best is None or baseline > best[0]:
            best = (baseline, az)
    return best[1] if best is not None else None


def localize_2d(
    tdoas: dict[tuple[int, int], float],
    geometry: ArrayGeometry,
    sample_rate_hz: int = 48_000,
    speed_of_sound_mps: float | None = None,
) -> tuple[float, float] | None:
    """Estimate the speaker's (x, y) position in metres from pair TDOAs.

    Returns None if there aren't enough measurements or the solver doesn't
    converge. Otherwise returns the (x, y) position closest to the array
    centroid.
    """
    if len(tdoas) < 2:
        return None
    cfg_speed = BeamConfig().speed_of_sound_mps
    c = speed_of_sound_mps or cfg_speed

    # Build the residual function: for each (i, j, tau), the predicted
    # range-difference between i and j is c * tau / sample_rate_hz, and the
    # measured one is |p - p_i| - |p - p_j|.
    pairs = []
    for (i, j), tau in tdoas.items():
        p_i = np.asarray(geometry.element(i), dtype=np.float64)
        p_j = np.asarray(geometry.element(j), dtype=np.float64)
        meas = c * tau / sample_rate_hz
        pairs.append((p_i, p_j, meas))

    def residuals(p: NDArray) -> NDArray:
        return np.asarray(
            [np.linalg.norm(p - pi) - np.linalg.norm(p - pj) - meas for pi, pj, meas in pairs]
        )

    # Initial guess: average of all element positions (centroid).
    p0 = np.mean([geometry.element(i) for i in range(geometry.num_elements())], axis=0)
    # Try a few candidate initialisations to escape local minima.
    best: tuple[float, NDArray] | None = None
    for offset in [np.zeros(2), np.array([1.0, 0.0]), np.array([-1.0, 0.0]), np.array([0.0, 1.0]), np.array([0.0, -1.0])]:
        try:
            sol = _least_squares(residuals, p0 + offset)
        except Exception:
            continue
        r = np.linalg.norm(residuals(sol))
        if best is None or r < best[0]:
            best = (r, sol)
    if best is None:
        return None
    return float(best[1][0]), float(best[1][1])


def _least_squares(fn, x0: NDArray) -> NDArray:
    """Gauss-Newton non-linear least squares. Bound the search to a 10 m
    radius around the centroid so the solver can't wander into the
    stratosphere when the measurements are bad.
    """
    x = x0.copy()
    for _ in range(50):
        r = fn(x)
        # Numerical Jacobian.
        eps = 1e-4
        J = np.empty((r.size, x.size))
        for k in range(x.size):
            x_plus = x.copy()
            x_plus[k] += eps
            r_plus = fn(x_plus)
            J[:, k] = (r_plus - r) / eps
        # Solve J dx = -r.
        try:
            dx, *_ = np.linalg.lstsq(J, -r, rcond=None)
        except np.linalg.LinAlgError:
            break
        # Bound the step.
        if np.linalg.norm(dx) > 5.0:
            dx = dx * 5.0 / np.linalg.norm(dx)
        x = x + dx
        if np.linalg.norm(dx) < 1e-6:
            break
    # Bound the result to a 10 m radius.
    if np.linalg.norm(x) > 10.0:
        x = x * 10.0 / np.linalg.norm(x)
    return x
