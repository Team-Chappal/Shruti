package dev.shruti.capture

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Build
import android.os.IBinder
import android.util.Log
import dev.shruti.protocol.Protocol
import dev.shruti.protocol.framePacket
import dev.shruti.transport.TransportClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.atomic.AtomicLong

/**
 * Foreground service that captures UNPROCESSED PCM at 48 kHz mono and
 * streams it to the laptop array processor.
 *
 * NEEDS-DEVICE:
 *   - UNPROCESSED source selection is the linchpin of the whole
 *     product. On the iQOO loaner fleet we must verify that
 *     AudioRecord with MediaRecorder.AudioSource.UNPROCESSED returns
 *     phase-coherent capture across all three units (ticket T01).
 *   - On Android 9 and below, UNPROCESSED is the only path. On 10+ it
 *     is restricted; the actual capture may need a vendor-specific
 *     input source. The team fills in the working source here.
 *   - The foreground service keeps the capture alive against
 *     Funtouch's background killer; the heartbeat below is part of
 *     the same defence.
 */
class CaptureService : Service() {

    private val scope = CoroutineScope(Dispatchers.Default + Job())
    private val sequence = AtomicLong(0)
    private val sampleRateHz = 48_000
    private val frameMs = 20
    private val frameSamples = sampleRateHz * frameMs / 1000 // 960

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startInForeground()
        scope.launch { captureLoop() }
        return START_STICKY
    }

    private fun startInForeground() {
        val channel = NotificationChannel(
            "shruti-capture",
            "SHRUTI capture",
            NotificationManager.IMPORTANCE_LOW,
        )
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(channel)
        val notif = Notification.Builder(this, "shruti-capture")
            .setContentTitle("SHRUTI")
            .setContentText("Capturing for the array")
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .build()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(
                1, notif,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE,
            )
        } else {
            startForeground(1, notif)
        }
    }

    private suspend fun captureLoop() {
        // NEEDS-DEVICE: pick the working AudioSource on the loaner fleet.
        // UNPROCESSED is the goal; fall back to MIC if it doesn't work.
        val source = MediaRecorder.AudioSource.UNPROCESSED
        val minBuf = AudioRecord.getMinBufferSize(
            sampleRateHz,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        val bufBytes = maxOf(minBuf, frameSamples * 2 * 4)
        val record = try {
            AudioRecord(
                source,
                sampleRateHz,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                bufBytes,
            )
        } catch (e: SecurityException) {
            Log.e(TAG, "RECORD_AUDIO not granted", e)
            stopSelf()
            return
        }
        if (record.state != AudioRecord.STATE_INITIALIZED) {
            Log.e(TAG, "AudioRecord failed to initialise")
            stopSelf()
            return
        }
        record.startRecording()

        val shortBuf = ShortArray(frameSamples)
        try {
            while (scope.isActive) {
                val read = record.read(shortBuf, 0, shortBuf.size, AudioRecord.READ_BLOCKING)
                if (read <= 0) continue
                val pcm = ShortArray(read) { shortBuf[it] }
                val pcmBytes = ByteArray(pcm.size * 2)
                ByteBuffer.wrap(pcmBytes).order(ByteOrder.LITTLE_ENDIAN)
                    .asShortBuffer().put(pcm)
                val ts = System.nanoTime() / 1000
                val pkt = framePacket(
                    phoneId = phoneId,
                    sequence = sequence.incrementAndGet().toInt(),
                    sampleRateHz = sampleRateHz,
                    samples = pcmBytes,
                    timestampUs = ts,
                )
                TransportClient.send(pkt)
            }
        } finally {
            try { record.stop() } catch (_: Throwable) {}
            try { record.release() } catch (_: Throwable) {}
        }
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    companion object {
        private const val TAG = "CaptureService"
        const val PHONE_ID: Int = 0  // the team assigns 0/1/2 per device

        fun start(ctx: Context) {
            val intent = Intent(ctx, CaptureService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                ctx.startForegroundService(intent)
            } else {
                ctx.startService(intent)
            }
        }

        fun stop(ctx: Context) {
            ctx.stopService(Intent(ctx, CaptureService::class.java))
        }
    }
}

/** Per-device identity. The team sets this from a runtime config. */
private val phoneId: Int
    get() = CaptureService.PHONE_ID
