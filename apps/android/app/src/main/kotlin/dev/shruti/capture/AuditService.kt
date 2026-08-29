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
import android.os.Environment
import android.os.IBinder
import android.util.Log
import dev.shruti.config.IdentityConfig
import java.io.File
import java.io.FileOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * Audit-mode recorder (T08).
 *
 * The recipe's device-audit step (tools/rebuild/recipe.md
 * step 3) needs per-phone WAVs the laptop's `shruti-audit`
 * script can analyse (RMS, noise floor, sample rate,
 * duration). The live capture service streams bytes to
 * the laptop; this service records the same audio locally
 * to a 16-bit mono PCM WAV at the standard
 * `getExternalFilesDir()/audit/<phone_id>_<ts>.wav` path.
 *
 * Filename convention matches the recipe and the laptop
 * fallback: `<phone_id>_<...>.wav` where the trailing part
 * is a free-form timestamp. The laptop's `pick_most_recent_
 * per_phone` already accepts this.
 */
class AuditService : Service() {

    private val scope = CoroutineScope(Dispatchers.IO + Job())
    private val sampleRateHz = 48_000
    private val frameMs = 20
    private val frameSamples = sampleRateHz * frameMs / 1000
    private var resolvedPhoneId: Int = 0
    private var resolvedDurationS: Int = 30
    private var outputFile: File? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        resolvedPhoneId = intent?.getIntExtra(EXTRA_PHONE_ID, -1)
            ?.takeIf { it in 0..254 }
            ?: IdentityConfig.phoneId(this)
        resolvedDurationS = intent?.getIntExtra(EXTRA_DURATION_S, 30) ?: 30
        startInForeground()
        scope.launch { recordLoop() }
        return START_STICKY
    }

    private fun startInForeground() {
        val channel = NotificationChannel(
            "shruti-audit",
            "SHRUTI audit",
            NotificationManager.IMPORTANCE_LOW,
        )
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(channel)
        val notif = Notification.Builder(this, "shruti-audit")
            .setContentTitle("SHRUTI audit (phone $resolvedPhoneId)")
            .setContentText("Recording 30 s of silence for calibration")
            .setSmallIcon(android.R.drawable.ic_menu_save)
            .build()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(
                3, notif,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE,
            )
        } else {
            startForeground(3, notif)
        }
    }

    private suspend fun recordLoop() {
        val source = MediaRecorder.AudioSource.UNPROCESSED
        val minBuf = AudioRecord.getMinBufferSize(
            sampleRateHz,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        val bufBytes = maxOf(minBuf, frameSamples * 2 * 4)
        val record = try {
            AudioRecord(
                source, sampleRateHz,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                bufBytes,
            )
        } catch (e: SecurityException) {
            Log.e(TAG, "RECORD_AUDIO not granted; audit cannot run")
            stopSelf()
            return
        }
        if (record.state != AudioRecord.STATE_INITIALIZED) {
            Log.e(TAG, "AudioRecord failed to initialise")
            stopSelf()
            return
        }
        // Prepare the output file. Standard 16-bit PCM mono
        // WAV: 44-byte header + raw int16 samples.
        val outDir = File(
            getExternalFilesDir(Environment.DIRECTORY_MUSIC),
            "audit",
        )
        outDir.mkdirs()
        val ts = System.currentTimeMillis()
        val out = File(outDir, "${resolvedPhoneId}_${ts}.wav")
        outputFile = out
        val fos = FileOutputStream(out)
        fos.write(WavFileWriter.buildHeader())
        record.startRecording()
        val shortBuf = ShortArray(frameSamples)
        val nFrames = (resolvedDurationS * sampleRateHz) / frameSamples
        var totalSamples = 0
        try {
            for (i in 0 until nFrames) {
                if (!scope.isActive) break
                val read = record.read(shortBuf, 0, shortBuf.size, AudioRecord.READ_BLOCKING)
                if (read <= 0) continue
                val pcmBytes = ByteArray(read * 2)
                ByteBuffer.wrap(pcmBytes).order(ByteOrder.LITTLE_ENDIAN)
                    .asShortBuffer().put(shortBuf, 0, read)
                fos.write(pcmBytes)
                totalSamples += read
            }
        } finally {
            try { record.stop() } catch (_: Throwable) {}
            try { record.release() } catch (_: Throwable) {}
            try { fos.close() } catch (_: Throwable) {}
        }
        // Fix up the WAV header with the final sizes.
        WavFileWriter.patchHeaderSize(out, totalSamples)
        Log.i(TAG, "wrote audit WAV: ${out.absolutePath} (${totalSamples} samples)")
        // Notify completion so MainActivity can show a "Share" affordance.
        val done = Notification.Builder(this, "shruti-audit")
            .setContentTitle("SHRUTI audit: WAV ready")
            .setContentText("Tap to share ${out.name}")
            .setSmallIcon(android.R.drawable.stat_sys_download_done)
            .setAutoCancel(true)
            .build()
        val nm = getSystemService(NotificationManager::class.java)
        nm?.notify(4, done)
        // T08: post a broadcast so MainActivity can update its UI.
        val intent = Intent(ACTION_AUDIT_DONE).apply {
            putExtra(EXTRA_OUTPUT_PATH, out.absolutePath)
            setPackage(packageName)
        }
        sendBroadcast(intent)
        stopSelf()
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    companion object {
        private const val TAG = "AuditService"
        const val EXTRA_PHONE_ID: String = "dev.shruti.phone_id"
        const val EXTRA_DURATION_S: String = "dev.shruti.duration_s"
        const val ACTION_AUDIT_DONE: String = "dev.shruti.action.AUDIT_DONE"
        const val EXTRA_OUTPUT_PATH: String = "dev.shruti.output_path"

        fun start(ctx: Context, phoneId: Int? = null, durationS: Int = 30) {
            val intent = Intent(ctx, AuditService::class.java)
            if (phoneId != null) intent.putExtra(EXTRA_PHONE_ID, phoneId)
            intent.putExtra(EXTRA_DURATION_S, durationS)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                ctx.startForegroundService(intent)
            } else {
                ctx.startService(intent)
            }
        }

        fun stop(ctx: Context) {
            ctx.stopService(Intent(ctx, AuditService::class.java))
        }
    }
}
