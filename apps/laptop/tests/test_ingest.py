"""Tests for the packet size cap and rate limiter in the ingest server.

These exercise the cheap pre-checks before CRC, so they don't need
a real WebSocket. The full WebSocket round-trip is exercised in the
end-to-end smoke test (a separate file would be nice; the demo's
time budget doesn't allow for it now).
"""
from __future__ import annotations

import asyncio

import numpy as np
import pytest

from shruti_array.ingest.websocket_server import (
    MAX_PACKET_BYTES,
    PacketServer,
    PhoneConnection,
)
from shruti_array.metrics import GLOBAL
from shruti_array.protocol import (
    HEADER_SIZE,
    MAX_PAYLOAD_SAMPLES,
    PacketType,
    frame_packet,
)


def test_max_packet_bytes_is_consistent_with_protocol() -> None:
    expected = HEADER_SIZE + MAX_PAYLOAD_SAMPLES * 2 + 4
    assert MAX_PACKET_BYTES == expected


def _phone_connection() -> PhoneConnection:
    return PhoneConnection(
        phone_id=0,
        sample_rate_hz=48_000,
        queue=asyncio.Queue(maxsize=8),
        remote=("127.0.0.1", 0),
        connected_at_s=0.0,
    )


def test_rate_limiter_trips_on_burst() -> None:
    conn = _phone_connection()
    # 401 packets within the window -> over the 400 cap.
    for i in range(401):
        conn.note_packet(float(i) * 0.001)
    assert conn.over_rate_limit() is True
    # 399 packets in the window -> not over.
    conn2 = _phone_connection()
    for i in range(399):
        conn2.note_packet(float(i) * 0.001)
    assert conn2.over_rate_limit() is False


def test_rate_limiter_window_slides() -> None:
    conn = _phone_connection()
    # 200 packets at t=0..0.199 (all within 2s window)
    for i in range(200):
        conn.note_packet(i * 0.001)
    # 50 more at t=10 (well outside window; old ones should be pruned)
    for i in range(50):
        conn.note_packet(10.0 + i * 0.001)
    assert conn.over_rate_limit() is False
    assert len(conn.packet_times) == 50


@pytest.mark.asyncio
async def test_oversized_packet_is_rejected_before_crc() -> None:
    server = PacketServer()
    metrics_before = GLOBAL.snapshot()
    # A 4 MB garbage packet must be rejected without ever calling CRC.
    huge = b"\x00" * (4 * 1024 * 1024)
    await server._on_packet(("127.0.0.1", 0), huge, on_connect=None)
    metrics_after = GLOBAL.snapshot()
    delta_rejected = (
        metrics_after["counters"].get("shruti_packets_rejected_total", 0.0)
        - metrics_before["counters"].get("shruti_packets_rejected_total", 0.0)
    )
    assert delta_rejected == 1
    # And no phone was registered.
    assert server.all_phone_ids() == []


@pytest.mark.asyncio
async def test_valid_packet_registers_phone() -> None:
    server = PacketServer()
    samples = (np.zeros(480, dtype=np.int16)).tobytes()
    pkt = frame_packet(
        phone_id=2,
        sequence=1,
        sample_rate_hz=48_000,
        samples=samples,
        timestamp_us=1_000_000,
        packet_type=PacketType.AUDIO_FRAME,
    )
    await server._on_packet(("127.0.0.1", 0), pkt, on_connect=None)
    assert 2 in server.all_phone_ids()


@pytest.mark.asyncio
async def test_corrupt_packet_is_counted_as_crc_failure() -> None:
    server = PacketServer()
    samples = (np.zeros(32, dtype=np.int16)).tobytes()
    pkt = frame_packet(
        phone_id=0, sequence=1, sample_rate_hz=48_000,
        samples=samples, timestamp_us=0,
    )
    # Flip a byte in the payload.
    bad = bytearray(pkt)
    bad[HEADER_SIZE + 4] ^= 0xFF
    before = GLOBAL.snapshot()["counters"].get("shruti_crc_failures_total", 0.0)
    await server._on_packet(("127.0.0.1", 0), bytes(bad), on_connect=None)
    after = GLOBAL.snapshot()["counters"].get("shruti_crc_failures_total", 0.0)
    assert after - before == 1.0
