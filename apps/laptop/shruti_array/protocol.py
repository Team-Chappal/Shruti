"""Shared packet protocol between Android sender and laptop receiver.

The protocol is deliberately tiny and binary: the array's whole real-time
budget is in the per-frame latency, so headers must be cheap to parse and
zero-copy where possible.

Wire format (single direction: phone -> laptop):

    [magic: u32][version: u8][type: u8][flags: u8][phone_id: u8]
    [sequence: u32][sample_rate: u32][sample_count: u16][reserved: u32]
    [timestamp_us: u64]
    [payload:     i16 * sample_count]      (little-endian PCM)
    [crc32c:      u32]                     (over header + payload)

Total header: 30 bytes (struct naturally packs; alignment of Q after H+I
ends up at offset 22 with no padding needed).

Magic:   0x53555254 ('SHRT' little-endian)
Version: 1
Type:
    0x01 AUDIO_FRAME   - payload is mono PCM at sample_rate
    0x02 CHIRP_ECHO    - payload is a chirp recording (alignment signal)
    0x03 HEARTBEAT     - payload is empty, timestamp_us is the wall clock
Flags:
    bit 0: dropped_frames  (set by sender when this frame skips samples)
    bit 1: last_frame      (set when sender is closing cleanly)

The on-wire size for a 20 ms frame at 48 kHz is:
    30 byte header + 960 * 2 byte payload + 4 byte crc = 1954 bytes
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Final

MAGIC: Final[int] = 0x53555254  # 'SHRT'
VERSION: Final[int] = 1
HEADER_SIZE: Final[int] = 30
CRC_SIZE: Final[int] = 4


class PacketType(IntEnum):
    AUDIO_FRAME = 0x01
    CHIRP_ECHO = 0x02
    HEARTBEAT = 0x03


class Flag(IntEnum):
    DROPPED = 1 << 0
    LAST = 1 << 1


_HEADER_STRUCT = struct.Struct("<IBBBBII H I Q")  # 30 bytes
if _HEADER_STRUCT.size != HEADER_SIZE:
    raise RuntimeError(
        f"Header struct size {_HEADER_STRUCT.size} != HEADER_SIZE {HEADER_SIZE}"
    )

# Maximum payload: 100 ms at 96 kHz mono = 9600 samples.
# We never produce that, but bounding the parser protects us from hostile input.
MAX_PAYLOAD_SAMPLES: Final[int] = 16_384


class ProtocolError(ValueError):
    """Raised on any malformed packet."""


@dataclass(frozen=True)
class Header:
    phone_id: int
    sequence: int
    sample_rate_hz: int
    sample_count: int
    timestamp_us: int
    packet_type: PacketType
    flags: int

    def pack(self) -> bytes:
        return _HEADER_STRUCT.pack(
            MAGIC,
            VERSION,
            int(self.packet_type),
            self.flags & 0xFF,
            self.phone_id & 0xFF,
            self.sequence,
            self.sample_rate_hz,
            self.sample_count,
            0,
            self.timestamp_us,
        )


def parse_header(buf: bytes, offset: int = 0) -> Header:
    if len(buf) - offset < HEADER_SIZE:
        raise ProtocolError("buffer shorter than header")
    magic, version, ptype, flags, phone_id, seq, sr, sc, _reserved, ts = (
        _HEADER_STRUCT.unpack_from(buf, offset)
    )
    if magic != MAGIC:
        raise ProtocolError(f"bad magic 0x{magic:08x}")
    if version != VERSION:
        raise ProtocolError(f"unsupported version {version}")
    if ptype not in PacketType._value2member_map_:
        raise ProtocolError(f"unknown packet type {ptype}")
    if sc > MAX_PAYLOAD_SAMPLES:
        raise ProtocolError(f"sample_count {sc} exceeds maximum")
    return Header(
        phone_id=phone_id,
        sequence=seq,
        sample_rate_hz=sr,
        sample_count=sc,
        timestamp_us=ts,
        packet_type=PacketType(ptype),
        flags=flags,
    )


def frame_packet(
    *,
    phone_id: int,
    sequence: int,
    sample_rate_hz: int,
    samples: bytes,
    timestamp_us: int,
    packet_type: PacketType = PacketType.AUDIO_FRAME,
    flags: int = 0,
) -> bytes:
    """Build a complete packet (header + payload + CRC) from a PCM payload.

    `samples` is raw little-endian int16 PCM, exactly `sample_count * 2` bytes.
    The CRC is computed over header + payload using CRC-32C (Castagnoli),
    which is also the polynomial used by iSCSI and many NIC offloads.
    """
    if len(samples) % 2 != 0:
        raise ProtocolError("PCM payload must be int16-aligned")
    sample_count = len(samples) // 2
    if sample_count > MAX_PAYLOAD_SAMPLES:
        raise ProtocolError("payload too large")
    header = Header(
        phone_id=phone_id,
        sequence=sequence,
        sample_rate_hz=sample_rate_hz,
        sample_count=sample_count,
        timestamp_us=timestamp_us,
        packet_type=packet_type,
        flags=flags,
    )
    header_bytes = header.pack()
    crc = _crc32c(header_bytes + samples)
    return header_bytes + samples + struct.pack("<I", crc)


def verify_packet(packet: bytes) -> Header:
    """Parse + CRC-verify a complete packet. Returns the header."""
    if len(packet) < HEADER_SIZE + CRC_SIZE:
        raise ProtocolError("packet shorter than header+CRC")
    header = parse_header(packet)
    payload_len = header.sample_count * 2
    expected = HEADER_SIZE + payload_len + CRC_SIZE
    if len(packet) != expected:
        raise ProtocolError(
            f"packet length {len(packet)} != expected {expected} for "
            f"{header.sample_count} samples"
        )
    actual_crc = struct.unpack_from("<I", packet, HEADER_SIZE + payload_len)[0]
    expected_crc = _crc32c(packet[: HEADER_SIZE + payload_len])
    if actual_crc != expected_crc:
        raise ProtocolError("CRC mismatch")
    return header


def payload(packet: bytes) -> bytes:
    """Return just the PCM payload bytes of a verified packet."""
    header = verify_packet(packet)
    return packet[HEADER_SIZE : HEADER_SIZE + header.sample_count * 2]


# --- CRC-32C (Castagnoli, polynomial 0x1EDC6F41) -----------------------------
# Table-driven, bit-reflected for the LSB-first algorithm. Verified at import
# time against the well-known check value 0xE3069283 for b"123456789"
# (the same vector used by the iSCSI spec, RFC 7143).
_CRC32C_POLY = 0x82F63B78  # bit-reflected Castagnoli


def _build_crc32c_table() -> tuple[int, ...]:
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ _CRC32C_POLY
            else:
                crc >>= 1
        table.append(crc)
    return tuple(table)


_CRC32C_TABLE = _build_crc32c_table()


def _crc32c(data: bytes, init: int = 0xFFFFFFFF) -> int:
    crc = init
    for b in data:
        crc = (crc >> 8) ^ _CRC32C_TABLE[(crc ^ b) & 0xFF]
    return crc ^ 0xFFFFFFFF


# Self-test on import. The CRC is the only thing the protocol depends on for
# packet integrity; if it regresses, every packet becomes a coin flip.
_CRC32C_SELFTEST = _crc32c(b"123456789")
if _CRC32C_SELFTEST != 0xE3069283:
    raise RuntimeError(
        f"CRC-32C self-test failed: got 0x{_CRC32C_SELFTEST:08X}, "
        f"expected 0xE3069283. The Castagnoli implementation is broken."
    )
