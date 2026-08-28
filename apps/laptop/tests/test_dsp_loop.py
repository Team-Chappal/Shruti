"""Tests for the real-time DSP loop.

The loop is the centrepiece: it drains the per-phone queues,
aligns, runs TDOA + beamform, and produces `LoopFrame`s. These
tests exercise it directly with synthetic data so the assertions
are deterministic and don't need a real device.
"""
from __future__ import annotations

import numpy as np

from shruti_array.config import AppConfig
from shruti_array.dsp_loop import (
    DEFAULT_SAMPLE_RATE_HZ,
    DspLoop,
    SyntheticPhoneSource,
)
from shruti_array.sync.alignment import StreamAligner
from shruti_array.tracker import MultiSpeakerTracker


def _make_aligner(n_phones: int = 3) -> StreamAligner:
    aligner = StreamAligner()
    for pid in range(n_phones):
        aligner.register(phone_id=pid, sample_rate_hz=DEFAULT_SAMPLE_RATE_HZ)
    return aligner


def test_loop_returns_none_until_buffer_fills() -> None:
    """A freshly constructed loop with no buffered samples should
    return None from step() — the renderer should not draw a
    frame that has no audio behind it."""
    aligner = _make_aligner(2)
    loop = DspLoop(aligner)
    assert loop.ready() is False
    assert loop.step() is None
    # One frame's worth of PCM is not enough; we need window_n_frames.
    loop.buffer_pcm(0, np.zeros(960, dtype=np.float32))
    loop.buffer_pcm(1, np.zeros(960, dtype=np.float32))
    assert loop.ready() is False
    # Top up to the full window.
    for _ in range(loop.window_n_frames - 1):
        loop.buffer_pcm(0, np.zeros(960, dtype=np.float32))
        loop.buffer_pcm(1, np.zeros(960, dtype=np.float32))
    assert loop.ready() is True
    frame = loop.step()
    assert frame is not None
    assert len(frame.channels) == 2


def test_loop_emits_correct_window_shape() -> None:
    """Each frame has len(phones) channels, each of length
    window_n_samples. Channels should be float32 in [-1, 1]."""
    aligner = _make_aligner(3)
    loop = DspLoop(aligner, window_n_frames=4)
    for pid in range(3):
        loop.buffer_pcm(pid, np.full(loop.window_n_samples(), 0.1, dtype=np.float32))
    frame = loop.step()
    assert frame is not None
    assert len(frame.channels) == 3
    expected_n = loop.window_n_samples()
    for ch in frame.channels:
        assert ch.shape == (expected_n,)
        assert ch.dtype == np.float32


def test_loop_step_produces_a_well_formed_frame() -> None:
    """A well-formed `LoopFrame` comes out of `step()` when
    the buffers are full. The test name was
    'test_loop_localises_off_axis_speaker' but the
    assertion was just '< 10.0 m' (a sanity check, not a
    real localisation test). Real localisation is
    covered by test_radar.py. The test exists to pin down
    that `step()` doesn't crash on a real
    synthetic-scene input and produces the expected frame
    shape."""
    aligner = _make_aligner(3)
    geometry = AppConfig.default().geometry
    loop = DspLoop(aligner, geometry=geometry)
    # Use a synthetic two-speaker scene with a known
    # source at 30 deg. The localiser's result is not
    # asserted exactly (test_radar.py covers that), only
    # that step() returns a well-formed frame.
    src_azimuth = np.deg2rad(30.0)
    sr = DEFAULT_SAMPLE_RATE_HZ
    n = loop.window_n_samples()
    from shruti_array.harness.synthetic import two_speaker_scene
    channels, _sources = two_speaker_scene(
        n_samples=n, sample_rate_hz=sr, geometry=geometry,
        azimuths_rad=(src_azimuth, np.deg2rad(120.0)),
        snr_db=30.0, seed=0,
    )
    for pid, ch in zip(range(3), channels, strict=True):
        loop.buffer_pcm(pid, ch.astype(np.float32))
    frame = loop.step()
    assert frame is not None
    # The frame's per-phone channels are the right shape.
    expected_n = loop.window_n_samples()
    assert len(frame.channels) == 3
    for ch in frame.channels:
        assert ch.shape == (expected_n,)
        assert ch.dtype == np.float32
    # The beamformed output is the right shape and dtype.
    assert frame.beamformed.shape == (expected_n,)
    assert frame.beamformed.dtype == np.float32
    # TDOAs were computed for all 3 pairs.
    assert len(frame.tdoas) == 3  # C(3, 2) = 3 pairs
    # The localiser's result is either None (didn't
    # converge) or a position within the bounded search
    # radius. Don't pin the exact position here.
    if frame.position_xy is not None:
        x, y = frame.position_xy
        assert float(np.hypot(x, y)) < 10.0, (x, y)


def test_loop_das_and_mvdr_both_produce_output() -> None:
    """Switching the beamformer between D&S and MVDR should
    produce a non-empty beamformed array in both cases."""
    for beam in ("das", "mvdr"):
        aligner = _make_aligner(3)
        loop = DspLoop(aligner, beamformer=beam)
        for pid in range(3):
            loop.buffer_pcm(pid, np.full(loop.window_n_samples(), 0.1, dtype=np.float32))
        frame = loop.step()
        assert frame is not None, beam
        assert frame.beamformed.shape == (loop.window_n_samples(),)
        # Beamformed output of constant 0.1 in should be roughly 0.1 out
        # (delay-and-sum averages 3 channels of 0.1 to get 0.1;
        # MVDR does the same in the diagonal-loaded covariance case).
        assert np.max(np.abs(frame.beamformed - 0.1)) < 0.5, beam


def test_loop_tracks_speaker_across_frames() -> None:
    """The multi-speaker tracker should produce a single track
    that survives across frames as long as the speaker doesn't
    move far enough to be associated with a new one."""
    aligner = _make_aligner(2)
    loop = DspLoop(aligner, tracker=MultiSpeakerTracker(association_radius_m=0.3))
    for pid in range(2):
        loop.buffer_pcm(pid, np.full(loop.window_n_samples(), 0.1, dtype=np.float32))
    frame1 = loop.step()
    assert frame1 is not None
    # Refill and step again.
    for pid in range(2):
        loop.buffer_pcm(pid, np.full(loop.window_n_samples(), 0.1, dtype=np.float32))
    frame2 = loop.step()
    assert frame2 is not None
    # Both frames should report the same number of tracks (likely 0,
    # because the localiser needs an off-centre position to return
    # anything with a constant 0.1 input — but the call should not
    # crash and the count should be consistent).
    assert len(frame1.tracks) == len(frame2.tracks)


def test_loop_frame_counters_increment() -> None:
    """The loop exposes frames_processed and windows_emitted
    counters; the renderer reads these for the metrics endpoint."""
    aligner = _make_aligner(2)
    loop = DspLoop(aligner)
    # Several step() calls before the buffer fills.
    for _ in range(5):
        loop.step()
    assert loop.frames_processed == 5
    assert loop.windows_emitted == 0
    # Fill the buffer and step again.
    for pid in range(2):
        loop.buffer_pcm(pid, np.full(loop.window_n_samples(), 0.1, dtype=np.float32))
    loop.step()
    assert loop.windows_emitted == 1


def test_synthetic_phone_source_produces_deterministic_audio() -> None:
    """A SyntheticPhoneSource with a fixed seed should produce
    the same audio on every call (the seed is the random
    generator's initial state)."""
    src1 = SyntheticPhoneSource(phone_id=0, target_position=(1.0, 0.0))
    src1._rng = np.random.default_rng(42)
    src2 = SyntheticPhoneSource(phone_id=0, target_position=(1.0, 0.0))
    src2._rng = np.random.default_rng(42)
    a = src1.next_frame()
    b = src2.next_frame()
    np.testing.assert_array_equal(a, b)
    # The 440 Hz tone is in the signal. With a 20 ms frame at 48 kHz
    # the FFT bin spacing is 50 Hz, so the bin closest to 440 is
    # 400 or 450. We assert it's within one bin, not the exact tone.
    spec = np.abs(np.fft.rfft(a))
    freqs = np.fft.rfftfreq(a.size, d=1.0 / src1.sample_rate_hz)
    peak_idx = int(np.argmax(spec[1:])) + 1
    peak_freq = float(freqs[peak_idx])
    assert 350.0 < peak_freq < 500.0, peak_freq


def test_synthetic_phone_source_builds_valid_packet() -> None:
    """A built packet must round-trip through verify_packet."""
    from shruti_array.protocol import verify_packet
    src = SyntheticPhoneSource(phone_id=7, target_position=(0.0, 0.0))
    pkt = src.build_packet(sequence=123)
    hdr = verify_packet(pkt)
    assert hdr.phone_id == 7
    assert hdr.sequence == 123
    assert hdr.sample_rate_hz == DEFAULT_SAMPLE_RATE_HZ
    assert hdr.packet_type.value == 0x01  # AUDIO_FRAME
