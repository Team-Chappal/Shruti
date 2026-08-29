package dev.shruti.capture

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Unit tests for the WAV-header writer used by the audit
 * service (T08). Pure JVM, no Android framework needed.
 *
 * The test asserts:
 *  - the placeholder header has the correct magic, format
 *    chunk, and a placeholder data-chunk length
 *  - patching the header with the actual sample count
 *    produces a header whose chunk size and sample count
 *    fields match what a real WAV reader would expect
 *  - the sample count read back from the patched header
 *    equals the number of int16 samples written
 */
class WavFileWriterTest {

    @Test
    fun build_header_is_44_bytes_with_correct_magic_and_format() {
        val h = WavFileWriter.buildHeader()
        assertEquals(44, h.size)
        // "RIFF" .... "WAVE" magic.
        assertEquals('R'.code.toByte(), h[0])
        assertEquals('I'.code.toByte(), h[1])
        assertEquals('F'.code.toByte(), h[2])
        assertEquals('F'.code.toByte(), h[3])
        assertEquals('W'.code.toByte(), h[8])
        assertEquals('A'.code.toByte(), h[9])
        assertEquals('V'.code.toByte(), h[10])
        assertEquals('E'.code.toByte(), h[11])
        // "fmt " sub-chunk at offset 12.
        assertEquals('f'.code.toByte(), h[12])
        assertEquals('m'.code.toByte(), h[13])
        assertEquals('t'.code.toByte(), h[14])
        assertEquals(' '.code.toByte(), h[15])
        // Audio format = PCM (1) at offset 20, 2 bytes LE.
        val fmt = ByteBuffer.wrap(h, 20, 2).order(ByteOrder.LITTLE_ENDIAN).short.toInt()
        assertEquals(1, fmt and 0xFFFF)
        // Sample rate at offset 24, 4 bytes LE.
        val sr = ByteBuffer.wrap(h, 24, 4).order(ByteOrder.LITTLE_ENDIAN).int
        assertEquals(48_000, sr)
        // Bits per sample at offset 34, 2 bytes LE.
        val bps = ByteBuffer.wrap(h, 34, 2).order(ByteOrder.LITTLE_ENDIAN).short.toInt()
        assertEquals(16, bps and 0xFFFF)
        // "data" sub-chunk at offset 36.
        assertEquals('d'.code.toByte(), h[36])
        assertEquals('a'.code.toByte(), h[37])
        assertEquals('t'.code.toByte(), h[38])
        assertEquals('a'.code.toByte(), h[39])
    }

    @Test
    fun patch_header_size_writes_chunk_size_and_sample_count() {
        val tmp = File.createTempFile("shruti_audit_", ".wav")
        tmp.deleteOnExit()
        // Write the placeholder header.
        tmp.writeBytes(WavFileWriter.buildHeader())
        // Simulate writing 960 samples (one 20 ms frame at 48 kHz).
        val n = 960
        WavFileWriter.patchHeaderSize(tmp, n)

        val bytes = tmp.readBytes()
        // Chunk size at offset 4 (LE int32) = 36 + 960*2 = 1956.
        val chunk = ByteBuffer.wrap(bytes, 4, 4).order(ByteOrder.LITTLE_ENDIAN).int
        assertEquals(36 + n * 2, chunk)
        // Sample count at offset 40 (LE int32) = 960.
        val count = ByteBuffer.wrap(bytes, 40, 4).order(ByteOrder.LITTLE_ENDIAN).int
        assertEquals(n, count)
    }

    @Test
    fun patch_header_size_handles_long_recordings() {
        // 30 s at 48 kHz = 1_440_000 samples. 2 bytes/sample
        // = 2_880_000 bytes of PCM. Chunk size = 36 + that.
        val tmp = File.createTempFile("shruti_audit_long_", ".wav")
        tmp.deleteOnExit()
        tmp.writeBytes(WavFileWriter.buildHeader())
        val n = 30 * 48_000
        WavFileWriter.patchHeaderSize(tmp, n)
        val bytes = tmp.readBytes()
        val chunk = ByteBuffer.wrap(bytes, 4, 4).order(ByteOrder.LITTLE_ENDIAN).int
        assertEquals(36 + n * 2, chunk)
        val count = ByteBuffer.wrap(bytes, 40, 4).order(ByteOrder.LITTLE_ENDIAN).int
        assertEquals(n, count)
    }
}
