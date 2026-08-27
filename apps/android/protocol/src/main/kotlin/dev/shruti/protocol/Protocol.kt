package dev.shruti.protocol

/**
 * On-wire packet header for phone -> laptop audio frames.
 *
 * Wire format (30 bytes):
 *   [magic: u32][version: u8][type: u8][flags: u8][phone_id: u8]
 *   [sequence: u32][sample_rate: u32][sample_count: u16][reserved: u32]
 *   [timestamp_us: u64]
 *
 * The Python reference implementation lives in
 * apps/laptop/shruti_array/protocol.py and must stay byte-compatible.
 *
 * Magic:   0x53555254 ('SHRT' little-endian)
 * Version: 1
 * Type:    0x01 AUDIO_FRAME | 0x02 CHIRP_ECHO | 0x03 HEARTBEAT
 * Flags:   bit 0 DROPPED | bit 1 LAST
 */
object Protocol {
    const val MAGIC: Int = 0x53555254
    const val VERSION: Int = 1
    const val HEADER_SIZE: Int = 30
    const val CRC_SIZE: Int = 4
    const val MAX_PAYLOAD_SAMPLES: Int = 16_384

    const val TYPE_AUDIO_FRAME: Int = 0x01
    const val TYPE_CHIRP_ECHO: Int = 0x02
    const val TYPE_HEARTBEAT: Int = 0x03

    const val FLAG_DROPPED: Int = 1 shl 0
    const val FLAG_LAST: Int = 1 shl 1

    // --- CRC-32C (Castagnoli, polynomial 0x1EDC6F41) -------------------------
    // Table-driven, bit-reflected. Verified at object init against
    // 0xE3069283 for the input "123456789" (RFC 7143 / iSCSI test vector).
    private const val CRC32C_POLY: Long = 0x82F63B78L

    private val CRC32C_TABLE: IntArray = buildCrc32cTable()

    private fun buildCrc32cTable(): IntArray {
        val table = IntArray(256)
        for (i in 0 until 256) {
            var crc = i
            repeat(8) {
                crc = if (crc and 1 != 0) (crc ushr 1) xor CRC32C_POLY.toInt()
                else crc ushr 1
            }
            table[i] = crc
        }
        return table
    }

    @JvmStatic
    fun crc32c(data: ByteArray, init: Int = 0xFFFFFFFF.toInt()): Int {
        var crc = init
        for (b in data) {
            val idx = (crc xor b.toInt()) and 0xFF
            crc = (crc ushr 8) xor CRC32C_TABLE[idx]
        }
        return crc xor 0xFFFFFFFF.toInt()
    }

    init {
        val selftest = crc32c("123456789".toByteArray(Charsets.US_ASCII))
        require(selftest == 0xE3069283.toInt()) {
            "CRC-32C self-test failed: got 0x${selftest.toUInt().toString(16)}, expected 0xe3069283"
        }
    }
}

class ProtocolError(message: String) : RuntimeException(message)

data class Header(
    val phoneId: Int,
    val sequence: Int,
    val sampleRateHz: Int,
    val sampleCount: Int,
    val timestampUs: Long,
    val packetType: Int,
    val flags: Int,
) {
    fun pack(): ByteArray {
        val buf = ByteArray(Protocol.HEADER_SIZE)
        val dv = java.nio.ByteBuffer.wrap(buf).order(java.nio.ByteOrder.LITTLE_ENDIAN)
        dv.putInt(Protocol.MAGIC)
        dv.put(Protocol.VERSION.toByte())
        dv.put(packetType.toByte())
        dv.put((flags and 0xFF).toByte())
        dv.put((phoneId and 0xFF).toByte())
        dv.putInt(sequence)
        dv.putInt(sampleRateHz)
        dv.putShort(sampleCount.toShort())
        dv.putInt(0) // reserved
        dv.putLong(timestampUs)
        return buf
    }
}

private val HEADER_STRUCT = java.nio.ByteBuffer
    .allocate(Protocol.HEADER_SIZE)
    .order(java.nio.ByteOrder.LITTLE_ENDIAN)

fun parseHeader(packet: ByteArray, offset: Int = 0): Header {
    if (packet.size - offset < Protocol.HEADER_SIZE) {
        throw ProtocolError("buffer shorter than header")
    }
    val dv = java.nio.ByteBuffer.wrap(packet, offset, Protocol.HEADER_SIZE)
        .order(java.nio.ByteOrder.LITTLE_ENDIAN)
    val magic = dv.int
    val version = dv.get().toInt() and 0xFF
    val ptype = dv.get().toInt() and 0xFF
    val flags = dv.get().toInt() and 0xFF
    val phoneId = dv.get().toInt() and 0xFF
    val seq = dv.int
    val sr = dv.int
    val sc = dv.short.toInt() and 0xFFFF
    dv.int // reserved
    val ts = dv.long
    if (magic != Protocol.MAGIC) throw ProtocolError("bad magic 0x${magic.toString(16)}")
    if (version != Protocol.VERSION) throw ProtocolError("unsupported version $version")
    if (ptype !in setOf(Protocol.TYPE_AUDIO_FRAME, Protocol.TYPE_CHIRP_ECHO, Protocol.TYPE_HEARTBEAT)) {
        throw ProtocolError("unknown packet type $ptype")
    }
    if (sc > Protocol.MAX_PAYLOAD_SAMPLES) {
        throw ProtocolError("sample_count $sc exceeds maximum")
    }
    return Header(phoneId, seq, sr, sc, ts, ptype, flags)
}

/** Build a complete packet (header + payload + CRC) from PCM int16 samples. */
fun framePacket(
    phoneId: Int,
    sequence: Int,
    sampleRateHz: Int,
    samples: ByteArray, // little-endian int16 PCM, sample_count * 2 bytes
    timestampUs: Long,
    packetType: Int = Protocol.TYPE_AUDIO_FRAME,
    flags: Int = 0,
): ByteArray {
    if (samples.size % 2 != 0) throw ProtocolError("PCM payload must be int16-aligned")
    val sampleCount = samples.size / 2
    if (sampleCount > Protocol.MAX_PAYLOAD_SAMPLES) throw ProtocolError("payload too large")
    val header = Header(
        phoneId = phoneId,
        sequence = sequence,
        sampleRateHz = sampleRateHz,
        sampleCount = sampleCount,
        timestampUs = timestampUs,
        packetType = packetType,
        flags = flags,
    )
    val headerBytes = header.pack()
    val body = headerBytes + samples
    val crc = crc32c(body)
    val out = ByteArray(body.size + Protocol.CRC_SIZE)
    System.arraycopy(body, 0, out, 0, body.size)
    val crcBuf = java.nio.ByteBuffer.wrap(out, body.size, Protocol.CRC_SIZE)
        .order(java.nio.ByteOrder.LITTLE_ENDIAN)
    crcBuf.putInt(crc)
    return out
}

fun verifyPacket(packet: ByteArray): Header {
    if (packet.size < Protocol.HEADER_SIZE + Protocol.CRC_SIZE) {
        throw ProtocolError("packet shorter than header+CRC")
    }
    val header = parseHeader(packet)
    val payloadLen = header.sampleCount * 2
    val expected = Protocol.HEADER_SIZE + payloadLen + Protocol.CRC_SIZE
    if (packet.size != expected) {
        throw ProtocolError(
            "packet length ${packet.size} != expected $expected for ${header.sampleCount} samples"
        )
    }
    val dv = java.nio.ByteBuffer.wrap(
        packet, Protocol.HEADER_SIZE + payloadLen, Protocol.CRC_SIZE,
    ).order(java.nio.ByteOrder.LITTLE_ENDIAN)
    val actualCrc = dv.int
    val expectedCrc = crc32c(packet.copyOfRange(0, Protocol.HEADER_SIZE + payloadLen))
    if (actualCrc != expectedCrc) throw ProtocolError("CRC mismatch")
    return header
}

fun payload(packet: ByteArray): ByteArray {
    val header = verifyPacket(packet)
    return packet.copyOfRange(
        Protocol.HEADER_SIZE,
        Protocol.HEADER_SIZE + header.sampleCount * 2,
    )
}

// --- CRC-32C top-level convenience ----------------------------------------
// The implementation lives inside `object Protocol` so the self-test
// runs at class init; this thin wrapper preserves the existing
// top-level call sites (and the public API).
fun crc32c(data: ByteArray, init: Int = 0xFFFFFFFF.toInt()): Int =
    Protocol.crc32c(data, init)
