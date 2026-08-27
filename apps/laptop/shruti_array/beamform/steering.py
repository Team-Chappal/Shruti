"""Convert a 2D direction (azimuth in the array's plane) into per-element
delays in samples, suitable for use as beamformer steering vectors.

All maths in the array's local coordinate system: origin at the array's
centroid, x-axis to the right, y-axis forward, z up. Elements are assumed
to sit in the z=0 plane (a real table of phones).
"""
from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from ..config import ArrayGeometry, BeamConfig


def unit_vector(azimuth_rad: float) -> NDArray[np.float64]:
    """Return the 2D unit vector pointing from the array toward the source."""
    return np.asarray([np.cos(azimuth_rad), np.sin(azimuth_rad)], dtype=np.float64)


def delays_for_direction(
    azimuth_rad: float,
    geometry: ArrayGeometry,
    config: BeamConfig | None = None,
    sample_rate_hz: int = 48_000,
) -> NDArray[np.float64]:
    """Return per-element delays in samples for a plane wave arriving from
    `azimuth_rad` (radians, measured CCW from the array's +x axis).

    A positive delay means the element's signal should be delayed in time
    to align with the array centroid. The centroid is the geometric mean
    of the element positions, so for a symmetric array the delays sum
    (weighted by element offset) to zero.
    """
    cfg = config or BeamConfig()
    u = unit_vector(azimuth_rad)
    # Project each element onto the incoming direction. Elements in front
    # of the centroid (toward the source) have a positive projection and
    # hear the wave EARLIER; the time-of-arrival difference is the
    # projection divided by the speed of sound.
    projection = np.asarray(geometry.elements, dtype=np.float64) @ u
    # Positive projection -> earlier arrival -> need to DELAY the signal
    # to align with the centroid -> positive delay in samples.
    delay_s = projection / cfg.speed_of_sound_mps
    return delay_s * sample_rate_hz


def azimuth_from_tdoa(
    tdoa_samples: float,
    baseline_m: float,
    sample_rate_hz: int = 48_000,
    speed_of_sound_mps: float | None = None,
) -> float:
    """Recover the azimuth (radians, measured CCW from +x) from a single
    TDOA measured across a 2-element baseline along the x-axis.

    The convention is `tdoa_samples = t_0 - t_1` in samples, where element 0
    sits at x=-baseline/2 and element 1 at x=+baseline/2. The relationship
    is `tdoa = -(baseline/c) * cos(az) * sample_rate_hz`, so we solve for
    az with `arccos`.

    Linear arrays have a left/right ambiguity (az and 360-az are not
    distinguishable from a single TDOA). Callers that need the unambiguous
    azimuth should also use a second, non-collinear baseline or motion.
    """
    from ..config import BeamConfig
    c = speed_of_sound_mps or BeamConfig().speed_of_sound_mps
    cos_theta = -(tdoa_samples / sample_rate_hz) * c / baseline_m
    cos_theta = max(-1.0, min(1.0, cos_theta))
    return float(np.arccos(cos_theta))
