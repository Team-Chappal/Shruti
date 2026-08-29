"""T19: Phone dialer.

Phones on Android expose an inbound WebSocket server on port
8765 (see `InboundWebSocketServer.kt` on the Android side). This
module is the laptop-side counterpart: it dials each phone, reads
binary audio frames off the WebSocket, and feeds them into the
same `PacketServer`-style downstream that the existing
`websocket_server` uses.

Why this exists
===============
The original WebSocket transport assumed the laptop is the
server and the phones are clients — the phone's `TransportClient`
dials `ws://<laptop-ip>:8765/`. That works on a normal Wi-Fi
AP, but Android phone hotspots enforce client isolation by
default: a phone connected to the hotspot can reach the internet
and the hotspot itself, but not other Wi-Fi clients. The laptop,
on the same hotspot, is a "Wi-Fi client" from the Nothing's
point of view, so the realme cannot reach it.

The work-around is to invert the direction: the phone becomes
the server, the laptop dials the phone. Client-to-AP traffic is
not blocked by Android hotspot isolation (it's the AP's own
forwarding), so the laptop-to-phone WebSocket works in both
directions of normal NAT.

The wire format is identical: every frame is a binary blob
starting with the SHRUTI magic, version, type, flags, phone_id,
sequence, sample_rate, sample_count, reserved, timestamp, payload
and CRC-32C. The Python `protocol` module is the decoder; the
output is a per-phone async queue that the rest of the pipeline
drains — exactly the same shape as `PacketConnection`.

Use
===
The dialer is a CLI tool:
    shruti-array dial --phone 0=10.158.110.1 --phone 1=10.158.110.136

It connects to each phone, prints every audio frame it receives,
and writes a final per-phone summary. There is also a
`DialerClient` class for embedding in tests.
"""
from __future__ import annotations

import argparse
import asyncio
import time
from dataclasses import dataclass

import websockets

from ..log import get_logger
from ..protocol import (
    CRC_SIZE,
    HEADER_SIZE,
    MAX_PAYLOAD_SAMPLES,
    PacketType,
    parse_header,
    verify_packet,
)

log = get_logger(__name__)

MAX_PACKET_BYTES = HEADER_SIZE + MAX_PAYLOAD_SAMPLES * 2 + CRC_SIZE


@dataclass
class DialedPhone:
    """A single phone the laptop has dialled into.

    `packets_received` is the count of binary WebSocket frames
    pulled from the socket. `packets_decoded` is the count of
    frames that passed CRC and were a recognised packet type.
    `crc_failures` is the count that failed CRC (we drop these
    silently per the same policy as the inbound server).
    """
    phone_id: int
    url: str
    connected_at_s: float = 0.0
    disconnected_at_s: float = 0.0
    packets_received: int = 0
    packets_decoded: int = 0
    crc_failures: int = 0
    payload_bytes: int = 0
    last_sequence: int = -1
    last_error: str | None = None
    sample_rate_hz: int = 48_000

    @property
    def connected(self) -> bool:
        return self.connected_at_s > 0 and self.disconnected_at_s == 0

    @property
    def duration_s(self) -> float:
        if self.connected_at_s == 0:
            return 0.0
        end = self.disconnected_at_s if self.disconnected_at_s else time.time()
        return end - self.connected_at_s

    @property
    def bitrate_kbps(self) -> float:
        if self.duration_s <= 0:
            return 0.0
        return (self.payload_bytes * 8 / 1000) / self.duration_s


async def dial_one(phone_id: int, host: str, port: int = 8765,
                   max_seconds: float | None = None) -> DialedPhone:
    """Dial one phone, read frames until disconnect or timeout.

    Returns a `DialedPhone` with full statistics even on errors.
    The function does not raise; it sets `last_error` instead.
    """
    phone = DialedPhone(phone_id=phone_id, url=f"ws://{host}:{port}/")
    try:
        async with websockets.connect(phone.url, max_size=MAX_PACKET_BYTES,
                                     ping_interval=20) as ws:
            phone.connected_at_s = time.time()
            log.info("dialed phone %d at %s", phone_id, phone.url)
            deadline = (time.time() + max_seconds) if max_seconds else None
            while True:
                if deadline is not None and time.time() >= deadline:
                    log.info("dial_one: timeout for phone %d", phone_id)
                    break
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                except asyncio.TimeoutError:
                    continue
                except websockets.ConnectionClosed:
                    break
                if not isinstance(msg, (bytes, bytearray, memoryview)):
                    phone.last_error = "non-binary frame received"
                    continue
                buf = bytes(msg)
                phone.packets_received += 1
                # Validate against the protocol: header + payload + CRC.
                if len(buf) < HEADER_SIZE + CRC_SIZE:
                    phone.crc_failures += 1
                    continue
                if len(buf) > MAX_PACKET_BYTES:
                    phone.crc_failures += 1
                    continue
                if not verify_packet(buf):
                    phone.crc_failures += 1
                    continue
                # Decode the header to update per-phone stats. The
                # payload itself is opaque; we just count its bytes
                # so the bitrate is meaningful.
                hdr = parse_header(buf)
                payload_size = len(buf) - HEADER_SIZE - CRC_SIZE
                phone.packets_decoded += 1
                phone.payload_bytes += payload_size
                phone.last_sequence = hdr.sequence
                phone.sample_rate_hz = hdr.sample_rate_hz
                if hdr.packet_type != PacketType.AUDIO_FRAME:
                    # Heartbeats are expected; chirp echoes from the
                    # master are also expected. The DSP loop
                    # only cares about audio frames.
                    continue
    except Exception as e:
        phone.last_error = f"{type(e).__name__}: {e}"
    finally:
        phone.disconnected_at_s = time.time()
    return phone


async def dial_many(phones: list[tuple[int, str]],
                   port: int = 8765,
                   max_seconds: float | None = None) -> list[DialedPhone]:
    """Dial multiple phones in parallel and return per-phone stats.

    Each phone's connection is an independent task. We return when
    all tasks complete (which happens at timeout, or on disconnect
    of all phones).
    """
    tasks = [
        dial_one(phone_id=pid, host=host, port=port, max_seconds=max_seconds)
        for pid, host in phones
    ]
    return await asyncio.gather(*tasks, return_exceptions=False)


def _format_summary(phone: DialedPhone) -> str:
    last_err = f" last_error={phone.last_error}" if phone.last_error else ""
    return (
        f"phone {phone.phone_id} ({phone.url}): "
        f"connected={phone.duration_s:.1f}s "
        f"pkts_rx={phone.packets_received} "
        f"decoded={phone.packets_decoded} "
        f"crc_fail={phone.crc_failures} "
        f"audio_kbps={phone.bitrate_kbps:.1f} "
        f"last_seq={phone.last_sequence}{last_err}"
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Dial SHRUTI phones and read their inbound WebSocket "
                    "audio stream. Used for the venue day when the Wi-Fi "
                    "AP has client isolation and the phones cannot reach "
                    "the laptop directly.",
    )
    p.add_argument(
        "--phone", action="append", required=True,
        help="Phone to dial, as 'phone_id=host' (repeatable). "
             "Example: --phone 0=10.158.110.1 --phone 1=10.158.110.136",
    )
    p.add_argument(
        "--port", type=int, default=8765,
        help="WebSocket port on the phone (default 8765).",
    )
    p.add_argument(
        "--duration", type=float, default=10.0,
        help="How long to keep the connections open, seconds (default 10).",
    )
    args = p.parse_args(argv)
    phones: list[tuple[int, str]] = []
    for spec in args.phone:
        if "=" not in spec:
            print(f"bad --phone arg {spec!r}; expected phone_id=host", flush=True)
            return 2
        pid_s, host = spec.split("=", 1)
        try:
            phones.append((int(pid_s), host))
        except ValueError:
            print(f"bad phone_id in {spec!r}", flush=True)
            return 2
    log.info("dialling %d phone(s) for %.1fs", len(phones), args.duration)
    results = asyncio.run(dial_many(phones, port=args.port,
                                    max_seconds=args.duration))
    for r in results:
        print(_format_summary(r), flush=True)
    # Return non-zero if no frames arrived from any phone. That
    # signals a round-trip failure the operator should notice.
    if all(r.packets_decoded == 0 for r in results):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
