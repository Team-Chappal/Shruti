"""Tests for the multi-speaker tracker."""
from __future__ import annotations

from shruti_array.tracker import (
    MultiSpeakerTracker,
    stream_to_speakers,
)


def test_single_track_assigned_to_observations() -> None:
    t = MultiSpeakerTracker()
    for i in range(5):
        tracks = t.update((1.0 + i * 0.01, 0.0), now_s=float(i))
    assert len(tracks) == 1
    assert tracks[0].track_id == 0


def test_two_speakers_become_two_tracks() -> None:
    t = MultiSpeakerTracker(association_radius_m=0.3)
    for i, (x, y) in enumerate([(0.0, 1.0), (2.0, 1.0), (0.0, 1.0), (2.0, 1.0)]):
        t.update((x, y), now_s=float(i))
    assert len(t.tracks) == 2


def test_track_dropped_after_timeout() -> None:
    t = MultiSpeakerTracker(track_timeout_s=0.5, association_radius_m=0.3)
    t.update((0.0, 0.0), now_s=0.0)
    t.update((5.0, 5.0), now_s=0.1)  # new speaker, far away
    t.update(None, now_s=10.0)  # long gap
    assert len(t.tracks) == 0


def test_max_tracks_caps_simultaneous_speakers() -> None:
    t = MultiSpeakerTracker(max_tracks=2, association_radius_m=0.1)
    for i, (x, y) in enumerate([(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0)]):
        t.update((x, y), now_s=float(i))
    assert len(t.tracks) <= 2


def test_stream_to_speakers_convenience() -> None:
    tracks = stream_to_speakers(
        positions=[(0.0, 0.0), (0.1, 0.0), (5.0, 0.0), (5.1, 0.0)],
        times_s=[0, 1, 2, 3],
        association_radius_m=0.3,
    )
    assert len(tracks) == 2
