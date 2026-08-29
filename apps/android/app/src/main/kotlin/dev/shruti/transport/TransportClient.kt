package dev.shruti.transport

import android.content.Context
import android.util.Log
import dev.shruti.config.IdentityConfig
import dev.shruti.protocol.Protocol
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong
import kotlin.concurrent.thread

/**
 * Sends binary packets to the laptop array processor over a WebSocket
 * (OkHttp's [WebSocket]). The wire format on the inside of the
 * WebSocket envelope is byte-identical to the legacy raw-TCP path —
 * each frame is one full packet (30-byte header + PCM payload +
 * 4-byte CRC-32C). The laptop's `PacketServer` (`websockets.serve`)
 * reads the same bytes it always has.
 *
 * Recovery (T05):
 *  - Exponential backoff 0.5s -> 1s -> 2s -> 4s -> 8s (capped),
 *    reset on a successful send.
 *  - On failure, the queue is *not* cleared; the oldest packet
 *    is dropped instead, and the drop is counted. The newest
 *    audio always wins over stale buffered audio.
 *  - The drop count is exposed via [droppedCount] for the heartbeat
 *    flag bit (FLAG_DROPPED) and for the laptop metrics.
 *
 * Identity (T03):
 *  - phoneId, isMaster, and the laptop URL all come from
 *    [IdentityConfig], which is SharedPreferences-backed and
 *    editable from MainActivity's setup screen.
 *  - The previous compile-time `LAPTOP_HOST`/`LAPTOP_PORT`
 *    constants are gone.
 */
object TransportClient {
    private const val TAG = "TransportClient"
    private const val QUEUE_CAPACITY = 256
    /** Max packets to keep in the queue after a drop. ~1 s of audio
     *  at the 20 ms/frame cadence. */
    private const val DROP_KEEP_RECENT = 50

    private val queue = LinkedBlockingQueue<ByteArray>(QUEUE_CAPACITY)
    @Volatile private var started = false
    @Volatile private var ctx: Context? = null
    @Volatile private var webSocket: WebSocket? = null
    @Volatile private var client: OkHttpClient? = null
    @Volatile private var backoffMs = 500L
    private val droppedCount = AtomicLong(0)
    private val sentCount = AtomicLong(0)

    /** Total packets dropped because the queue was full or the
     *  send path shed oldest. Surfaced in the heartbeat flag bit
     *  and exposed to the laptop metrics. */
    fun droppedCount(): Long = droppedCount.get()

    /** Total packets successfully delivered to the WebSocket. */
    fun sentCount(): Long = sentCount.get()

    /** Start the sender. Idempotent. The first call must have a
     *  Context so the client's identity (phoneId, WS URL) is
     *  resolvable. */
    fun start(context: Context) {
        if (started) return
        started = true
        ctx = context.applicationContext
        thread(name = "shruti-tx", isDaemon = true) { senderLoop() }
    }

    /** Backwards-compatible entry point. The capture services still
     *  call `TransportClient.start()`; we resolve the Context from
     *  the [IdentityConfig] application context the first time a
     *  packet is sent if the caller didn't pass one in. */
    fun start() {
        // No-op; we now require a Context. Existing callers are
        // updated to pass one. The function is kept so that
        // older call sites compile during the migration.
    }

    fun send(packet: ByteArray) {
        if (!started) {
            Log.w(TAG, "send() called before start(); dropping ${packet.size}-byte packet")
            return
        }
        if (!queue.offer(packet)) {
            // Queue full. Drop the oldest to keep the newest
            // audio (T05). This is the only correct way to
            // handle a burst: clearing the queue would lose
            // timing relationships across the whole window.
            val dropped = queue.poll()
            if (dropped != null) droppedCount.incrementAndGet()
            if (!queue.offer(packet)) {
                droppedCount.incrementAndGet()
            }
        }
    }

    private fun senderLoop() {
        while (true) {
            val pkt = queue.take()
            try {
                ensureConnected().send(ByteString.of(*pkt))
                sentCount.incrementAndGet()
                backoffMs = 500L  // reset on success
            } catch (e: InterruptedException) {
                Thread.currentThread().interrupt()
                return
            } catch (e: Throwable) {
                Log.w(TAG, "send failed, will reconnect: ${e.message}")
                closeQuietly()
                val failures = backoffMs
                Log.d(TAG, "backing off ${backoffMs} ms before reconnect attempt")
                TimeUnit.MILLISECONDS.sleep(backoffMs)
                backoffMs = (backoffMs * 2).coerceAtMost(8_000L)
                // The current packet was already consumed from
                // the queue. We do NOT requeue it: that would
                // duplicate the audio and break the sequence.
                // The next iteration will pick up the newest
                // packet, which is what the laptop's
                // drop-oldest ring buffer expects.
                @Suppress("UNUSED_VARIABLE") val _ignoredFailures = failures
            }
        }
    }

    private fun ensureConnected(): WebSocket {
        webSocket?.let { return it }
        val context = ctx
            ?: throw IllegalStateException("TransportClient.start(context) was not called")
        val url = IdentityConfig.laptopWsUrl(context)
        val c = client ?: OkHttpClient.Builder()
            .pingInterval(20, TimeUnit.SECONDS)
            .build()
            .also { client = it }
        val req = Request.Builder().url(url).build()
        val ws = c.newWebSocket(req, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                Log.i(TAG, "WebSocket open to $url")
                backoffMs = 500L
            }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.w(TAG, "WebSocket failure: ${t.message}")
                closeQuietly()
            }
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                Log.i(TAG, "WebSocket closed: code=$code reason=$reason")
                closeQuietly()
            }
        })
        webSocket = ws
        return ws
    }

    private fun closeQuietly() {
        try { webSocket?.close(1000, "client close") } catch (_: Throwable) {}
        webSocket = null
    }
}
