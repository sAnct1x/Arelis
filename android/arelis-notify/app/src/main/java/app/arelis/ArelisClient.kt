package app.arelis

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.IOException
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.URLEncoder
import java.net.UnknownHostException
import java.util.concurrent.TimeUnit

class ArelisClient(
    baseUrl: String,
    private val token: String,
    relayUrl: String = "",
    instance: String = "",
) {
    private val baseUrl = normalizeBaseUrl(baseUrl)
    private val relay: RelayTransport? =
        if (relayUrl.isNotBlank() && instance.isNotBlank()) {
            RelayTransport(relayUrl, token, instance)
        } else {
            null
        }
    private val lanConnectMs = if (relay != null) 1_500L else 8_000L
    private val http = OkHttpClient.Builder()
        .connectTimeout(lanConnectMs, TimeUnit.MILLISECONDS)
        .readTimeout(12, TimeUnit.SECONDS)
        .writeTimeout(12, TimeUnit.SECONDS)
        .build()
    private val longHttp = OkHttpClient.Builder()
        .connectTimeout(lanConnectMs, TimeUnit.MILLISECONDS)
        .readTimeout(10, TimeUnit.MINUTES)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    fun ping(): String {
        if (relay == null) {
            try {
                val healthReq = Request.Builder()
                    .url("$baseUrl/inbound/health")
                    .get()
                    .build()
                http.newCall(healthReq).execute().use { resp ->
                    if (!resp.isSuccessful) {
                        throw IllegalStateException(
                            "Reached the PC but /inbound/health returned HTTP ${resp.code}.",
                        )
                    }
                }
            } catch (exc: Exception) {
                if (exc is IllegalStateException) throw exc
                throw IOException(explainConnectFailure(exc, baseUrl), exc)
            }
        }
        val req = Request.Builder()
            .url("$baseUrl/inbound/ping")
            .header("X-Arelis-Token", token)
            .get()
            .build()
        val (code, bytes, _) = unary(req)
        val body = String(bytes, Charsets.UTF_8)
        if (code == 401) {
            throw IllegalStateException("Reached Arelis, but the token does not match.")
        }
        if (code !in 200..299) {
            throw IllegalStateException("HTTP $code: $body")
        }
        return body
    }

    fun pair(instance: String, pair: String, listenUrl: String, deviceKey: String, talk: Boolean = true): String {
        val json = JSONObject()
            .put("instance", instance)
            .put("pair", pair)
            .put("device_key", deviceKey)
            .put("talk", talk)
        if (listenUrl.isNotBlank()) {
            json.put("listen_url", listenUrl)
        }
        val req = Request.Builder()
            .url("$baseUrl/inbound/pair")
            .header("X-Arelis-Token", token)
            .header("Content-Type", "application/json")
            .post(json.toString().toRequestBody(JSON))
            .build()
        try {
            http.newCall(req).execute().use { resp ->
                val text = resp.body?.string().orEmpty()
                if (resp.code == 401) {
                    throw IllegalStateException("Token does not match this Arelis.")
                }
                if (resp.code == 409) {
                    throw IllegalStateException("That QR belongs to a different Arelis on this PC.")
                }
                if (resp.code == 403) {
                    throw IllegalStateException(
                        "Pairing expired. Open Settings → Notify on the PC and scan again.",
                    )
                }
                if (!resp.isSuccessful) {
                    throw IllegalStateException("HTTP ${resp.code}: $text")
                }
                return text
            }
        } catch (exc: Exception) {
            if (exc is IllegalStateException) throw exc
            throw IOException(explainConnectFailure(exc, baseUrl), exc)
        }
    }

    fun postInbound(
        id: String,
        from: String,
        body: String,
        timeIso: String,
        imageJpeg: String? = null,
    ): String {
        val json = JSONObject()
            .put("id", id)
            .put("from", from)
            .put("body", body)
            .put("time", timeIso)
            .put("source", "notification")
        if (!imageJpeg.isNullOrBlank()) {
            json.put("image_jpeg", imageJpeg)
        }
        val req = Request.Builder()
            .url("$baseUrl/inbound/sms")
            .header("X-Arelis-Token", token)
            .header("Content-Type", "application/json")
            .post(json.toString().toRequestBody(JSON))
            .build()
        val (code, bytes, _) = unary(req)
        val text = String(bytes, Charsets.UTF_8)
        if (code !in 200..299) throw IllegalStateException("HTTP $code: $text")
        return text
    }

    fun status(): JSONObject {
        val req = Request.Builder()
            .url("$baseUrl/mobile/status")
            .header("X-Arelis-Token", token)
            .get()
            .build()
        val (code, bytes, _) = unary(req)
        val body = String(bytes, Charsets.UTF_8)
        if (code == 401) throw IllegalStateException("Token does not match this Arelis.")
        if (code !in 200..299) throw IllegalStateException("HTTP $code: $body")
        return JSONObject(body.ifBlank { "{}" })
    }

    fun persona(): String {
        val req = Request.Builder()
            .url("$baseUrl/mobile/persona")
            .header("X-Arelis-Token", token)
            .get()
            .build()
        val (code, bytes, _) = unary(req)
        val body = String(bytes, Charsets.UTF_8)
        if (code !in 200..299) throw IllegalStateException("HTTP $code: $body")
        return JSONObject(body.ifBlank { "{}" }).optString("system")
    }

    fun confirm(id: String, allow: Boolean): JSONObject {
        val json = JSONObject()
            .put("id", id)
            .put("decision", if (allow) "allow" else "skip")
            .toString()
        val req = Request.Builder()
            .url("$baseUrl/mobile/confirm")
            .header("X-Arelis-Token", token)
            .header("Content-Type", "application/json")
            .post(json.toRequestBody(JSON))
            .build()
        val (code, bytes, _) = unary(req)
        val body = String(bytes, Charsets.UTF_8)
        if (code !in 200..299) throw IllegalStateException("HTTP $code: $body")
        return JSONObject(body.ifBlank { "{}" })
    }

    fun sync(messages: List<JSONObject>, sessionId: String = ""): JSONObject {
        val arr = org.json.JSONArray()
        messages.forEach { arr.put(it) }
        val json = JSONObject().put("messages", arr)
        if (sessionId.isNotBlank()) json.put("session_id", sessionId)
        val req = Request.Builder()
            .url("$baseUrl/mobile/sync")
            .header("X-Arelis-Token", token)
            .header("Content-Type", "application/json")
            .post(json.toString().toRequestBody(JSON))
            .build()
        val (code, bytes, _) = unary(req)
        val body = String(bytes, Charsets.UTF_8)
        if (code !in 200..299) throw IllegalStateException("HTTP $code: $body")
        return JSONObject(body.ifBlank { "{}" })
    }

    fun listChats(): JSONObject {
        val req = Request.Builder()
            .url("$baseUrl/mobile/chats")
            .header("X-Arelis-Token", token)
            .get()
            .build()
        val (code, bytes, _) = unary(req)
        val body = String(bytes, Charsets.UTF_8)
        if (code == 503) throw IllegalStateException("Chats wait until the house is back.")
        if (code !in 200..299) throw IllegalStateException("HTTP $code: $body")
        return JSONObject(body.ifBlank { "{}" })
    }

    fun switchChat(action: String, id: String = ""): JSONObject {
        val json = JSONObject().put("action", action)
        if (id.isNotBlank()) json.put("id", id)
        val req = Request.Builder()
            .url("$baseUrl/mobile/chat")
            .header("X-Arelis-Token", token)
            .header("Content-Type", "application/json")
            .post(json.toString().toRequestBody(JSON))
            .build()
        val (code, bytes, _) = unary(req)
        val body = String(bytes, Charsets.UTF_8)
        if (code == 503) throw IllegalStateException("Chats wait until the house is back.")
        if (code == 409) {
            val msg = runCatching { JSONObject(body).optString("error") }.getOrNull()
            throw IllegalStateException(msg.orEmpty().ifBlank { "Finish or stop the current turn first." })
        }
        if (code !in 200..299) throw IllegalStateException("HTTP $code: $body")
        return JSONObject(body.ifBlank { "{}" })
    }

    fun ackNotice(id: String) {
        val json = JSONObject().put("id", id).toString()
        val req = Request.Builder()
            .url("$baseUrl/mobile/ack")
            .header("X-Arelis-Token", token)
            .header("Content-Type", "application/json")
            .post(json.toRequestBody(JSON))
            .build()
        unary(req)
    }

    fun fileBytes(id: String): Pair<ByteArray, String> {
        val req = Request.Builder()
            .url("$baseUrl/mobile/file/$id")
            .header("X-Arelis-Token", token)
            .get()
            .build()
        val (code, bytes, mime) = unary(req)
        if (code !in 200..299) throw IllegalStateException("HTTP $code")
        return bytes to mime.ifBlank { "application/octet-stream" }
    }

    fun listFiles(scope: String, path: String): JSONObject {
        val qScope = URLEncoder.encode(scope, Charsets.UTF_8.name())
        val qPath = URLEncoder.encode(path, Charsets.UTF_8.name())
        val req = Request.Builder()
            .url("$baseUrl/mobile/files?scope=$qScope&path=$qPath")
            .header("X-Arelis-Token", token)
            .get()
            .build()
        val (code, bytes, _) = unary(req)
        val body = String(bytes, Charsets.UTF_8)
        if (code == 503) throw IllegalStateException("Open Arelis on the PC — files live there.")
        if (code == 403) throw IllegalStateException("That path is outside the workspace.")
        if (code !in 200..299) throw IllegalStateException("HTTP $code: $body")
        return JSONObject(body.ifBlank { "{}" })
    }

    fun openPath(path: String): Pair<ByteArray, String> {
        val qPath = URLEncoder.encode(path, Charsets.UTF_8.name())
        val req = Request.Builder()
            .url("$baseUrl/mobile/open?path=$qPath")
            .header("X-Arelis-Token", token)
            .get()
            .build()
        val (code, bytes, mime) = unary(req)
        if (code == 413) throw IllegalStateException("File is larger than 8 MB — open it on the PC.")
        if (code == 403) throw IllegalStateException("That path is outside the workspace.")
        if (code == 503) throw IllegalStateException("Open Arelis on the PC — files live there.")
        if (code !in 200..299) throw IllegalStateException("HTTP $code")
        return bytes to mime.ifBlank { "application/octet-stream" }
    }

    fun turn(
        text: String,
        imageJpeg: String? = null,
        audioWav: String? = null,
        onLine: (JSONObject) -> Unit,
    ) {
        val json = JSONObject().put("text", text)
        if (!imageJpeg.isNullOrBlank()) json.put("image_jpeg", imageJpeg)
        if (!audioWav.isNullOrBlank()) json.put("audio_wav_b64", audioWav)
        val payload = json.toString()
        val req = Request.Builder()
            .url("$baseUrl/mobile/turn")
            .header("X-Arelis-Token", token)
            .header("Content-Type", "application/json")
            .post(payload.toRequestBody(JSON))
            .build()
        try {
            longHttp.newCall(req).execute().use { resp ->
                if (resp.code == 401) throw IllegalStateException("Token does not match this Arelis.")
                if (resp.code == 503) {
                    throw IllegalStateException(
                        resp.body?.string()?.let {
                            runCatching { JSONObject(it).optString("error") }.getOrNull()
                        } ?: "Open Arelis on the PC.",
                    )
                }
                if (!resp.isSuccessful) {
                    throw IllegalStateException("HTTP ${resp.code}: ${resp.body?.string().orEmpty()}")
                }
                val stream = resp.body?.byteStream() ?: return
                stream.bufferedReader().use { reader ->
                    while (true) {
                        val line = reader.readLine() ?: break
                        if (line.isBlank()) continue
                        onLine(JSONObject(line))
                    }
                }
            }
        } catch (exc: IOException) {
            val r = relay ?: throw IOException(explainConnectFailure(exc, baseUrl), exc)
            r.streamTurn(payload, onLine)
        }
    }

    private fun pathOf(req: Request): String {
        val q = req.url.encodedQuery
        return req.url.encodedPath + if (q.isNullOrBlank()) "" else "?$q"
    }

    private fun bodyOf(req: Request): ByteArray? {
        val body = req.body ?: return null
        val buf = okio.Buffer()
        body.writeTo(buf)
        return buf.readByteArray()
    }

    private fun unary(req: Request): Triple<Int, ByteArray, String> {
        try {
            http.newCall(req).execute().use { resp ->
                val bytes = resp.body?.bytes() ?: ByteArray(0)
                return Triple(resp.code, bytes, resp.header("Content-Type") ?: "")
            }
        } catch (exc: IOException) {
            val r = relay ?: throw IOException(explainConnectFailure(exc, baseUrl), exc)
            val u = r.unary(req.method, pathOf(req), bodyOf(req))
            return Triple(u.code, u.body, u.contentType)
        }
    }

    companion object {
        private val JSON = "application/json; charset=utf-8".toMediaType()

        fun fromPrefs(prefs: Prefs): ArelisClient =
            ArelisClient(prefs.baseUrl, prefs.token, prefs.relayUrl, prefs.instanceId)

        fun normalizeBaseUrl(url: String): String {
            var value = url.trim()
            while (value.endsWith("/")) {
                value = value.dropLast(1)
            }
            for (suffix in listOf(
                "/inbound/ping",
                "/inbound/health",
                "/inbound/sms",
                "/inbound/pair",
                "/inbound",
                "/mobile/status",
                "/mobile/turn",
            )) {
                if (value.endsWith(suffix)) {
                    value = value.removeSuffix(suffix)
                    break
                }
            }
            return value
        }

        fun explainConnectFailure(exc: Throwable, baseUrl: String): String {
            val root = generateSequence(exc) { it.cause }.last()
            return when (root) {
                is ConnectException ->
                    "Cannot reach $baseUrl. Is Arelis open on the PC, same Wi-Fi, firewall allowing the port?"
                is SocketTimeoutException ->
                    "Timed out reaching $baseUrl. PC asleep? Guest Wi-Fi?"
                is UnknownHostException ->
                    "Unknown host in $baseUrl."
                else ->
                    "Failed to reach $baseUrl: ${root.message ?: root.javaClass.simpleName}"
            }
        }
    }
}
