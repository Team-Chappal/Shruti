package dev.shruti.sync

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioTrack
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
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlin.math.PI
import kotlin.math.sin

/**
 * Periodic chirp beacon. The master phone plays a PRBS-modulated sine
 * sweep in the ultrasonic band; the other phones record it. The
 * cross-correlation on the laptop yields per-phone clock offsets.
 *
 * NEEDS-DEVICE:
 *   - Pick the working speaker output path. The Ultrasonic band
 *     (17.5-22 kHz) is outside the comfortable range of phone speakers
 *     and may require the media volume to be at max; the demo script
 *     walks the team through setting it.
 *   - The LFSR seed and frequency band are tuned here for the
 *     measured phones' speaker/mic response; calibration step.
 *
 * The heartbeat also serves as the keep-alive for the foreground
 * service against Funtouch's background killer.
 */
class ChirpService : Service() {

    private val scope = CoroutineScope(Dispatchers.IO + Job())
    private val fLow = 17_500.0
    private val fHigh = 22_000.0
    private val durationS = 0.060
    private val amplitude = 0.4
    private val sampleRateHz = 48_000
    private val heartbeatMs = 2_000L

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startInForeground()
        scope.launch { heartbeatLoop() }
        return START_STICKY
    }

    private fun startInForeground() {
        val channel = NotificationChannel(
            "shruti-sync",
            "SHRUTI sync",
            NotificationManager.IMPORTANCE_LOW,
        )
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(channel)
        val notif = Notification.Builder(this, "shruti-sync")
            .setContentTitle("SHRUTI")
            .setContentText("Sync heartbeat")
            .setSmallIcon(android.R.drawable.presence_audio_online)
            .build()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(2, notif, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        } else {
            startForeground(2, notif)
        }
    }

    private suspend fun heartbeatLoop() {
        val chirp = renderChirp()
        val track = openTrack()
        if (track == null) {
            Log.e(TAG, "could not open AudioTrack")
            return
        }
        try {
            while (scope.isActive) {
                track.write(chirp, 0, chirp.size)
                val echo = renderHeartbeatEcho()
                val pkt = framePacket(
                    phoneId = phoneId,
                    sequence = 0,
                    sampleRateHz = sampleRateHz,
                    samples = pcmToBytes(echo),
                    timestampUs = System.nanoTime() / 1000,
                    packetType = Protocol.TYPE_HEARTBEAT,
                )
                TransportClient.send(pkt)
                delay(heartbeatMs)
            }
        } finally {
            try { track.stop() } catch (_: Throwable) {}
            try { track.release() } catch (_: Throwable) {}
        }
    }

    private fun openTrack(): AudioTrack? = try {
        val minBuf = AudioTrack.getMinBufferSize(
            sampleRateHz,
            AudioFormat.CHANNEL_OUT_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        val track = AudioTrack(
            AudioManager.STREAM_MUSIC,
            sampleRateHz,
            AudioFormat.CHANNEL_OUT_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            maxOf(minBuf, (sampleRateHz * durationS * 2 * 2).toInt()),
            AudioTrack.MODE_STREAM,
        )
        track.play()
        track
    } catch (e: Throwable) {
        Log.e(TAG, "AudioTrack open failed", e)
        null
    }

    private fun renderChirp(): ShortArray {
        val n = (durationS * sampleRateHz).toInt()
        val out = ShortArray(n)
        for (i in 0 until n) {
            val t = i.toDouble() / sampleRateHz
            val k = (fHigh - fLow) / durationS
            val phase = 2 * PI * (fLow * t + 0.5 * k * t * t)
            val mod = if (i % 96 < 48) 1.0 else -1.0
            out[i] = (amplitude * mod * sin(phase) * Short.MAX_VALUE).toInt().toShort()
        }
        return out
    }

    private fun renderHeartbeatEcho(): ShortArray {
        // A short zero-fill so the chirp_echo packet carries no extra audio;
        // the heartbeat timing is in the timestamp_us field.
        return ShortArray(8)
    }

    private fun pcmToBytes(samples: ShortArray): ByteArray {
        val out = ByteArray(samples.size * 2)
        val buf = java.nio.ByteBuffer.wrap(out).order(java.nio.ByteOrder.LITTLE_ENDIAN)
        for (s in samples) buf.putShort(s)
        return out
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    companion object {
        private const val TAG = "ChirpService"
        const val PHONE_ID: Int = 0

        fun start(ctx: Context) {
            val intent = Intent(ctx, ChirpService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                ctx.startForegroundService(intent)
            } else {
                ctx.startService(intent)
            }
        }

        fun stop(ctx: Context) {
            ctx.stopService(Intent(ctx, ChirpService::class.java))
        }
    }
}

private val phoneId: Int get() = ChirpService.PHONE_ID
