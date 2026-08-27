"""Tests for the protocol module."""
from __future__ import annotations

import struct

import numpy as np
import pytest

from shruti_array.protocol import (
    CRC_SIZE,
    HEADER_SIZE,
    MAGIC,
    VERSION,
    Flag,
    PacketType,
    ProtocolError,
    frame_packet,
    parse_header,
    payload,
    verify_packet,
)


def _pcm(samples: int) -> bytes:
    # Use a small int16-safe ramp; we just need non-zero bytes for the
    # integrity tests, not a specific waveform.
    return np.arange(samples, dtype=np.int16).tobytes()


def test_header_roundtrip() -> None:
    pkt = frame_packet(
        phone_id=2,
        sequence=42,
        sample_rate_hz=48_000,
        samples=_pcm(960),
        timestamp_us=1_000_000,
    )
    assert len(pkt) == HEADER_SIZE + 960 * 2 + CRC_SIZE
    hdr = verify_packet(pkt)
    assert hdr.phone_id == 2
    assert hdr.sequence == 42
    assert hdr.sample_rate_hz == 48_000
    assert hdr.sample_count == 960
    assert hdr.timestamp_us == 1_000_000
    assert hdr.packet_type == PacketType.AUDIO_FRAME
    assert hdr.flags == 0


def test_header_flags() -> None:
    pkt = frame_packet(
        phone_id=0,
        sequence=1,
        sample_rate_hz=48_000,
        samples=_pcm(8),
        timestamp_us=0,
        flags=Flag.DROPPED | Flag.LAST,
    )
    hdr = verify_packet(pkt)
    assert hdr.flags & Flag.DROPPED
    assert hdr.flags & Flag.LAST


def test_corrupt_payload_detected() -> None:
    pkt = frame_packet(
        phone_id=0,
        sequence=1,
        sample_rate_hz=48_000,
        samples=_pcm(64),
        timestamp_us=0,
    )
    # Flip a byte in the payload.
    bad = bytearray(pkt)
    bad[HEADER_SIZE + 4] ^= 0xFF
    with pytest.raises(ProtocolError):
        verify_packet(bytes(bad))


def test_bad_magic_rejected() -> None:
    pkt = bytearray(frame_packet(
        phone_id=0, sequence=1, sample_rate_hz=48_000,
        samples=_pcm(8), timestamp_us=0,
    ))
    pkt[0:4] = b"\x00\x00\x00\x00"
    with pytest.raises(ProtocolError):
        verify_packet(bytes(pkt))


def test_bad_length_rejected() -> None:
    pkt = frame_packet(
        phone_id=0, sequence=1, sample_rate_hz=48_000,
        samples=_pcm(8), timestamp_us=0,
    )
    with pytest.raises(ProtocolError):
        verify_packet(pkt[:-1])  # truncate


def test_payload_extraction() -> None:
    samples = _pcm(16)
    pkt = frame_packet(
        phone_id=0, sequence=1, sample_rate_hz=48_000,
        samples=samples, timestamp_us=0,
    )
    assert payload(pkt) == samples


def test_max_payload_enforced() -> None:
    # 16-bit alignment required.
    with pytest.raises(ProtocolError):
        frame_packet(
            phone_id=0, sequence=1, sample_rate_hz=48_000,
            samples=b"\x00\x01\x02", timestamp_us=0,  # 3 bytes -> misaligned
        )


def test_packet_type_chirp_echo() -> None:
    pkt = frame_packet(
        phone_id=1, sequence=5, sample_rate_hz=48_000,
        samples=_pcm(32), timestamp_us=99,
        packet_type=PacketType.CHIRP_ECHO,
    )
    hdr = verify_packet(pkt)
    assert hdr.packet_type == PacketType.CHIRP_ECHO


def test_parse_header_bad_version() -> None:
    pkt = frame_packet(
        phone_id=0, sequence=1, sample_rate_hz=48_000,
        samples=_pcm(4), timestamp_us=0,
    )
    # Overwrite version byte (offset 4) to an unsupported version.
    bad = bytearray(pkt)
    bad[4] = 99
    # Recompute CRC since we changed a header byte.
    from shruti_array.protocol import _crc32c
    body = bytes(bad[: HEADER_SIZE + 8])
    struct.pack_into("<I", bad, HEADER_SIZE + 8, _crc32c(body))
    with pytest.raises(ProtocolError):
        verify_packet(bytes(bad))
