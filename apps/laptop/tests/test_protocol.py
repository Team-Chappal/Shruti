"""Tests for the protocol module."""
from __future__ import annotations

import struct

import numpy as np
import pytest

from shruti_array.ingest.websocket_server import packet_to_samples
from shruti_array.protocol import (
    CRC_SIZE,
    HEADER_SIZE,
    Flag,
    PacketType,
    ProtocolError,
    frame_packet,
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


def test_packet_to_samples_decodes_int16_to_float32_normalized() -> None:
    """packet_to_samples is the canonical phone->samples decoder used by
    the ingest pipeline. A previous lint pass had silently introduced
    camelCase attribute access here (Header.sampleCount etc.) that no
    test caught; this test pins the snake_case contract and the float
    normalization that the beamformer downstream depends on.
    """
    # Build a known PCM payload: 4 int16 samples, max-amplitude sine-ish.
    raw = np.array([0, 16384, -16384, 32767], dtype=np.int16).tobytes()
    pkt = frame_packet(
        phone_id=3, sequence=7, sample_rate_hz=48_000,
        samples=raw, timestamp_us=1234,
        packet_type=PacketType.AUDIO_FRAME,
    )
    ptype, sample_rate, phone_id, samples = packet_to_samples(pkt)
    assert ptype == PacketType.AUDIO_FRAME
    assert sample_rate == 48_000
    assert phone_id == 3
    assert samples.dtype == np.float32
    assert samples.shape == (4,)
    # Conversion is / 32768.0 (signed int16 max abs = 32768).
    assert samples[0] == pytest.approx(0.0)
    assert samples[1] == pytest.approx(0.5)
    assert samples[2] == pytest.approx(-0.5)
    assert samples[3] == pytest.approx(32767 / 32768.0, abs=1e-6)


def test_packet_to_samples_rejects_bad_crc() -> None:
    """If the packet is corrupted, packet_to_samples must raise (not
    return a silently-wrong array). It calls verify_packet first, so a
    CRC mismatch is a ProtocolError, not garbage samples."""
    pkt = frame_packet(
        phone_id=0, sequence=1, sample_rate_hz=48_000,
        samples=_pcm(8), timestamp_us=0,
    )
    bad = bytearray(pkt)
    bad[HEADER_SIZE + 2] ^= 0xFF
    with pytest.raises(ProtocolError):
        packet_to_samples(bytes(bad))


def test_crc32c_selftest_matches_iscsi_vector() -> None:
    """The CRC is the only packet-integrity primitive the whole wire
    protocol depends on. If this regresses, every packet is a coin flip.
    The iSCSI check value for '123456789' is 0xE3069283.
    """
    from shruti_array.protocol import _CRC32C_SELFTEST
    assert _CRC32C_SELFTEST == 0xE3069283


def test_max_payload_enforced_at_frame_packet() -> None:
    """MAX_PAYLOAD_SAMPLES caps payload size. Constructing an oversize
    packet must fail before any CRC work."""
    from shruti_array.protocol import MAX_PAYLOAD_SAMPLES
    too_big = (MAX_PAYLOAD_SAMPLES + 1) * 2  # int16 -> bytes
    with pytest.raises(ProtocolError):
        frame_packet(
            phone_id=0, sequence=1, sample_rate_hz=48_000,
            samples=b"\x00" * too_big, timestamp_us=0,
        )


def test_wire_format_constants_match_android() -> None:
    """The Kotlin reference (apps/android/protocol/.../Protocol.kt) and
    this Python module must agree on every constant that appears on the
    wire. A silent drift here turns the cross-language protocol into a
    coin flip. If you change a constant in either place, change it in
    both in the same commit.
    """
    from shruti_array.protocol import (
        MAGIC,
        MAX_PAYLOAD_SAMPLES,
        VERSION,
    )
    # Magic must be 'SHRT' little-endian so the on-wire bytes are
    # 0x54 0x52 0x55 0x53 (b'T' b'R' b'U' b'S').
    assert MAGIC == 0x53555254
    assert VERSION == 1
    assert HEADER_SIZE == 30
    assert CRC_SIZE == 4
    assert MAX_PAYLOAD_SAMPLES == 16_384
    # Packet types.
    assert PacketType.AUDIO_FRAME.value == 0x01
    assert PacketType.CHIRP_ECHO.value == 0x02
    assert PacketType.HEARTBEAT.value == 0x03
    # Flag bits.
    assert Flag.DROPPED.value == 1 << 0
    assert Flag.LAST.value == 1 << 1


def test_packed_header_layout_matches_struct_format() -> None:
    """Pin the byte offsets of every field. If any field drifts, the
    Kotlin parser (which uses the same layout) will produce garbage.
    """
    pkt = frame_packet(
        phone_id=0xAB,  # 0xAB in the phone_id byte
        sequence=0x01020304,
        sample_rate_hz=0x05060708,
        samples=b"\x00" * 2,  # 1 int16 sample so the packet isn't trivial
        timestamp_us=0x090A0B0C0D0E0F10,
    )
    magic = struct.unpack_from("<I", pkt, 0)[0]
    assert magic == 0x53555254
    assert pkt[4] == 1  # version
    assert pkt[5] == 0x01  # type = AUDIO_FRAME
    assert pkt[6] == 0  # flags
    assert pkt[7] == 0xAB  # phone_id
    seq = struct.unpack_from("<I", pkt, 8)[0]
    sr = struct.unpack_from("<I", pkt, 12)[0]
    sc = struct.unpack_from("<H", pkt, 16)[0]
    reserved = struct.unpack_from("<I", pkt, 18)[0]
    ts = struct.unpack_from("<Q", pkt, 22)[0]
    assert seq == 0x01020304
    assert sr == 0x05060708
    assert sc == 1
    assert reserved == 0
    assert ts == 0x090A0B0C0D0E0F10
