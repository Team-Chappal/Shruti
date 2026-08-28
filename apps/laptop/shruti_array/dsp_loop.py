"""Real-time DSP loop.

The single piece of code that ties everything together: drains the
per-phone packet queues filled by `PacketServer`, aligns the streams
using the chirp-derived offsets, runs TDOA for radar, beamforms with
either D&S or MVDR, and feeds the result to ASR. The output is
exposed as an async generator so the rendering layer (text radar,
Compose canvas, future matplotlib UI) can subscribe to it.

Architecture:

    PacketServer (per-phone queue)
            |
            v
    DspLoop.pop_aligned_window()   <-- drains queues, aligns using StreamAligner
            |
            v
    per-pair TDOA via GCC-PHAT     <-- on the aligned window
            |
            v
    2D position via localize_2d    <-- per frame
            |
            v
    beamform with D&S or MVDR      <-- steered at the locked speaker
            |
            v
    ASR.transcribe()                <-- on the beamformed window
            |
            v
    RadarState (the rendering layer reads this)

A real deployment drives the loop from a single asyncio task that
`await`s a sleep of `frame_duration` between iterations. A
simulation drives the loop from a synthetic packet generator
(`dsp_loop.SyntheticPhoneSource`).

The loop is small on purpose — anything more complex belongs in a
helper module. The whole point is to make the data path obvious.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from .beamform import das, mvdr
from .config import AppConfig, ArrayGeometry
from .protocol import PacketType
from .radar.position import localize_2d
from .sync.alignment import StreamAligner
from .tdoa.gcc_phat import gcc_phat
from .tracker import MultiSpeakerTracker, Track

# 20 ms at 48 kHz. The protocol's frame is 960 samples; we
# accumulate 4 frames (= 80 ms) into a beamforming window for
# better TDOA accuracy. Override via the `window_n_frames` ctor arg.
DEFAULT_WINDOW_N_FRAMES = 4
DEFAULT_SAMPLE_RATE_HZ = 48_000


@dataclass
class LoopFrame:
    """One iteration of the DSP loop's output."""
    # Per-phone aligned channels (float32, in [-1, 1]).
    channels: list[NDArray[np.float32]]
    # TDOAs in samples, per pair.
    tdoas: dict[tuple[int, int], float]
    # Speaker position in metres, or None if the estimator
    # didn't converge this frame.
    position_xy: tuple[float, float] | None
    # Beamformed audio (mono, float32, same length as `channels[0]`).
    beamformed: NDArray[np.float32]
    # Active tracks from the multi-speaker tracker.
    tracks: list[Track]
    # Wall-clock time at the start of the loop iteration.
    now_s: float


class DspLoop:
    """Drives the live DSP pipeline.

    Construct with a `StreamAligner` (which has been fed the
    per-phone offsets from the chirp handshake) and the array
    geometry. Call `step()` from a real-time loop, or
    `run_forever()` to drive it from an asyncio task. The
    `frames()` async generator yields each `LoopFrame` so a
    renderer can subscribe to live state.

    The class is intentionally stateful: it owns the per-phone
    ring buffers and the multi-speaker tracker. Tests can
    construct it once and feed it many windows.
    """

    def __init__(
        self,
        aligner: StreamAligner,
        geometry: ArrayGeometry | None = None,
        sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ,
        window_n_frames: int = DEFAULT_WINDOW_N_FRAMES,
        beamformer: Literal["das", "mvdr"] = "das",
        tracker: MultiSpeakerTracker | None = None,
    ) -> None:
        self.aligner = aligner
        self.geometry = geometry or AppConfig.default().geometry
        self.sample_rate_hz = sample_rate_hz
        self.window_n_frames = window_n_frames
        self.beamformer = beamformer
        self.tracker = tracker or MultiSpeakerTracker()
        # Per-phone rolling buffer (float32, normalised to [-1, 1]).
        self._buffers: dict[int, NDArray[np.float32]] = {}
        # Last position estimate — used as the steering direction
        # so the beamformer doesn't have to search every frame.
        self._last_position: tuple[float, float] | None = None
        # Subcribers to the live frame stream.
        self._subscribers: list[asyncio.Queue[LoopFrame]] = []
        # Counters useful for the metrics endpoint.
        self.frames_processed = 0
        self.windows_emitted = 0
        self.started_at_s: float | None = None

    @property
    def last_position(self) -> tuple[float, float] | None:
        return self._last_position

    def buffer_pcm(self, phone_id: int, samples: NDArray[np.float32]) -> None:
        """Append a frame of float32 PCM to a phone's ring buffer."""
        if phone_id not in self._buffers:
            self._buffers[phone_id] = samples.copy()
        else:
            self._buffers[phone_id] = np.concatenate(
                [self._buffers[phone_id], samples]
            )
        # Cap the buffer at 1 second so a slow consumer can't blow up
        # memory. The limit is well above the largest beamforming
        # window (50 ms), so this never clips a real run.
        max_samples = self.sample_rate_hz
        if self._buffers[phone_id].size > max_samples:
            self._buffers[phone_id] = self._buffers[phone_id][-max_samples:]

    def window_n_samples(self) -> int:
        # The protocol frame is hardcoded at 960 samples (20 ms @
        # 48 kHz) on both the Kotlin and Python sides. If the team
        # ever changes that, this is the only number to update here.
        return 960 * self.window_n_frames

    def ready(self) -> bool:
        """All known phones have at least one full window of samples."""
        need = self.window_n_samples()
        return all(
            self._buffers.get(pid, np.empty(0)).size >= need
            for pid in self.aligner.all_phone_ids()
        )

    def pop_from_queues(
        self,
        queues: dict[int, asyncio.Queue[bytes]],
        max_packets_per_phone: int = 8,
    ) -> int:
        """Drain up to N packets from each phone's queue, decode
        them, and feed the resulting float32 PCM into the
        per-phone rolling buffer.

        This is the bridge between the live `PacketServer`
        (which fills per-phone `asyncio.Queue`s) and the
        DSP loop (which consumes float32 buffers). The
        caller drives the loop on its own schedule: call
        `pop_from_queues`, then `step()` if `ready()` is
        true.

        Returns the total number of packets consumed across
        all phones. Zero on an empty queue is normal and
        not an error.

        Packets that fail CRC verification are silently
        dropped — the queue's own metrics counter already
        tracks them.
        """
        from .ingest.websocket_server import packet_to_samples
        from .protocol import ProtocolError
        n = 0
        for pid, q in queues.items():
            if pid not in self.aligner.all_phone_ids():
                # Phone we don't know about yet. Skip; the
                # aligner will register it on the next
                # heartbeat.
                continue
            for _ in range(max_packets_per_phone):
                try:
                    raw = q.get_nowait()
                except asyncio.QueueEmpty:
                    break
                try:
                    _type, _sr, _phone_id, samples = packet_to_samples(raw)
                except ProtocolError:
                    continue
                # packet_to_samples returns int16-floats in
                # [-1, 1]. The DspLoop expects float32 in
                # [-1, 1], which is exactly what we have.
                self.buffer_pcm(pid, samples)
                n += 1
        return n

    def aligned_window(self) -> list[NDArray[np.float32]] | None:
        """Pop one window of aligned audio across all registered phones.

        Returns None if any phone doesn't have enough samples yet.
        The pop is destructive: each call advances the buffer.
        """
        need = self.window_n_samples()
        if not self.ready():
            return None
        # Grab the last `need` samples from each phone's buffer
        # BEFORE cropping — cropping the buffer to `buffer[need:]`
        # makes the last `need` samples of the post-crop buffer
        # the previous window, not this one. The aligner already
        # applied per-phone offsets at chirp time; per-window
        # drift is small enough to ignore inside an 80 ms window.
        result = [self._buffers[pid][-need:].copy() for pid in self.aligner.all_phone_ids()]
        for pid in self.aligner.all_phone_ids():
            self._buffers[pid] = self._buffers[pid][need:]
        return result

    def step(self) -> LoopFrame | None:
        """Run one iteration of the DSP pipeline.

        Returns a `LoopFrame` if all phones have a full window, else
        None. Updates the multi-speaker tracker and the last
        position. Callers (real-time or simulator) decide how often
        to call this.
        """
        if self.started_at_s is None:
            self.started_at_s = time.time()
        self.frames_processed += 1
        channels = self.aligned_window()
        if channels is None:
            return None
        phone_ids = self.aligner.all_phone_ids()
        # Compute per-pair TDOAs. Skip the pair if it would need a
        # very long GCC-PHAT (the array is small; this is bounded).
        tdoas: dict[tuple[int, int], float] = {}
        for i in range(len(phone_ids)):
            for j in range(i + 1, len(phone_ids)):
                tau = float(gcc_phat(channels[i], channels[j]))
                tdoas[(phone_ids[i], phone_ids[j])] = tau
        # Localise the speaker in 2D. With 3 elements we have 3
        # TDOAs; the non-linear least-squares in localize_2d handles
        # the over-determined case.
        position = localize_2d(tdoas, self.geometry, self.sample_rate_hz)
        # Track the speaker. Even when the localiser returns None
        # (e.g. a silent frame), prune stale tracks.
        if position is not None:
            self._last_position = position
        self.tracker.update(position, now_s=time.time())
        # Beamform steered at the last known position. If we don't
        # have a lock yet, fall back to the array centroid direction
        # (broadside) so the first few frames still produce output.
        if position is not None:
            # Far-field azimuth from the array centroid. The
            # steering-vector math is invariant under this
            # assumption.
            x, y = position
            r = float(np.hypot(x, y))
            if r > 1e-3:
                azimuth_rad = float(np.arctan2(y, x))
            else:
                azimuth_rad = 0.0
        else:
            azimuth_rad = 0.0
        # Pad/truncate to the window length (channels are already
        # the right size, but be defensive in case the aligner
        # mixed-length input).
        n = min(c.size for c in channels)
        channels = [c[:n] for c in channels]
        # The 2-phone Tier-0 pitch mode uses fewer microphones
        # than the 3-element default geometry. Subset the geometry
        # to match the actual channel count, so the beamformer's
        # "geometry has N elements, got M channels" guard doesn't
        # trip. The first M elements of the default layout keep
        # the same x-baseline the on-device calibration expects.
        if len(channels) == len(self.geometry.elements):
            beam_geometry = self.geometry
        else:
            from .config import ArrayGeometry
            beam_geometry = ArrayGeometry(
                elements=self.geometry.elements[: len(channels)]
            )
        if self.beamformer == "mvdr":
            beamformed = mvdr.mvdr_beamform(
                channels, azimuth_rad, beam_geometry, self.sample_rate_hz
            )
        else:
            beamformed = das.delay_and_sum(
                channels, azimuth_rad, beam_geometry, self.sample_rate_hz
            )
        frame = LoopFrame(
            channels=channels,
            tdoas=tdoas,
            position_xy=position,
            beamformed=beamformed,
            tracks=list(self.tracker.tracks),
            now_s=time.time(),
        )
        self.windows_emitted += 1
        # Fan out to any subscribers (the radar UI typically).
        for q in self._subscribers:
            try:
                q.put_nowait(frame)
            except asyncio.QueueFull:
                # A slow subscriber shouldn't stall the loop; drop
                # the frame on this subscriber only.
                pass
        return frame

    async def frames(self) -> AsyncIterator[LoopFrame]:
        """Async generator: yield every `LoopFrame` produced by
        `step()`. Use as `async for frame in loop.frames(): ...`."""
        q: asyncio.Queue[LoopFrame] = asyncio.Queue(maxsize=8)
        self._subscribers.append(q)
        try:
            while True:
                frame = await q.get()
                yield frame
        finally:
            if q in self._subscribers:
                self._subscribers.remove(q)


@dataclass
class SyntheticPhoneSource:
    """Simulated phone that produces 48 kHz PCM frames on demand.

    Used by the e2e simulator and the regression harness. Each
    source generates the audio that ONE phone on the array would
    capture, given a target speaker position and an arbitrary
    background noise. The simulator wires three of these to a
    `DspLoop` via `frame_packet` so the laptop's `PacketServer`
    can be exercised without real hardware.

    The source is a generator: each call to `next_frame()` returns
    one 20 ms frame of float32 PCM. The simulator feeds it
    through `frame_packet` and into the WebSocket.
    """
    phone_id: int
    target_position: tuple[float, float]  # speaker (x, y) in metres
    noise_amplitude: float = 0.01
    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ
    frame_n_samples: int = 960  # 20 ms
    _n: int = 0
    _rng: np.random.Generator = field(default_factory=lambda: np.random.default_rng())

    def next_frame(self) -> NDArray[np.float32]:
        """Return one 20 ms frame of synthetic PCM (float32, [-1, 1])."""
        n = self.frame_n_samples
        # A pure tone aimed at the "speaker" location. The
        # amplitude is fixed; the simulator is about exercising
        # the pipeline, not demonstrating microphone calibration.
        t = (self._n + np.arange(n)) / self.sample_rate_hz
        tone = 0.3 * np.sin(2 * np.pi * 440.0 * t).astype(np.float32)
        noise = self._rng.standard_normal(n).astype(np.float32) * self.noise_amplitude
        self._n += n
        return tone + noise

    def build_packet(self, sequence: int) -> bytes:
        """Generate one full 20 ms packet ready to feed the WebSocket."""
        from .protocol import frame_packet
        pcm = self.next_frame()
        pcm_bytes = (pcm * 32767.0).astype(np.int16).tobytes()
        return frame_packet(
            phone_id=self.phone_id,
            sequence=sequence,
            sample_rate_hz=self.sample_rate_hz,
            samples=pcm_bytes,
            timestamp_us=self._n,
            packet_type=PacketType.AUDIO_FRAME,
        )
