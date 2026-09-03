package dev.shruti.capture

import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Pure helpers for writing 16-bit mono PCM WAV files.
 *
 * The audit service ([AuditService]) writes 44-byte WAV
 * headers up front and patches the chunk size + sample count
 * once recording is complete. The patch logic is small but
 * fiddly (byte ordering, the data chunk's 4-byte length, the
 * sample count's 4-byte length), so it lives in a pure
 * object that can be unit-tested without an Android device.
 */
object WavFileWriter {
    const val HEADER_SIZE: Int = 44
    const val SAMPLE_RATE_HZ: Int = 48_000
    const val BITS_PER_SAMPLE: Int = 16
    const val NUM_CHANNELS: Int = 1
    const val BYTE_RATE: Int = SAMPLE_RATE_HZ * NUM_CHANNELS * BITS_PER_SAMPLE / 8
    const val BLOCK_ALIGN: Int = NUM_CHANNELS * BITS_PER_SAMPLE / 8

    /**
     * Build the 44-byte WAV header with the `data` chunk
     * length placeholder set to 0xFFFFFFFF (so the file looks
     * valid mid-recording; we'll patch it on close).
     */
    fun buildHeader(): ByteArray {
        val buf = ByteBuffer.allocate(HEADER_SIZE).order(ByteOrder.LITTLE_ENDIAN)
        // RIFF chunk descriptor
        buf.put("RIFF".toByteArray(Charsets.US_ASCII))
        buf.putInt(0)  // chunk size (patched later: 36 + dataBytes)
        buf.put("WAVE".toByteArray(Charsets.US_ASCII))
        // fmt sub-chunk
        buf.put("fmt ".toByteArray(Charsets.US_ASCII))
        buf.putInt(16)  // sub-chunk size for PCM
        buf.putShort(1)  // audio format = PCM
        buf.putShort(NUM_CHANNELS.toShort())
        buf.putInt(SAMPLE_RATE_HZ)
        buf.putInt(BYTE_RATE)
        buf.putShort(BLOCK_ALIGN.toShort())
        buf.putShort(BITS_PER_SAMPLE.toShort())
        // data sub-chunk
        buf.put("data".toByteArray(Charsets.US_ASCII))
        buf.putInt(0xFFFFFFFF.toInt())  // placeholder; patched on close
        return buf.array()
    }

    /**
     * Patch the WAV header in place with the final data
     * length. Reads nothing; writes two int32 values to the
     * existing file. Safe to call on a closed stream.
     */
    fun patchHeaderSize(file: File, totalSamples: Int) {
        val dataBytes = totalSamples * NUM_CHANNELS * BITS_PER_SAMPLE / 8
        RandomAccessFile(file, "rw").use { raf ->
            // chunk size at offset 4 (4 bytes) LE
            raf.seek(4)
            raf.writeInt(Integer.reverseBytes(36 + dataBytes))
            // sample count at offset 40 (4 bytes) LE — note this
            // is the sample count, not the byte count, so the
            // laptop's `pick_most_recent_per_phone` reads the
            // correct total.
            raf.seek(40)
            raf.writeInt(Integer.reverseBytes(totalSamples))
        }
    }
}
