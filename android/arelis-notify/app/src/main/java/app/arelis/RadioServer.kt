package app.arelis

import android.content.Context
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedInputStream
import java.io.ByteArrayOutputStream
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.nio.charset.StandardCharsets
import java.util.UUID
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * SMSGate-shaped Local Server: POST /messages, GET /health.
 * Auth is the pairing device key (Basic arelis:&lt;key&gt; or Bearer).
 */
class RadioServer(
    private val context: Context,
    private val prefs: Prefs,
    private val bindHost: String,
    private val port: Int,
) {
    private val running = AtomicBoolean(false)
    private val pool = Executors.newCachedThreadPool()
    private var server: ServerSocket? = null
    @Volatile
    var boundPort: Int = port
        private set

    fun start() {
        if (!running.compareAndSet(false, true)) return
        var socket: ServerSocket? = null
        var chosen = port
        var last: Exception? = null
        for (i in 0..9) {
            try {
                socket = ServerSocket(chosen, 8, InetAddress.getByName(bindHost))
                break
            } catch (exc: Exception) {
                last = exc
                chosen += 1
            }
        }
        val bound = socket ?: run {
            running.set(false)
            throw last ?: IllegalStateException("radio port")
        }
        boundPort = bound.localPort
        server = bound
        pool.execute {
            while (running.get()) {
                try {
                    val client = bound.accept()
                    pool.execute { handle(client) }
                } catch (_: Exception) {
                    if (!running.get()) break
                }
            }
        }
    }

    fun stop() {
        running.set(false)
        runCatching { server?.close() }
        server = null
    }

    private fun handle(client: Socket) {
        client.soTimeout = 15_000
        try {
            val input = BufferedInputStream(client.getInputStream())
            val headerBytes = readHeaders(input) ?: return
            val headerText = String(headerBytes, StandardCharsets.ISO_8859_1)
            val lines = headerText.split("\r\n")
            val requestLine = lines.firstOrNull().orEmpty()
            val parts = requestLine.split(" ")
            val method = parts.getOrNull(0).orEmpty()
            val path = parts.getOrNull(1)?.substringBefore("?").orEmpty()
            val headers = mutableMapOf<String, String>()
            for (line in lines.drop(1)) {
                val idx = line.indexOf(':')
                if (idx <= 0) continue
                headers[line.substring(0, idx).trim().lowercase()] = line.substring(idx + 1).trim()
            }
            val length = headers["content-length"]?.toIntOrNull()?.coerceIn(0, 32_000) ?: 0
            val body = if (length > 0) input.readNBytesCompat(length) else ByteArray(0)
            if (!authorized(headers)) {
                reply(client, 401, """{"ok":false,"error":"unauthorized"}""")
                return
            }
            when {
                method == "GET" && (path == "/health" || path == "/") ->
                    reply(client, 200, """{"ok":true,"service":"arelis-radio"}""")
                method == "POST" && path == "/messages" -> {
                    val result = sendMessage(String(body, StandardCharsets.UTF_8))
                    reply(client, result.first, result.second)
                }
                else -> reply(client, 404, """{"ok":false,"error":"not found"}""")
            }
        } catch (_: Exception) {
            runCatching { reply(client, 500, """{"ok":false,"error":"radio error"}""") }
        } finally {
            runCatching { client.close() }
        }
    }

    private fun authorized(headers: Map<String, String>): Boolean {
        val key = prefs.deviceKey
        if (key.isBlank()) return false
        val auth = headers["authorization"].orEmpty()
        if (auth.startsWith("Bearer ", ignoreCase = true)) {
            return auth.substring(7).trim() == key
        }
        if (auth.startsWith("Basic ", ignoreCase = true)) {
            val decoded = runCatching {
                String(Base64.decode(auth.substring(6).trim(), Base64.DEFAULT), StandardCharsets.UTF_8)
            }.getOrNull().orEmpty()
            val password = decoded.substringAfter(":", missingDelimiterValue = "")
            return password == key
        }
        return headers["x-arelis-token"] == key
    }

    private fun sendMessage(raw: String): Pair<Int, String> {
        val obj = runCatching { JSONObject(raw.ifBlank { "{}" }) }.getOrNull()
            ?: return 400 to """{"ok":false,"error":"invalid json"}"""
        val numbers = mutableListOf<String>()
        val arr: JSONArray? = obj.optJSONArray("phoneNumbers")
        if (arr != null) {
            for (i in 0 until arr.length()) {
                val n = arr.optString(i).trim()
                if (n.isNotEmpty()) numbers.add(n)
            }
        }
        val one = obj.optString("phoneNumber").trim()
        if (one.isNotEmpty()) numbers.add(one)
        val text = obj.optJSONObject("textMessage")?.optString("text")?.trim()
            ?: obj.optString("text").trim()
        if (numbers.isEmpty() || text.isEmpty()) {
            return 400 to """{"ok":false,"error":"phoneNumbers and textMessage.text required"}"""
        }
        val sim = obj.optInt("simNumber", 0)
        val id = UUID.randomUUID().toString()
        return try {
            SmsSender(context).send(numbers.first(), text, sim)
            200 to JSONObject().put("id", id).put("state", "Pending").toString()
        } catch (exc: SecurityException) {
            403 to """{"ok":false,"error":"SEND_SMS not granted"}"""
        } catch (exc: Exception) {
            500 to JSONObject().put("ok", false).put("error", exc.message ?: "send failed").toString()
        }
    }

    private fun reply(client: Socket, code: Int, json: String) {
        val payload = json.toByteArray(StandardCharsets.UTF_8)
        val reason = when (code) {
            200 -> "OK"
            400 -> "Bad Request"
            401 -> "Unauthorized"
            403 -> "Forbidden"
            404 -> "Not Found"
            else -> "Error"
        }
        val out = client.getOutputStream()
        val head = "HTTP/1.1 $code $reason\r\n" +
            "Content-Type: application/json; charset=utf-8\r\n" +
            "Content-Length: ${payload.size}\r\n" +
            "Connection: close\r\n\r\n"
        out.write(head.toByteArray(StandardCharsets.US_ASCII))
        out.write(payload)
        out.flush()
    }

    private fun readHeaders(input: BufferedInputStream): ByteArray? {
        val buf = ByteArrayOutputStream()
        var last = 0
        while (true) {
            val b = input.read()
            if (b < 0) return if (buf.size() == 0) null else buf.toByteArray()
            buf.write(b)
            if (buf.size() > 16_000) return buf.toByteArray()
            if (last == '\n'.code && b == '\n'.code) break
            last = if (b == '\r'.code) last else b
            // Detect \r\n\r\n
            val bytes = buf.toByteArray()
            if (bytes.size >= 4 &&
                bytes[bytes.size - 4] == '\r'.code.toByte() &&
                bytes[bytes.size - 3] == '\n'.code.toByte() &&
                bytes[bytes.size - 2] == '\r'.code.toByte() &&
                bytes[bytes.size - 1] == '\n'.code.toByte()
            ) {
                break
            }
        }
        return buf.toByteArray()
    }
}

private fun BufferedInputStream.readNBytesCompat(len: Int): ByteArray {
    val out = ByteArray(len)
    var off = 0
    while (off < len) {
        val n = read(out, off, len - off)
        if (n < 0) break
        off += n
    }
    return if (off == len) out else out.copyOf(off)
}
