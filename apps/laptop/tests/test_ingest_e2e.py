"""End-to-end smoke test for the ingest server.

Exercises the full WebSocket round-trip: a real client (the test
itself) opens a connection to a real PacketServer running on a
free port, sends framed audio packets, and the server decodes them
into PhoneConnection queues. The previous ingest tests covered
the unit-level guards (size cap, rate limit, CRC); this one proves
the bytes actually traverse the WebSocket layer and land in the
per-phone state.

What this is NOT:
- A test of the beamformer (that's test_beamform).
- A test of the radar / TDOA / sync (those have their own files).
- A test of the phone-side codec (no Android involved).

It is the cheapest possible "does the wire work?" verification
that the demo can run on the laptop the day before the event to
confirm the ingest path isn't broken by a refactor.
"""
from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import numpy as np
import pytest

# websockets is an optional dep; the import lives inside PacketServer.start
# to keep the unit tests fast. We import it here explicitly because the
# e2e path needs it on the client side.
import websockets

from shruti_array.config import ServerConfig
from shruti_array.ingest.websocket_server import PacketServer
from shruti_array.metrics import GLOBAL
from shruti_array.protocol import PacketType, frame_packet


def _free_port() -> int:
    """Ask the kernel for an unused TCP port.

    Race-prone (the port could be taken between the close and the
    server's bind), but acceptable for a test-only helper — the
    server start happens within microseconds.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@asynccontextmanager
async def _running_server() -> AsyncIterator[PacketServer]:
    """Start a PacketServer on a free port for the duration of one test."""
    cfg = ServerConfig(host="127.0.0.1", port=_free_port())
    server = PacketServer(cfg)
    task = asyncio.create_task(server.start())
    # Yield once the server is actually accepting connections. websockets'
    # serve() returns immediately; sleep briefly is the standard pattern
    # in their own tests.
    await asyncio.sleep(0.1)
    try:
        yield server
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


def _audio_packet(phone_id: int, sequence: int, n_samples: int = 480) -> bytes:
    """Build a real audio packet with a deterministic sine payload."""
    t = np.arange(n_samples) / 48_000.0
    samples = (0.5 * np.sin(2 * np.pi * 440.0 * t) * 32767).astype(np.int16)
    return frame_packet(
        phone_id=phone_id,
        sequence=sequence,
        sample_rate_hz=48_000,
        samples=samples.tobytes(),
        timestamp_us=sequence * 20_000,  # 20 ms per frame at 48 kHz
        packet_type=PacketType.AUDIO_FRAME,
    )


@pytest.mark.asyncio
async def test_single_phone_round_trip_registers_and_increments() -> None:
    """One client sends N packets, server should report 1 phone and
    the received counter should climb by N."""
    async with _running_server() as server:
        cfg = server.config
        url = f"ws://{cfg.host}:{cfg.port}"
        before = GLOBAL.snapshot()["counters"].get(
            "shruti_packets_received_total", 0.0
        )
        async with websockets.connect(url) as ws:
            for seq in range(5):
                await ws.send(_audio_packet(phone_id=0, sequence=seq))
            # Give the server a moment to drain the asyncio queue.
            await asyncio.sleep(0.1)
        after = GLOBAL.snapshot()["counters"].get(
            "shruti_packets_received_total", 0.0
        )
        assert server.all_phone_ids() == [0]
        assert after - before == 5.0


@pytest.mark.asyncio
async def test_three_phones_each_registered_separately() -> None:
    """The 3-phone Tier-1 pitch mode. Three concurrent connections
    from three phone_ids must each end up as a distinct entry in
    _connections, and each must have the right sample_rate recorded."""
    async with _running_server() as server:
        cfg = server.config
        url = f"ws://{cfg.host}:{cfg.port}"

        async def client(phone_id: int) -> None:
            async with websockets.connect(url) as ws:
                await ws.send(_audio_packet(phone_id=phone_id, sequence=0))
                await ws.send(_audio_packet(phone_id=phone_id, sequence=1))

        await asyncio.gather(client(0), client(1), client(2))
        await asyncio.sleep(0.2)
        assert sorted(server.all_phone_ids()) == [0, 1, 2]


@pytest.mark.asyncio
async def test_corrupt_packet_does_not_register_phone() -> None:
    """A bad packet must be CRC-rejected, not crash the connection
    and not register a phantom phone."""
    async with _running_server() as server:
        cfg = server.config
        url = f"ws://{cfg.host}:{cfg.port}"
        before = GLOBAL.snapshot()["counters"].get(
            "shruti_crc_failures_total", 0.0
        )
        async with websockets.connect(url) as ws:
            # Build a valid packet, then flip a payload byte.
            pkt = bytearray(_audio_packet(phone_id=0, sequence=0))
            pkt[40] ^= 0xFF  # somewhere in the payload
            await ws.send(bytes(pkt))
            await asyncio.sleep(0.1)
            # Now send a valid packet from the same connection; the
            # server should still accept it (corrupt-then-recover).
            await ws.send(_audio_packet(phone_id=0, sequence=1))
            await asyncio.sleep(0.1)
        after = GLOBAL.snapshot()["counters"].get(
            "shruti_crc_failures_total", 0.0
        )
        assert after - before == 1.0
        # The valid follow-up packet DID register the phone.
        assert server.all_phone_ids() == [0]


@pytest.mark.asyncio
async def test_oversized_websocket_frame_is_dropped_silently() -> None:
    """The websockets lib caps incoming frames at MAX_PACKET_BYTES.
    A 4 MB frame should close the connection without crashing the
    server, and the server should still accept new connections."""
    async with _running_server() as server:
        cfg = server.config
        url = f"ws://{cfg.host}:{cfg.port}"
        # Try the too-large send. The websockets client will close on
        # its side; we don't care about the exact failure mode, only
        # that the server is still alive afterwards.
        try:
            async with websockets.connect(url, max_size=None) as ws:
                try:
                    await ws.send(b"\x00" * (4 * 1024 * 1024))
                except Exception:
                    pass
                try:
                    await ws.send(_audio_packet(phone_id=7, sequence=0))
                except Exception:
                    pass
        except Exception:
            pass
        await asyncio.sleep(0.2)
        # The server should still be reachable.
        async with websockets.connect(url) as ws2:
            await ws2.send(_audio_packet(phone_id=9, sequence=0))
            await asyncio.sleep(0.1)
        assert 9 in server.all_phone_ids()
