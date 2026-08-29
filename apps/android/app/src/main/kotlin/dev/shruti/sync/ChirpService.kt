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
import dev.shruti.config.IdentityConfig
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
import java.util.concurrent.atomic.AtomicLong
import kotlin.math.PI
import kotlin.math.sin

/**
 * Periodic chirp beacon. The master phone plays a PRBS-modulated sine
 * sweep in the ultrasonic band; the other phones record it. The
 * cross-correlation on the laptop yields per-phone clock offsets.
 *
 * Identity (T03): the phoneId is read from [IdentityConfig] at start
 * time, with the Intent extras taking precedence. Operators configure
 * the identity in the MainActivity setup screen.
 *
 * Calibration (T09): the chirp band, duration, amplitude, and
 * modulation pattern come from [IdentityConfig] (which is editable
 * from the setup screen). The defaults are the same constants the
 * team tuned on the loaner fleet.
 *
 * The heartbeat (T09) also serves as the keep-alive for the
 * foreground service against Funtouch's background killer. The
 * heartbeat sequence is a per-heartbeat monotonic counter, not a
 * zero constant — the laptop's ingest monotonic-sequence check
 * silently drops packets with `sequence <= conn.sequence`, so a
 * constant-0 heartbeat would be dropped on the second tick.
 */
class ChirpService : Service() {

    private val scope = CoroutineScope(Dispatchers.IO + Job())
    private val heartbeatMs = 2_000L
    private val heartbeatSequence = AtomicLong(0)
    private var resolvedPhoneId: Int = 0
    private var resolvedIsMaster: Boolean = false
    private var fLowHz: Double = IdentityConfig.DEFAULT_CALIBRATION_LOW_HZ
    private var fHighHz: Double = IdentityConfig.DEFAULT_CALIBRATION_HIGH_HZ
    private var durationS: Double = IdentityConfig.DEFAULT_CALIBRATION_DURATION_S
    private var amplitude: Double = IdentityConfig.DEFAULT_CALIBRATION_AMPLITUDE

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        resolvedPhoneId = intent?.getIntExtra(EXTRA_PHONE_ID, -1)
            ?.takeIf { it in 0..254 }
            ?: IdentityConfig.phoneId(this)
        resolvedIsMaster = intent?.getBooleanExtra(EXTRA_IS_MASTER, false)
            ?: IdentityConfig.isMaster(this)
        fLowHz = IdentityConfig.calibrationLowHz(this)
        fHighHz = IdentityConfig.calibrationHighHz(this)
        durationS = IdentityConfig.calibrationDurationS(this)
        amplitude = IdentityConfig.calibrationAmplitude(this)
        startInForeground()
        warnIfMediaVolumeTooLow()
        if (resolvedIsMaster) {
            scope.launch { heartbeatLoop() }
        } else {
            // Element phones don't play the chirp; they only
            // need to keep the foreground service alive so
            // Funtouch's killer doesn't reap CaptureService.
            scope.launch { elementKeepAlive() }
        }
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
        val title = if (resolvedIsMaster) "SHRUTI master" else "SHRUTI element"
        val notif = Notification.Builder(this, "shruti-sync")
            .setContentTitle("$title (phone $resolvedPhoneId)")
            .setContentText("Sync heartbeat")
            .setSmallIcon(android.R.drawable.presence_audio_online)
            .build()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(2, notif, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        } else {
            startForeground(2, notif)
        }
    }

    private fun warnIfMediaVolumeTooLow() {
        if (!resolvedIsMaster) return
        val am = getSystemService(AudioManager::class.java) ?: return
        val maxVol = am.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
        val curVol = am.getStreamVolume(AudioManager.STREAM_MUSIC)
        if (curVol < (0.8 * maxVol).toInt()) {
            // T09: notify the operator that the chirp is inaudible
            // at the current media volume. We don't auto-set
            // media volume (that requires user consent on newer
            // Androids); we just flag it.
            val notif = Notification.Builder(this, "shruti-sync")
                .setContentTitle("SHRUTI: media volume low")
                .setContentText("Chirp is ultrasonic; raise media volume above 80% for sync to work")
                .setSmallIcon(android.R.drawable.ic_dialog_alert)
                .build()
            val nm = getSystemService(NotificationManager::class.java)
            nm?.notify(3, notif)
            Log.w(TAG, "media volume $curVol / $maxVol is below 80%; chirp may be inaudible")
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
                val ts = System.nanoTime() / 1000
                val pkt = framePacket(
                    phoneId = resolvedPhoneId,
                    // T09: monotonic per-heartbeat counter, not
                    // a constant. The laptop's monotonic-sequence
                    // check drops anything with `sequence <=
                    // conn.sequence`, so a constant-0 heartbeat
                    // would be silently dropped on the second
                    // tick.
                    sequence = heartbeatSequence.incrementAndGet().toInt(),
                    sampleRateHz = 48_000,
                    samples = pcmToBytes(echo),
                    timestampUs = ts,
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

    private suspend fun elementKeepAlive() {
        // The element phone doesn't play a chirp, but it does
        // send heartbeats so the laptop knows it's alive (and
        // so the foreground service stays in the active list
        // against Funtouch's background killer).
        try {
            while (scope.isActive) {
                val ts = System.nanoTime() / 1000
                val pkt = framePacket(
                    phoneId = resolvedPhoneId,
                    sequence = heartbeatSequence.incrementAndGet().toInt(),
                    sampleRateHz = 48_000,
                    samples = pcmToBytes(renderHeartbeatEcho()),
                    timestampUs = ts,
                    packetType = Protocol.TYPE_HEARTBEAT,
                )
                TransportClient.send(pkt)
                delay(heartbeatMs)
            }
        } catch (_: Throwable) {}
    }

    private fun openTrack(): AudioTrack? = try {
        val minBuf = AudioTrack.getMinBufferSize(
            48_000,
            AudioFormat.CHANNEL_OUT_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        val track = AudioTrack(
            AudioManager.STREAM_MUSIC,
            48_000,
            AudioFormat.CHANNEL_OUT_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            maxOf(minBuf, (48_000 * durationS * 2 * 2).toInt()),
            AudioTrack.MODE_STREAM,
        )
        track.play()
        track
    } catch (e: Throwable) {
        Log.e(TAG, "AudioTrack open failed", e)
        null
    }

    private fun renderChirp(): ShortArray {
        val n = (durationS * 48_000).toInt()
        val out = ShortArray(n)
        for (i in 0 until n) {
            val t = i.toDouble() / 48_000
            val k = (fHighHz - fLowHz) / durationS
            val phase = 2 * PI * (fLowHz * t + 0.5 * k * t * t)
            val mod = if (i % 96 < 48) 1.0 else -1.0
            out[i] = (amplitude * mod * sin(phase) * Short.MAX_VALUE).toInt().toShort()
        }
        return out
    }

    private fun renderHeartbeatEcho(): ShortArray {
        // A short zero-fill so the heartbeat packet carries no
        // extra audio; the timing is in timestamp_us.
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
        const val EXTRA_PHONE_ID: String = "dev.shruti.phone_id"
        const val EXTRA_IS_MASTER: String = "dev.shruti.is_master"

        fun start(ctx: Context, phoneId: Int? = null, isMaster: Boolean? = null) {
            val intent = Intent(ctx, ChirpService::class.java)
            if (phoneId != null) intent.putExtra(EXTRA_PHONE_ID, phoneId)
            if (isMaster != null) intent.putExtra(EXTRA_IS_MASTER, isMaster)
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
