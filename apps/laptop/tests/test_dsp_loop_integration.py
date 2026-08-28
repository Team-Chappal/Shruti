"""End-to-end integration test: real WebSocket -> DspLoop -> beamformed audio.

The previous e2e tests (test_ingest_e2e.py) verified that
the WebSocket server accepts packets and registers phones.
The DspLoop tests (test_dsp_loop.py) verified that the
DSP pipeline runs. This test wires the two together: spin
up a real PacketServer, connect a fake phone, push a bunch
of valid packets, drain the per-phone queue through
`DspLoop.pop_from_queues`, and confirm the DSP loop
produces a beamformed output.

This is the closest a CI test can get to the live demo
without the iQOO loaner fleet.
"""
from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import numpy as np
import pytest
import websockets

from shruti_array.config import AppConfig
from shruti_array.dsp_loop import DspLoop
from shruti_array.ingest.websocket_server import PacketServer
from shruti_array.protocol import (
    PacketType,
    frame_packet,
)
from shruti_array.sync.alignment import StreamAligner


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@asynccontextmanager
async def _running_server_with_queues() -> AsyncIterator[tuple]:
    """Start a PacketServer and return (server, queues_dict).

    The queues dict maps phone_id -> asyncio.Queue. The
    DspLoop will pull from these.
    """
    from shruti_array.config import ServerConfig
    cfg = ServerConfig(host="127.0.0.1", port=_free_port())
    server = PacketServer(cfg)
    task = asyncio.create_task(server.start())
    await asyncio.sleep(0.1)
    queues = {pid: conn.queue for pid, conn in server._connections.items()}
    try:
        yield server, queues
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


def _build_packet(phone_id: int, sequence: int, n_samples: int = 960) -> bytes:
    """Build a real wire-format audio packet with a
    deterministic sine payload."""
    sr = 48_000
    t = np.arange(n_samples) / sr
    # Same target signal on all "phones" so the TDOA is
    # near zero; the DSP loop should still produce output.
    pcm = (0.3 * np.sin(2 * np.pi * 440.0 * t + 0.01 * phone_id)).astype(np.float32)
    pcm_bytes = (pcm * 32767.0).astype(np.int16).tobytes()
    return frame_packet(
        phone_id=phone_id,
        sequence=sequence,
        sample_rate_hz=sr,
        samples=pcm_bytes,
        timestamp_us=sequence * 20_000,
        packet_type=PacketType.AUDIO_FRAME,
    )


@pytest.mark.asyncio
async def test_dsp_loop_drains_real_websocket_queue() -> None:
    """Connect a fake phone, push 8 valid packets, drain
    the per-phone queue through DspLoop.pop_from_queues,
    then call step() and confirm a LoopFrame is produced."""
    async with _running_server_with_queues() as (server, _queues):
        cfg = AppConfig.default()
        # Build the aligner the way the production code would
        # after the chirp handshake: register both phones.
        aligner = StreamAligner()
        for pid in (0, 1):
            aligner.register(phone_id=pid, sample_rate_hz=cfg.audio.sample_rate_hz)
        loop = DspLoop(aligner, geometry=cfg.geometry)
        # Wait for the phones to register after the first
        # packet arrives; for now, drive the loop manually.
        url = f"ws://{server.config.host}:{server.config.port}"
        async with websockets.connect(url) as ws:
            # Each phone sends 8 packets (= 4 windows of 960
            # samples each, 80 ms per window).
            for phone_id in (0, 1):
                for seq in range(8):
                    await ws.send(_build_packet(phone_id=phone_id, sequence=seq))
            await asyncio.sleep(0.2)
        # The server should now have 2 phones registered,
        # each with 8 packets queued.
        assert sorted(server.all_phone_ids()) == [0, 1]
        # Drain the per-phone queues through the DspLoop.
        queues = {pid: conn.queue for pid, conn in server._connections.items()}
        n_consumed = loop.pop_from_queues(queues, max_packets_per_phone=8)
        # 2 phones * 8 packets each = 16 packets consumed.
        assert n_consumed == 16
        # The buffer should now have 8 windows' worth of
        # samples per phone (= 8 * 960 = 7680 samples per
        # phone, capped at 1 second = 48000).
        for pid in (0, 1):
            assert loop._buffers[pid].size == 8 * 960  # noqa: SLF001
        # The DSP loop should be ready to step.
        assert loop.ready() is True
        # Run one iteration. We don't assert on the localiser
        # output (synthetic data is too quiet); we just
        # confirm a LoopFrame came out with the right shape.
        frame = loop.step()
        assert frame is not None
        assert len(frame.channels) == 2
        for ch in frame.channels:
            assert ch.shape == (loop.window_n_samples(),)
            assert ch.dtype == np.float32
        # The beamformed output should also be the right shape
        # and dtype.
        assert frame.beamformed.shape == (loop.window_n_samples(),)
        assert frame.beamformed.dtype == np.float32


@pytest.mark.asyncio
async def test_dsp_loop_handles_unknown_phone_id() -> None:
    """If the aligner doesn't know about a phone_id, packets
    for that phone should be skipped (not crash, not
    register). This guards against a malicious or
    misconfigured phone claiming an unexpected id."""
    async with _running_server_with_queues() as (server, _queues):
        cfg = AppConfig.default()
        aligner = StreamAligner()
        # Only register phone 0; phone 1 will be unknown.
        aligner.register(phone_id=0, sample_rate_hz=cfg.audio.sample_rate_hz)
        loop = DspLoop(aligner, geometry=cfg.geometry)
        url = f"ws://{server.config.host}:{server.config.port}"
        async with websockets.connect(url) as ws:
            for seq in range(4):
                await ws.send(_build_packet(phone_id=1, sequence=seq))
            await asyncio.sleep(0.1)
        # Phone 1 is registered with the server (because the
        # server accepts any phone_id), but NOT with the
        # aligner. pop_from_queues should skip it cleanly.
        queues = {pid: conn.queue for pid, conn in server._connections.items()}
        n_consumed = loop.pop_from_queues(queues, max_packets_per_phone=8)
        # 0 packets consumed (phone 1 is unknown to the
        # aligner).
        assert n_consumed == 0
        # Phone 0 was never sent, so its buffer is empty.
        assert loop._buffers.get(0, np.empty(0)).size == 0  # noqa: SLF001


@pytest.mark.asyncio
async def test_dsp_loop_drops_corrupt_packets() -> None:
    """A CRC-corrupted packet in the queue should be
    silently dropped, not crash the loop or affect the
    other phones' alignment."""
    async with _running_server_with_queues() as (server, _queues):
        cfg = AppConfig.default()
        aligner = StreamAligner()
        for pid in (0, 1):
            aligner.register(phone_id=pid, sample_rate_hz=cfg.audio.sample_rate_hz)
        loop = DspLoop(aligner, geometry=cfg.geometry)
        url = f"ws://{server.config.host}:{server.config.port}"
        async with websockets.connect(url) as ws:
            # Phone 0: 4 valid packets.
            for seq in range(4):
                await ws.send(_build_packet(phone_id=0, sequence=seq))
            # Phone 1: 1 valid packet, then 1 corrupt packet.
            await ws.send(_build_packet(phone_id=1, sequence=0))
            bad = bytearray(_build_packet(phone_id=1, sequence=1))
            bad[40] ^= 0xFF  # corrupt a byte in the payload
            await ws.send(bytes(bad))
            await asyncio.sleep(0.2)
        queues = {pid: conn.queue for pid, conn in server._connections.items()}
        # Drain. The corrupt packet is dropped silently.
        n_consumed = loop.pop_from_queues(queues, max_packets_per_phone=8)
        # 4 (phone 0) + 1 (phone 1, valid) = 5 consumed; the
        # corrupt one is dropped.
        assert n_consumed == 5
        # Phone 0's buffer should be 4 * 960 = 3840 samples.
        assert loop._buffers[0].size == 4 * 960  # noqa: SLF001
        # Phone 1's buffer should be 1 * 960 = 960 samples
        # (only the valid packet).
        assert loop._buffers[1].size == 1 * 960  # noqa: SLF001


@pytest.mark.asyncio
async def test_dsp_loop_handles_empty_queues() -> None:
    """pop_from_queues on empty queues should return 0 and
    not raise. This is the steady-state behaviour when the
    WebSocket is idle."""
    async with _running_server_with_queues() as (server, _queues):
        cfg = AppConfig.default()
        aligner = StreamAligner()
        for pid in (0, 1):
            aligner.register(phone_id=pid, sample_rate_hz=cfg.audio.sample_rate_hz)
        loop = DspLoop(aligner, geometry=cfg.geometry)
        # No packets sent; queues are empty.
        queues = {pid: conn.queue for pid, conn in server._connections.items()}
        n = loop.pop_from_queues(queues)
        assert n == 0
        # And the loop is not ready.
        assert loop.ready() is False
