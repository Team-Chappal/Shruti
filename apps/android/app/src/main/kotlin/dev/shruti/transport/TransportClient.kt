package dev.shruti.transport

import android.util.Log
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.util.concurrent.LinkedBlockingQueue
import kotlin.concurrent.thread

/**
 * Sends binary packets to the laptop array processor over a TCP socket.
 *
 * In production this runs over the Wi-Fi Direct group owned by the
 * master phone; the Office Kit bridge on the iQOO fleet routes it
 * transparently to the laptop. On a stock device the same code works
 * over a normal Wi-Fi connection to the laptop.
 *
 * NEEDS-DEVICE:
 *   - Resolve the laptop's IP from the Wi-Fi Direct group owner or
 *     mDNS on Office Kit. The team fills in `LAPTOP_HOST` after the
 *     device-audit step.
 *   - If the connection drops, the heartbeat (ChirpService) keeps
 *     the foreground service alive; this client should reconnect
 *     with exponential backoff. The current implementation reconnects
 *     on the next send.
 */
object TransportClient {
    @Volatile private var socket: Socket? = null
    @Volatile private var out: OutputStream? = null
    private val queue = LinkedBlockingQueue<ByteArray>(256)
    @Volatile private var started = false

    fun start() {
        if (started) return
        started = true
        thread(name = "shruti-tx", isDaemon = true) { senderLoop() }
    }

    fun send(packet: ByteArray) {
        if (!started) start()
        if (!queue.offer(packet)) {
            // Queue full -> drop and log. The capture service detects
            // this from the AUDIO_FRAME flags and surfaces a count.
            Log.w(TAG, "tx queue full, dropping packet of ${packet.size} bytes")
        }
    }

    private fun senderLoop() {
        while (true) {
            val pkt = queue.take()
            try {
                val s = ensureSocket()
                s.write(pkt)
                s.flush()
            } catch (e: Throwable) {
                Log.w(TAG, "send failed, will reconnect: ${e.message}")
                closeQuietly()
                queue.clear()
                // Put this packet back at the head; if the next send
                // also fails it will also be re-queued, bounded by
                // the queue capacity.
                if (!queue.offer(pkt)) {
                    Log.w(TAG, "requeue failed, dropping")
                }
                Thread.sleep(500)
            }
        }
    }

    private fun ensureSocket(): OutputStream {
        val s = socket
        if (s != null && s.isConnected && !s.isClosed) {
            return out!!
        }
        closeQuietly()
        val ns = Socket()
        ns.tcpNoDelay = true
        ns.connect(InetSocketAddress(LAPTOP_HOST, LAPTOP_PORT), 5_000)
        socket = ns
        val os = ns.getOutputStream()
        out = os
        Log.i(TAG, "connected to $LAPTOP_HOST:$LAPTOP_PORT")
        return os
    }

    private fun closeQuietly() {
        try { out?.close() } catch (_: Throwable) {}
        try { socket?.close() } catch (_: Throwable) {}
        out = null
        socket = null
    }

    // NEEDS-DEVICE: set from the device-audit step. The team's
    // runbook (tools/rebuild/recipe.md) walks through this.
    private const val LAPTOP_HOST = "192.168.49.1"  // placeholder
    private const val LAPTOP_PORT = 9870             // placeholder
    private const val TAG = "TransportClient"
}
