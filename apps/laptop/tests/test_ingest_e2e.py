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
async def _running_server() -> AsyncIterator[tuple[PacketServer, ServerConfig]]:
    """Start a PacketServer on a free port for the duration of one test.
    Yields the server and its config so tests can construct the WS URL.
    """
    cfg = ServerConfig(host="127.0.0.1", port=_free_port())
    server = PacketServer(cfg)
    task = asyncio.create_task(server.start())
    # Yield once the server is actually accepting connections. websockets'
    # serve() returns immediately; sleep briefly is the standard pattern
    # in their own tests.
    await asyncio.sleep(0.1)
    try:
        yield server, cfg
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
    async with _running_server() as (server, cfg):
        url = f"ws://{cfg.host}:{cfg.port}"
        before = GLOBAL.snapshot()["counters"].get(
            "shruti_packets_received_total", 0.0
        )
        server_state: dict[str, list[int]] = {"snapshot": []}
        async with websockets.connect(url) as ws:
            for seq in range(5):
                await ws.send(_audio_packet(phone_id=0, sequence=seq))
            # Give the server a moment to drain the asyncio queue.
            await asyncio.sleep(0.1)
            server_state["snapshot"] = list(server.all_phone_ids())
        after = GLOBAL.snapshot()["counters"].get(
            "shruti_packets_received_total", 0.0
        )
        assert server_state["snapshot"] == [0]
        assert after - before == 5.0


@pytest.mark.asyncio
async def test_three_phones_each_registered_separately() -> None:
    """The 3-phone Tier-1 pitch mode. Three concurrent connections
    from three phone_ids must each end up as a distinct entry in
    _connections, and each must have the right sample_rate recorded.

    T11 changed the test mechanics: the server's disconnect
    handler now removes a phone from _connections when its
    WebSocket closes, so we have to snapshot the server's view
    *while* all three connections are still alive rather than
    after the `async with` contexts have exited.

    Implementation note: this is the fourth revision of the
    test. The three earlier versions (shared-dict snapshot,
    per-client snapshot with fixed sleep, per-client snapshot
    with server-state polling, and barrier-only synchronisation)
    each closed one race but exposed another:

    1. Shared dict: last writer wins. The last client to write
       was often the one whose connection was the only one
       still alive.
    2. Fixed sleep: client could read before the server had
       processed its own registration, or after another
       client's disconnect had been processed.
    3. Server-state polling: timing-dependent — clients 0/1
       could release their poll (see all 3 registered) while
       client 2 was still mid-poll and read its snapshot alone
       (with phones 0/1 already disconnected by the server).
    4. Barrier-only: barrier released before the server had
       processed any registrations, so every client read an
       empty `_connections`.

    The correct fix combines barrier + server-state poll:
    each client polls `len(server.all_phone_ids()) == 3`
    inside its `async with` (proving all 3 phones are
    registered on the server) and *then* arrives at the
    barrier. After the barrier releases, every client
    reads the snapshot while all 3 connections are still
    open (because the barrier is awaited inside the
    `async with`).

    The poll timeout is 5 s, generous enough for any
    reasonable CI runner. If a client times out, the
    assertion fires with the actual `_connections` state
    so the team can diagnose.

    This was a real CI flake surfaced by T15: 3.10/3.12
    (fast runners) saw `[1, 2]`, 3.11 saw `[2]`, and
    the barrier-only version saw `[]`. The combined
    barrier + poll closes every race in the snapshot
    sequence.
    """
    async with _running_server() as (server, cfg):
        url = f"ws://{cfg.host}:{cfg.port}"

        # Coordination barrier: all 3 clients arrive here
        # *after* the server has registered all 3 phones.
        # Python 3.10-compatible (asyncio.Barrier is 3.11+).
        arrived = 0
        all_arrived = asyncio.Event()

        async def arrive_and_wait(n_clients: int) -> None:
            nonlocal arrived
            arrived += 1
            if arrived == n_clients:
                all_arrived.set()
            await all_arrived.wait()

        # Per-client snapshot list. After the barrier, every
        # client reads the server's view while all 3 are alive.
        snapshots: list[list[int]] = []

        async def client(phone_id: int) -> None:
            async with websockets.connect(url) as ws:
                await ws.send(_audio_packet(phone_id=phone_id, sequence=0))
                await ws.send(_audio_packet(phone_id=phone_id, sequence=1))
                # Wait for the server to register all 3 phones.
                # This proves the server has processed at least
                # the first packet from each client, so the
                # SHRUTI-level registration is complete (not
                # just the WebSocket-level connection).
                deadline = asyncio.get_event_loop().time() + 5.0
                while (
                    len(server.all_phone_ids()) < 3
                    and asyncio.get_event_loop().time() < deadline
                ):
                    await asyncio.sleep(0.01)
                # Rendezvous with the other 2 clients before
                # reading. Inside the `async with`, so all 3
                # connections are still open on the server.
                # By the time we get here, the server has
                # registered all 3 phones; the barrier just
                # ensures all 3 clients read the snapshot at
                # the same instant, before any `async with`
                # can exit and trigger a disconnect handler.
                await arrive_and_wait(3)
                snapshots.append(sorted(server.all_phone_ids()))

        await asyncio.gather(client(0), client(1), client(2))
        # All 3 clients should have seen all 3 phones alive
        # at the moment of the rendezvous. If any client saw
        # fewer than 3, the barrier or poll didn't work as
        # expected — fail loudly so the team notices.
        for i, snap in enumerate(snapshots):
            assert snap == [0, 1, 2], (
                f"client {i} saw {snap}, expected [0, 1, 2]; "
                f"all 3 snapshots = {snapshots}"
            )


@pytest.mark.asyncio
async def test_corrupt_packet_does_not_register_phone() -> None:
    """A bad packet must be CRC-rejected, not crash the connection
    and not register a phantom phone."""
    async with _running_server() as (server, cfg):
        url = f"ws://{cfg.host}:{cfg.port}"
        before = GLOBAL.snapshot()["counters"].get(
            "shruti_crc_failures_total", 0.0
        )
        server_state: dict[str, list[int]] = {"snapshot_after": []}
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
            server_state["snapshot_after"] = list(server.all_phone_ids())
        after = GLOBAL.snapshot()["counters"].get(
            "shruti_crc_failures_total", 0.0
        )
        assert after - before == 1.0
        # The valid follow-up packet DID register the phone (T11's
        # disconnect handler hasn't fired yet because the WS is
        # still open inside this block).
        assert server_state["snapshot_after"] == [0]


@pytest.mark.asyncio
async def test_oversized_websocket_frame_is_dropped_silently() -> None:
    """The websockets lib caps incoming frames at MAX_PACKET_BYTES.
    A 4 MB frame should close the connection without crashing the
    server, and the server should still accept new connections."""
    async with _running_server() as (server, cfg):
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
        server_state: dict[str, list[int]] = {"snapshot": []}
        async with websockets.connect(url) as ws2:
            await ws2.send(_audio_packet(phone_id=9, sequence=0))
            await asyncio.sleep(0.1)
            server_state["snapshot"] = list(server.all_phone_ids())
        assert 9 in server_state["snapshot"]
