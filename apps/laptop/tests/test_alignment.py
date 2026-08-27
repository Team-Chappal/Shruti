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


def test_align_using_chirp_recovers_known_offset() -> None:
    ref = generate_chirp()
    delay = 73
    rec = np.concatenate([np.zeros(delay, dtype=np.float32), ref, np.zeros(1000, dtype=np.float32)])
    off = align_using_chirp(ref, rec, 48_000)
    assert abs(off - delay) < 0.5
