package dev.shruti.protocol

import org.junit.jupiter.api.Test
import org.junit.jupiter.api.Assertions.assertArrayEquals
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertThrows

class ProtocolTest {
    private fun pcm(samples: Int): ByteArray =
        (0 until samples).map { it.toByte() }.toByteArray()

    @Test
    fun `header roundtrips through pack and parse`() {
        val pkt = framePacket(
            phoneId = 2,
            sequence = 42,
            sampleRateHz = 48_000,
            samples = pcm(960),
            timestampUs = 1_000_000L,
        )
        assertEquals(Protocol.HEADER_SIZE + 960 * 2 + Protocol.CRC_SIZE, pkt.size)
        val hdr = verifyPacket(pkt)
        assertEquals(2, hdr.phoneId)
        assertEquals(42, hdr.sequence)
        assertEquals(48_000, hdr.sampleRateHz)
        assertEquals(960, hdr.sampleCount)
        assertEquals(1_000_000L, hdr.timestampUs)
        assertEquals(Protocol.TYPE_AUDIO_FRAME, hdr.packetType)
        assertEquals(0, hdr.flags)
    }

    @Test
    fun `flags survive the wire`() {
        val pkt = framePacket(
            phoneId = 0,
            sequence = 1,
            sampleRateHz = 48_000,
            samples = pcm(8),
            timestampUs = 0,
            flags = Protocol.FLAG_DROPPED or Protocol.FLAG_LAST,
        )
        val hdr = verifyPacket(pkt)
        assertEquals(Protocol.FLAG_DROPPED, hdr.flags and Protocol.FLAG_DROPPED)
        assertEquals(Protocol.FLAG_LAST, hdr.flags and Protocol.FLAG_LAST)
    }

    @Test
    fun `corrupt payload is detected`() {
        val pkt = framePacket(0, 1, 48_000, pcm(64), 0)
        val bad = pkt.copyOf()
        bad[Protocol.HEADER_SIZE + 4] = (bad[Protocol.HEADER_SIZE + 4].toInt() xor 0xFF).toByte()
        assertThrows(ProtocolError::class.java) { verifyPacket(bad) }
    }

    @Test
    fun `bad magic is rejected`() {
        val pkt = framePacket(0, 1, 48_000, pcm(8), 0)
        val bad = pkt.copyOf()
        bad[0] = 0; bad[1] = 0; bad[2] = 0; bad[3] = 0
        assertThrows(ProtocolError::class.java) { verifyPacket(bad) }
    }

    @Test
    fun `bad length is rejected`() {
        val pkt = framePacket(0, 1, 48_000, pcm(8), 0)
        assertThrows(ProtocolError::class.java) { verifyPacket(pkt.copyOfRange(0, pkt.size - 1)) }
    }

    @Test
    fun `payload extraction returns original samples`() {
        val samples = pcm(16)
        val pkt = framePacket(0, 1, 48_000, samples, 0)
        assertArrayEquals(samples, payload(pkt))
    }

    @Test
    fun `misaligned payload is rejected`() {
        assertThrows(ProtocolError::class.java) {
            framePacket(0, 1, 48_000, byteArrayOf(0, 1, 2), 0)
        }
    }

    @Test
    fun `chirp echo packet type roundtrips`() {
        val pkt = framePacket(
            1, 5, 48_000, pcm(32), 99,
            packetType = Protocol.TYPE_CHIRP_ECHO,
        )
        val hdr = verifyPacket(pkt)
        assertEquals(Protocol.TYPE_CHIRP_ECHO, hdr.packetType)
    }

    @Test
    fun `crc self test`() {
        // The init {} block already verified on import; this is a belt-and-braces
        // assertion for the test report.
        val selftest = crc32c("123456789".toByteArray(Charsets.US_ASCII))
        assertEquals(0xE3069283.toInt(), selftest)
    }
}
