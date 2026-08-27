"""Multi-speaker tracker.

Given a stream of per-pair TDOAs and the array geometry, track up to
N distinct speakers over time, each with its own beamformed output
and transcript line.

Implementation: a simple nearest-neighbour association on the
estimated (x, y) position. Each frame, the tracker receives a set of
TDOAs, calls `localize_2d` to get a position, and matches it to the
closest existing track within a radius. Unmatched positions spawn
new tracks; tracks that haven't been updated in N frames are
dropped.

This is deliberately simple; the demo's "two speakers at different
positions" is well within the nearest-neighbour regime.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray


@dataclass
class Track:
    track_id: int
    last_position: tuple[float, float]
    last_seen_s: float
    history: deque[tuple[float, float]] = field(default_factory=lambda: deque(maxlen=64))

    def update(self, position: tuple[float, float], now_s: float) -> None:
        self.last_position = position
        self.last_seen_s = now_s
        self.history.append(position)


class MultiSpeakerTracker:
    def __init__(
        self,
        max_tracks: int = 4,
        association_radius_m: float = 0.6,
        track_timeout_s: float = 2.0,
    ) -> None:
        self.max_tracks = max_tracks
        self.association_radius_m = association_radius_m
        self.track_timeout_s = track_timeout_s
        self._next_id = 0
        self._tracks: list[Track] = []

    @property
    def tracks(self) -> list[Track]:
        return list(self._tracks)

    def update(self, position: tuple[float, float] | None, now_s: float | None = None) -> list[Track]:
        """Add a new position observation. Returns the current set of tracks.

        If `position` is None, no association is attempted (the frame
        didn't yield a confident localisation); stale tracks are still
        pruned.
        """
        now_s = now_s if now_s is not None else time.time()
        if position is not None:
            best = self._find_closest(position)
            if best is not None:
                best.update(position, now_s)
            elif len(self._tracks) < self.max_tracks:
                self._tracks.append(Track(self._next_id, position, now_s))
                self._next_id += 1
        self._prune(now_s)
        return self.tracks

    def _find_closest(self, position: tuple[float, float]) -> Track | None:
        best: Track | None = None
        best_d = self.association_radius_m
        for t in self._tracks:
            d = float(np.hypot(
                t.last_position[0] - position[0],
                t.last_position[1] - position[1],
            ))
            if d <= best_d:
                best = t
                best_d = d
        return best

    def _prune(self, now_s: float) -> None:
        self._tracks = [
            t for t in self._tracks
            if (now_s - t.last_seen_s) <= self.track_timeout_s
        ]

    def reset(self) -> None:
        self._tracks.clear()
        self._next_id = 0


def stream_to_speakers(
    positions: list[tuple[float, float] | None],
    times_s: list[float] | None = None,
    **tracker_kwargs,
) -> list[Track]:
    """Convenience: feed a sequence of positions to a fresh tracker and
    return the final state. Useful for tests and the radar UI replay.
    """
    if times_s is None:
        times_s = list(range(len(positions)))
    tracker = MultiSpeakerTracker(**tracker_kwargs)
    for pos, t in zip(positions, times_s):
        tracker.update(pos, t)
    return tracker.tracks
