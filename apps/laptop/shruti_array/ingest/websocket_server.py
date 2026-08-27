"""WebSocket packet receiver.

Phones connect over WebSocket and stream binary frames in the protocol
defined by `shruti_array.protocol`. The receiver validates every packet's
CRC, drops anything malformed, and feeds the rest into a bounded
per-phone ring buffer that the rest of the pipeline drains.

A real deployment on the hackathon venue runs over Wi-Fi Direct through
the Office Kit bridge; the same code works over loopback for testing
and over any TCP/IP transport.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Awaitable, Callable

import numpy as np
from numpy.typing import NDArray

from ..protocol import (
    HEADER_SIZE,
    MAX_PAYLOAD_SAMPLES,
    PacketType,
    verify_packet,
)
from ..config import ServerConfig

log = logging.getLogger(__name__)

# A handler returns True to keep the connection open, False to close.
ConnectionHandler = Callable[["PhoneConnection"], Awaitable[None]]


@dataclass
class PhoneConnection:
    phone_id: int
    sample_rate_hz: int
    queue: "asyncio.Queue[bytes]"  # raw, CRC-verified packets
    remote: tuple[str, int]
    connected_at_s: float

    def __post_init__(self) -> None:
        self.sequence: int = -1
        self.dropped_frames: int = 0


class PacketServer:
    """Minimal async WebSocket server that accepts one connection per phone.

    The server keeps a small ring buffer per phone; slow consumers
    drop the oldest packet rather than block, so a phone that suddenly
    stops responding (e.g., screen locked) doesn't stall the array.
    """

    def __init__(self, config: ServerConfig | None = None) -> None:
        self.config = config or ServerConfig()
        self._connections: dict[int, PhoneConnection] = {}
        self._lock = asyncio.Lock()

    async def start(self, on_connect: ConnectionHandler | None = None) -> None:
        import websockets  # local import so the package is optional at install

        async def handler(ws) -> None:
            remote = ws.remote_address
            try:
                async for raw in ws:
                    await self._on_packet(ws, remote, raw, on_connect)
            except Exception as e:  # noqa: BLE001
                log.warning("connection from %s closed: %s", remote, e)

        log.info("listening on ws://%s:%d", self.config.host, self.config.port)
        async with __import__("websockets").serve(  # noqa
            handler, self.config.host, self.config.port
        ):
            await asyncio.Future()  # run forever

    async def _on_packet(
        self,
        ws,
        remote: tuple[str, int],
        raw: bytes,
        on_connect: ConnectionHandler | None,
    ) -> None:
        try:
            header = verify_packet(raw)
        except Exception as e:  # noqa: BLE001
            log.warning("malformed packet from %s: %s", remote, e)
            return
        phone_id = header.phone_id
        async with self._lock:
            conn = self._connections.get(phone_id)
            if conn is None:
                conn = PhoneConnection(
                    phone_id=phone_id,
                    sample_rate_hz=header.sample_rate_hz,
                    queue=asyncio.Queue(maxsize=64),
                    remote=remote,
                    connected_at_s=time.time(),
                )
                self._connections[phone_id] = conn
                if on_connect is not None:
                    asyncio.create_task(on_connect(conn))
            if header.sequence <= conn.sequence:
                # Duplicate or out-of-order; drop silently.
                return
            if header.sequence != conn.sequence + 1:
                conn.dropped_frames += max(0, header.sequence - conn.sequence - 1)
            conn.sequence = header.sequence
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
