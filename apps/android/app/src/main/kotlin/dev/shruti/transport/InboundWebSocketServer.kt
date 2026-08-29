/*
 * T19 inbound WebSocket server — raw ServerSocket implementation.
 *
 * Why we don't use a library
 * ---------------------------
 * We previously wired `org.java-websocket:Java-WebSocket` here. It
 * printed "ws server thread started on port 8765" (its onStart
 * callback fired) but `accept()` never actually bound. Every dial
 * from the laptop got RST. Logs showed "Operation not permitted"
 * from inside the library's accept loop. After digging on GitHub
 * and Stack Overflow (Android Emulator + java-websocket = "EPERM
 * Operation not permitted" on ServerSocket.bind), the accepted
 * workaround is to write the accept loop ourselves. This file does
 * exactly that.
 *
 * The WebSocket protocol (RFC 6455) is small:
 *   - accept() the TCP connection
 *   - read HTTP request line + headers
 *   - reply `HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n...`
 *   - SHA-1 of the Sec-WebSocket-Key + the magic GUID, base64'd
 *   - from then on, frames (not raw bytes)
 *
 * Frame format (server-to-client, no masking):
 *   byte 0: 0x80 | opcode   (0x82 = binary, FIN=1)
 *   byte 1: 126/127 for 16/64-bit length, or 0..125
 *   bytes 2..: payload (no mask from server to client)
 *
 * Multiple laptop connections are supported, each in its own
 * thread, each pushed binary frames from the same audio queue.
 */
package dev.shruti.transport

import android.util.Log
import dev.shruti.protocol.Protocol
import java.io.BufferedReader
import java.io.IOException
import java.io.InputStream
import java.io.InputStreamReader
import java.io.OutputStream
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.nio.ByteBuffer
import java.security.MessageDigest
import java.util.Base64
import java.util.Collections
import java.util.concurrent.atomic.AtomicLong

/**
 * Singleton WebSocket server bound to 0.0.0.0:8765. Phones run
 * this in their CaptureService; the laptop's `phone_dialer`
 * dials in and reads the audio stream. The same on-wire format
 * the existing `PacketServer` (laptop WS server) decodes, just
 * with the direction reversed: phones broadcast, laptop collects.
 */
object InboundWebSocketServer {
    private const val TAG = "InboundWS"
    private const val DEFAULT_PORT = 8765

    // The well-known GUID from RFC 6455 §1.3 used to compute the
    // accept hash. Hard-coded because changing it is not allowed
    // by the spec.
    private const val WS_MAGIC_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    @Volatile private var started = false
    @Volatile private var server: ServerSocket? = null
    @Volatile private var acceptThread: Thread? = null
    private val clients: MutableSet<ClientConn> = Collections.synchronizedSet(HashSet())
    private val totalConnections = AtomicLong(0)

    /**
     * One accepted laptop connection. The reader thread consumes
     * any inbound frames (we don't expect any but the spec requires
     * us to reply to pings); the writer thread is fed packets
     * from the audio queue.
     */
    private class ClientConn(val socket: Socket) {
        private val out: OutputStream = socket.getOutputStream()
        private val `in`: InputStream = socket.getInputStream()
        @Volatile private var closed = false
        private val writerThread = Thread({ writeLoop() }, "shruti-ws-writer-${socket.port}").apply { isDaemon = true; start() }
        private val readerThread = Thread({ readLoop() }, "shruti-ws-reader-${socket.port}").apply { isDaemon = true; start() }

        fun sendFrame(payload: ByteArray) {
            if (closed) return
            try {
                synchronized(out) {
                    val frame = encodeBinaryFrame(payload)
                    out.write(frame)
                    out.flush()
                }
            } catch (t: Throwable) {
                Log.w(TAG, "sendFrame failed: ${t.message}")
                close()
            }
        }

        private fun writeLoop() {
            // Sentinel — the actual writes happen in sendFrame()
            // (called from TransportClient.send -> broadcast()).
            // The writer thread's only job is to be alive so the
            // JVM doesn't garbage-collect the connection.
            try {
                while (!closed) {
                    try { Thread.sleep(60_000) } catch (_: InterruptedException) { break }
                }
            } finally {
                close()
            }
        }

        private fun readLoop() {
            try {
                val buf = ByteArray(2048)
                while (!closed) {
                    val n = `in`.read(buf)
                    if (n < 0) break
                    // We don't expect any inbound frames. The spec
                    // requires we reply to PING (opcode 0x09) with
                    // a PONG (opcode 0x0A) carrying the same payload.
                    // Cheap parse: only do this when the first byte
                    // is a non-final control frame.
                    if (n >= 2) {
                        val b0 = buf[0].toInt() and 0xFF
                        val opcode = b0 and 0x0F
                        if (opcode == 0x09) {
                            // PING — reply with PONG. We assume the
                            // ping is small and unmasked (clients
                            // must mask but we tolerate).
                            val payload = buf.copyOfRange(2, n)
                            val pong = ByteArray(2 + payload.size)
                            pong[0] = 0x8A.toByte() // FIN + PONG
                            pong[1] = payload.size.toByte()
                            System.arraycopy(payload, 0, pong, 2, payload.size)
                            synchronized(out) {
                                out.write(pong)
                                out.flush()
                            }
                        }
                    }
                }
            } catch (_: Throwable) {
                // Client went away
            } finally {
                close()
            }
        }

        fun close() {
            if (closed) return
            closed = true
            try { socket.close() } catch (_: Throwable) {}
            clients.remove(this)
            Log.i(TAG, "laptop disconnected (clients=${clients.size})")
        }
    }

    /**
     * Start the server on the given port. Idempotent. Returns
     * immediately; the accept loop runs on its own daemon thread.
     */
    fun start(listenPort: Int = DEFAULT_PORT) {
        if (started) return
        synchronized(this) {
            if (started) return
            try {
                // Direct ServerSocket constructor — the two-arg form
                // (bind addr, port) maps to ServerSocket(port, backlog,
                // bindAddr) on the JVM, but on Android 16+ calling
                // setReuseAddress(true) before bind() returns
                // EPERM (Operation not permitted), so we let the
                // system set the defaults. The direct
                // ServerSocket(port) constructor binds to 0.0.0.0
                // and queue length 50, which is what we want.
                val s = ServerSocket(listenPort)
                server = s
                acceptThread = Thread({ acceptLoop(s) }, "shruti-ws-accept").apply { isDaemon = true; start() }
                started = true
                Log.i(TAG, "Inbound WebSocket server listening on 0.0.0.0:$listenPort")
            } catch (t: Throwable) {
                Log.e(TAG, "Failed to bind 0.0.0.0:$listenPort: ${t.javaClass.name}: ${t.message}", t)
                started = false
            }
        }
    }

    /**
     * Stop the server, close every client, and release the port.
     * Idempotent.
     */
    fun stop() {
        if (!started) return
        synchronized(this) {
            if (!started) return
            started = false
            try {
                synchronized(clients) {
                    for (c in clients.toList()) try { c.close() } catch (_: Throwable) {}
                    clients.clear()
                }
                server?.close()
            } catch (t: Throwable) {
                Log.w(TAG, "stop: ${t.message}")
            }
            server = null
            acceptThread = null
            Log.i(TAG, "Inbound WebSocket server stopped")
        }
    }

    /**
     * Broadcast one captured packet to every connected client.
     * Returns the number of clients the packet was delivered to.
     * The packet is the same byte format the laptop's
     * `PacketServer` decodes — see [dev.shruti.protocol.framePacket].
     */
    fun broadcast(packet: ByteArray): Int {
        if (!started || clients.isEmpty()) return 0
        var n = 0
        synchronized(clients) {
            for (c in clients.toList()) {
                try {
                    c.sendFrame(packet)
                    n++
                } catch (_: Throwable) { /* close() runs inside */ }
            }
        }
        return n
    }

    /** Test-only: is the server currently bound? */
    val isRunning: Boolean
        get() = started

    private fun acceptLoop(s: ServerSocket) {
        while (!Thread.currentThread().isInterrupted && started) {
            try {
                val sock = s.accept()
                val remote = sock.remoteSocketAddress
                Log.i(TAG, "laptop dialed in: $remote")
                performHandshake(sock)
                val conn = ClientConn(sock)
                clients.add(conn)
                totalConnections.incrementAndGet()
                Log.i(TAG, "handshake complete (clients=${clients.size})")
            } catch (t: Throwable) {
                if (started) {
                    Log.w(TAG, "accept failed: ${t.message}")
                    try { Thread.sleep(200) } catch (_: InterruptedException) { break }
                } else break
            }
        }
    }

    /**
     * Read the HTTP upgrade request, validate it, and send back
     * the `101 Switching Protocols` reply with the
     * Sec-WebSocket-Accept hash.
     */
    private fun performHandshake(sock: Socket) {
        sock.soTimeout = 5000
        val input = BufferedReader(InputStreamReader(sock.getInputStream()))
        // Read the request line + headers
        val requestLine = input.readLine() ?: throw IOException("empty request")
        if (!requestLine.contains("HTTP/1.1")) {
            throw IOException("not HTTP/1.1: $requestLine")
        }
        var key: String? = null
        while (true) {
            val line = input.readLine() ?: break
            if (line.isEmpty()) break
            val idx = line.indexOf(':')
            if (idx > 0) {
                val name = line.substring(0, idx).trim().lowercase()
                val value = line.substring(idx + 1).trim()
                if (name == "sec-websocket-key") key = value
            }
        }
        if (key == null) throw IOException("missing Sec-WebSocket-Key")
        val accept = sha1Base64(key + WS_MAGIC_GUID)
        val response = buildString {
            append("HTTP/1.1 101 Switching Protocols\r\n")
            append("Upgrade: websocket\r\n")
            append("Connection: Upgrade\r\n")
            append("Sec-WebSocket-Accept: $accept\r\n")
            append("\r\n")
        }
        sock.getOutputStream().write(response.toByteArray(Charsets.UTF_8))
        sock.getOutputStream().flush()
    }

    private fun sha1Base64(s: String): String {
        val md = MessageDigest.getInstance("SHA-1")
        val digest = md.digest(s.toByteArray(Charsets.UTF_8))
        return Base64.getEncoder().encodeToString(digest)
    }

    /**
     * Encode a server-to-client binary frame. No masking (servers
     * must not mask).
     */
    private fun encodeBinaryFrame(payload: ByteArray): ByteArray {
        val len = payload.size
        return when {
            len <= 125 -> {
                val out = ByteArray(2 + len)
                out[0] = 0x82.toByte() // FIN + binary
                out[1] = len.toByte()
                System.arraycopy(payload, 0, out, 2, len)
                out
            }
            len <= 0xFFFF -> {
                val out = ByteArray(4 + len)
                out[0] = 0x82.toByte()
                out[1] = 126.toByte()
                out[2] = ((len shr 8) and 0xFF).toByte()
                out[3] = (len and 0xFF).toByte()
                System.arraycopy(payload, 0, out, 4, len)
                out
            }
            else -> {
                val out = ByteArray(10 + len)
                out[0] = 0x82.toByte()
                out[1] = 127.toByte()
                val bb = ByteBuffer.wrap(out, 2, 8).putLong(len.toLong())
                System.arraycopy(payload, 0, out, 10, len)
                out
            }
        }
    }
}
