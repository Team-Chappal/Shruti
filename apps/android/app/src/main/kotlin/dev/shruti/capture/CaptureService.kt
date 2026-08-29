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
import dev.shruti.config.IdentityConfig
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
 * The phone's identity (phoneId, isMaster, laptop WS URL) is read
 * from [IdentityConfig] at start time, with the Intent extras
 * taking precedence. Operators configure the identity in the
 * MainActivity setup screen; the per-device value persists across
 * restarts.
 */
class CaptureService : Service() {

    private val scope = CoroutineScope(Dispatchers.Default + Job())
    private val sequence = AtomicLong(0)
    private val sampleRateHz = 48_000
    private val frameMs = 20
    private val frameSamples = sampleRateHz * frameMs / 1000 // 960
    private var resolvedPhoneId: Int = 0

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // T03: Intent extras override stored prefs so a fresh
        // launch from MainActivity can stamp the identity.
        resolvedPhoneId = intent?.getIntExtra(EXTRA_PHONE_ID, -1)
            ?.takeIf { it in 0..254 }
            ?: IdentityConfig.phoneId(this)
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
            .setContentTitle("SHRUTI phone $resolvedPhoneId")
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
        // T09: the AudioSource is now configurable per-device
        // (some loaner units need MIC or CAMCORDER instead of
        // UNPROCESSED). Default to UNPROCESSED; teams can
        // override at runtime via the setup screen.
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
            // T04: a clean error message, not a silent stop.
            // The MainActivity should have requested RECORD_AUDIO
            // before starting us. If we got here without it, the
            // operator sees a notification.
            Log.e(TAG, "RECORD_AUDIO not granted; captureService cannot run")
            val notif = Notification.Builder(this, "shruti-capture")
                .setContentTitle("SHRUTI: mic permission missing")
                .setContentText("Open the app and grant microphone access")
                .setSmallIcon(android.R.drawable.ic_dialog_alert)
                .build()
            val nm2 = getSystemService(NotificationManager::class.java)
            nm2?.notify(2, notif)
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
                // T05: FLAG_DROPPED is set when the transport
                // queue shed at least one packet since the last
                // send, so the laptop can see loss without
                // having to scrape the metrics.
                val flags = if (TransportClient.droppedCount() > 0) {
                    Protocol.FLAG_DROPPED
                } else {
                    0
                }
                val pkt = framePacket(
                    phoneId = resolvedPhoneId,
                    sequence = sequence.incrementAndGet().toInt(),
                    sampleRateHz = sampleRateHz,
                    samples = pcmBytes,
                    timestampUs = ts,
                    flags = flags,
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
        const val EXTRA_PHONE_ID: String = "dev.shruti.phone_id"

        fun start(ctx: Context, phoneId: Int? = null) {
            val intent = Intent(ctx, CaptureService::class.java)
            if (phoneId != null) intent.putExtra(EXTRA_PHONE_ID, phoneId)
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
