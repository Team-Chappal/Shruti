"""Stream alignment and drift compensation.

Each phone produces a stream of PCM frames. They arrive at the laptop with
different network and capture latencies, so they need to be aligned in time
before any spatial processing can happen.

Alignment is a per-phone offset (in samples) plus a per-phone clock-drift
estimate (in parts per million). The offsets are re-estimated whenever a
new chirp echo arrives, and the drift is tracked between chirps using the
frame sequence numbers and timestamps in the protocol.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from .correlation import find_offset_sub_sample


@dataclass
class PhoneStream:
    """A single phone's buffered state."""
    phone_id: int
    sample_rate_hz: int
    # Time-series of (timestamp_us, sample_count) pairs, used to track drift.
    timing_history: deque[tuple[int, int]] = field(default_factory=lambda: deque(maxlen=64))
    # Latest offset (in samples) relative to the master phone.
    offset_samples: float = 0.0
    # Latest drift estimate in parts per million.
    drift_ppm: float = 0.0
    # Local sample buffer (not yet flushed into the aligned stream).
    buffer: NDArray[np.float32] = field(default_factory=lambda: np.empty(0, dtype=np.float32))


class StreamAligner:
    """Aligns multiple PhoneStream objects in time using offset + drift.

    The first phone to register is the master; everything else aligns to it.
    """

    def __init__(self, master_id: int | None = None) -> None:
        self._streams: dict[int, PhoneStream] = {}
        self._master_id = master_id

    @property
    def master_id(self) -> int:
        if self._master_id is None:
            if not self._streams:
                raise RuntimeError("no streams registered yet")
            self._master_id = next(iter(self._streams))
        return self._master_id

    def register(self, phone_id: int, sample_rate_hz: int) -> None:
        if phone_id not in self._streams:
            self._streams[phone_id] = PhoneStream(
                phone_id=phone_id, sample_rate_hz=sample_rate_hz
            )
            if self._master_id is None:
                self._master_id = phone_id

    def set_offset(self, phone_id: int, offset_samples: float) -> None:
        stream = self._streams[phone_id]
        stream.offset_samples = offset_samples

    def estimate_drift(self, phone_id: int) -> float:
        """Update drift estimate from timing history. Returns the new ppm value."""
        stream = self._streams[phone_id]
        history = list(stream.timing_history)
        if len(history) < 4:
            return stream.drift_ppm
        # Linear fit: sample_count = rate * dt + offset; slope drift = slope/ideal - 1.
        ts0, sc0 = history[0]
        tsN, scN = history[-1]
        dt_us = tsN - ts0
        if dt_us <= 0:
            return stream.drift_ppm
        measured_rate = (scN - sc0) * 1_000_000.0 / dt_us
        ideal_rate = stream.sample_rate_hz
        stream.drift_ppm = (measured_rate - ideal_rate) / ideal_rate * 1e6
        return stream.drift_ppm

    def update_timing(self, phone_id: int, timestamp_us: int, sample_count: int) -> None:
        self._streams[phone_id].timing_history.append((timestamp_us, sample_count))

    def alignment_offset_samples(self, phone_id: int, t_samples: int) -> float:
        """Return the sample offset to apply to phone_id at master time t_samples.

        Includes the base offset plus a drift correction that grows linearly
        with t_samples from the last chirp.
        """
        stream = self._streams[phone_id]
        return stream.offset_samples + (stream.drift_ppm * 1e-6) * t_samples

    def all_phone_ids(self) -> list[int]:
        return list(self._streams.keys())

    def unregister(self, phone_id: int) -> bool:
        """Drop a phone from the aligner. Returns True if the
        phone was registered, False otherwise.

        T11: when a phone disconnects mid-demo, the operator
        (or the server's disconnect handler) calls this so
        `DspLoop.step()` stops trying to read from its buffer
        and the array gracefully degrades to the surviving
        elements. The next `all_phone_ids()` reflects the new
        membership, so geometry subsetting in the beamformer
        follows the live count, not the original 3.
        """
        return self._streams.pop(phone_id, None) is not None

    def __contains__(self, phone_id: int) -> bool:
        return phone_id in self._streams


def align_using_chirp(
    reference: NDArray[np.float32],
    recording: NDArray[np.float32],
    sample_rate_hz: int,
) -> float:
    """Helper: estimate the offset (in samples) of a chirp echo against the
    reference chirp. Returns a sub-sample offset suitable for the aligner.
    """
    return find_offset_sub_sample(reference, recording, max_lag=sample_rate_hz // 2)


def now_us() -> int:
    return int(time.time() * 1_000_000)
