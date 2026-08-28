"""WebSocket packet receiver.

Phones connect over WebSocket and stream binary frames in the
protocol defined by `shruti_array.protocol`. The receiver validates
every packet's CRC, enforces a per-packet size cap, applies a
per-phone rate limit, drops anything malformed, and feeds the rest
into a bounded per-phone ring buffer that the rest of the pipeline
drains.

A real deployment on the hackathon venue runs over Wi-Fi Direct
through the Office Kit bridge; the same code works over loopback
for testing and over any TCP/IP transport.

The HTTP /metrics endpoint lives in a separate process (see
`shruti_array.ingest.metrics_server`) on a different port, so the
WebSocket and HTTP transports stay cleanly separated.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray

from ..config import ServerConfig
from ..log import get_logger
from ..metrics import (
    ACTIVE_PHONES,
    BYTES_RECEIVED,
    CRC_FAILURES,
    DROPPED_FRAMES,
    PACKETS_DECODED,
    PACKETS_RECEIVED,
    PACKETS_REJECTED,
)
from ..metrics import (
    GLOBAL as METRICS,
)
from ..protocol import (
    CRC_SIZE,
    HEADER_SIZE,
    MAX_PAYLOAD_SAMPLES,
    PacketType,
    verify_packet,
)

log = get_logger(__name__)

# A packet carrying the maximum payload plus header + CRC. We refuse
# anything larger before even attempting to parse it, so a hostile
# phone can't tie us up in CRC computation on a 4 GB buffer.
MAX_PACKET_BYTES: int = HEADER_SIZE + MAX_PAYLOAD_SAMPLES * 2 + CRC_SIZE


# A simple sliding-window rate limiter. Phones are expected to send
# at most ~50 packets/second (one per 20 ms frame). Anything beyond
# 200/s for more than 2 seconds is treated as a runaway and we drop
# the packet. Tuned for a 3-phone demo; not production-grade.
_RATE_WINDOW_S: float = 2.0
_RATE_MAX_PACKETS: int = 400

ConnectionHandler = Callable[["PhoneConnection"], Coroutine[Any, Any, None]]


@dataclass
class PhoneConnection:
    phone_id: int
    sample_rate_hz: int
    queue: asyncio.Queue[bytes]  # raw, CRC-verified packets
    remote: tuple[str, int]
    connected_at_s: float
    packet_times: deque[float] = field(default_factory=deque)
    sequence: int = -1
    dropped_frames: int = 0

    def note_packet(self, now: float) -> None:
        self.packet_times.append(now)
        while self.packet_times and (now - self.packet_times[0]) > _RATE_WINDOW_S:
            self.packet_times.popleft()

    def over_rate_limit(self) -> bool:
        return len(self.packet_times) > _RATE_MAX_PACKETS


class PacketServer:
    """Async WebSocket server that accepts one connection per phone.

    Per-phone state is tracked in `_connections`. Slow consumers
    cause the oldest packet in the queue to be dropped, so a phone
    that suddenly stops responding (e.g., screen locked) doesn't
    stall the array.
    """

    def __init__(self, config: ServerConfig | None = None) -> None:
        self.config = config or ServerConfig()
        self._connections: dict[int, PhoneConnection] = {}
        self._lock = asyncio.Lock()

    async def start(self, on_connect: ConnectionHandler | None = None) -> None:
        """Start the WebSocket server. Blocks forever."""
        import websockets  # local import: optional at install

        log.info("listening on ws://%s:%d", self.config.host, self.config.port)
        # `max_size` is the websockets-library frame-size cap. It
        # must be >= MAX_PACKET_BYTES; any larger frame is closed
        # before we see the bytes.
        async with websockets.serve(
            self._handle_connection,
            self.config.host,
            self.config.port,
            max_size=MAX_PACKET_BYTES,
        ):
            await asyncio.Future()  # run forever

    async def _handle_connection(self, ws) -> None:
        remote = ws.remote_address
        try:
            async for raw in ws:
                await self._on_packet(remote, raw, on_connect=None)
        except Exception as e:  # noqa: BLE001
            log.warning("connection from %s closed: %s", remote, e)

    async def _on_packet(
        self,
        remote: tuple[str, int],
        raw: bytes,
        on_connect: ConnectionHandler | None,
    ) -> None:
        METRICS.inc(PACKETS_RECEIVED)
        METRICS.inc(BYTES_RECEIVED, len(raw))

        # Cheap pre-check before CRC: refuse anything obviously too
        # big or too small before we spend any CPU on it.
        if len(raw) > MAX_PACKET_BYTES or len(raw) < HEADER_SIZE + CRC_SIZE:
            METRICS.inc(PACKETS_REJECTED)
            log.warning("packet from %s rejected: bad size %d", remote, len(raw))
            return

        try:
            header = verify_packet(raw)
        except Exception as e:  # noqa: BLE001
            METRICS.inc(PACKETS_REJECTED)
            METRICS.inc(CRC_FAILURES)
            log.warning("malformed packet from %s: %s", remote, e)
            return

        phone_id = header.phone_id
        now = time.time()
        async with self._lock:
            conn = self._connections.get(phone_id)
            if conn is None:
                conn = PhoneConnection(
                    phone_id=phone_id,
                    sample_rate_hz=header.sample_rate_hz,
                    queue=asyncio.Queue(maxsize=64),
                    remote=remote,
                    connected_at_s=now,
                )
                self._connections[phone_id] = conn
                METRICS.set_gauge(ACTIVE_PHONES, len(self._connections))
                if on_connect is not None:
                    asyncio.create_task(on_connect(conn))
            conn.note_packet(now)
            if conn.over_rate_limit():
                METRICS.inc(PACKETS_REJECTED)
                log.warning("phone %d over rate limit; dropping packet", phone_id)
                return
            if header.sequence <= conn.sequence:
                # Duplicate or out-of-order; drop silently.
                return
            if header.sequence != conn.sequence + 1:
                gap = max(0, header.sequence - conn.sequence - 1)
                conn.dropped_frames += gap
                METRICS.inc(DROPPED_FRAMES, gap)
            conn.sequence = header.sequence
        METRICS.inc(PACKETS_DECODED)
        try:
            conn.queue.put_nowait(raw)
        except asyncio.QueueFull:
            try:
                _ = conn.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                conn.queue.put_nowait(raw)
            except asyncio.QueueFull:
                pass  # give up; this should be rare

    def get_connection(self, phone_id: int) -> PhoneConnection | None:
        return self._connections.get(phone_id)

    def all_phone_ids(self) -> list[int]:
        return list(self._connections.keys())


def packet_to_samples(packet: bytes) -> tuple[PacketType, int, int, NDArray[np.float32]]:
    """Decode a CRC-verified packet into (type, sample_rate, phone_id, samples).

    Samples are returned as float32 in [-1, 1].
    """
    header = verify_packet(packet)
    payload = packet[HEADER_SIZE : HEADER_SIZE + header.sample_count * 2]
    raw = np.frombuffer(payload, dtype="<i2")
    return (
        header.packet_type,
        header.sample_rate_hz,
        header.phone_id,
        (raw.astype(np.float32) / 32768.0),
    )
