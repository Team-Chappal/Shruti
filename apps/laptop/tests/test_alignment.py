"""Tests for the stream aligner."""
from __future__ import annotations

import numpy as np

from shruti_array.sync.alignment import StreamAligner, align_using_chirp
from shruti_array.sync.chirp import generate_chirp


def test_register_and_set_offset() -> None:
    aligner = StreamAligner(master_id=0)
    aligner.register(0, 48_000)
    aligner.register(1, 48_000)
    aligner.set_offset(1, 12.5)
    assert aligner.alignment_offset_samples(1, 1000) == 12.5


def test_drift_grows_linearly_with_time() -> None:
    aligner = StreamAligner(master_id=0)
    aligner.register(0, 48_000)
    aligner.register(1, 48_000)
    aligner.set_offset(1, 0.0)
    aligner._streams[1].drift_ppm = 100.0  # 100 ppm
    # 1 second = 48_000 samples; 100 ppm = 100/1e6 = 0.0001 samples/sample
    # 48000 * 0.0001 = 4.8 samples of drift over 1 second.
    assert abs(aligner.alignment_offset_samples(1, 48_000) - 4.8) < 1e-6


def test_estimate_drift_from_timing_history() -> None:
    """A history of timestamps that imply ~1% drift should be picked up
    by the linear fit."""
    aligner = StreamAligner(master_id=0)
    aligner.register(0, 48_000)
    aligner.register(1, 48_000)
    # estimate_drift needs >= 4 history points. Feed 4 points that
    # imply 1% fast (48_480 samples per 1 s, instead of 48_000).
    aligner.update_timing(1, 0, 0)
    aligner.update_timing(1, 250_000, 12_120)
    aligner.update_timing(1, 500_000, 24_240)
    aligner.update_timing(1, 1_000_000, 48_480)
    drift = aligner.estimate_drift(1)
    # (48_480/48_000 - 1) * 1e6 = 10_000 ppm
    assert abs(drift - 10_000.0) < 1.0


def test_estimate_drift_insufficient_history_returns_existing() -> None:
    aligner = StreamAligner(master_id=0)
    aligner.register(0, 48_000)
    aligner.register(1, 48_000)
    aligner._streams[1].drift_ppm = 42.0
    aligner.update_timing(1, 0, 0)
    aligner.update_timing(1, 100, 100)  # only 2 points
    assert aligner.estimate_drift(1) == 42.0


def test_align_using_chirp_recovers_known_offset() -> None:
    ref = generate_chirp()
    delay = 73
    rec = np.concatenate([np.zeros(delay, dtype=np.float32), ref, np.zeros(1000, dtype=np.float32)])
    off = align_using_chirp(ref, rec, 48_000)
    assert abs(off - delay) < 0.5


def test_master_id_set_on_first_register() -> None:
    aligner = StreamAligner()
    aligner.register(3, 48_000)
    assert aligner.master_id == 3
    assert 3 in aligner


def test_no_phones_raises() -> None:
    aligner = StreamAligner()
    try:
        _ = aligner.master_id
    except RuntimeError as e:
        assert "no streams" in str(e)
    else:
        raise AssertionError("expected RuntimeError")
