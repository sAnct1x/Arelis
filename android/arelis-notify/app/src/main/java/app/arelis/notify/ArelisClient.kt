package app.arelis.notify

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.IOException
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.util.concurrent.TimeUnit

class ArelisClient(
    baseUrl: String,
    private val token: String,
) {
    private val baseUrl = normalizeBaseUrl(baseUrl)
    private val http = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(8, TimeUnit.SECONDS)
        .writeTimeout(8, TimeUnit.SECONDS)
        .build()

    fun ping(): String {
        // Health first (no token): proves the phone can reach the PC at all.
        try {
            val healthReq = Request.Builder()
                .url("$baseUrl/inbound/health")
                .get()
                .build()
            http.newCall(healthReq).execute().use { resp ->
                if (!resp.isSuccessful) {
                    throw IllegalStateException(
                        "Reached PC but /inbound/health returned HTTP ${resp.code}. " +
                            "Is an older Arelis build still running?"
                    )
                }
            }
        } catch (exc: Exception) {
            throw IOException(explainConnectFailure(exc, baseUrl), exc)
        }

        val req = Request.Builder()
            .url("$baseUrl/inbound/ping")
            .header("X-Arelis-Token", token)
            .get()
            .build()
        http.newCall(req).execute().use { resp ->
            val body = resp.body?.string().orEmpty()
            if (resp.code == 401) {
                throw IllegalStateException(
                    "Reached Arelis, but the token does not match " +
                        "sms.ingest_token in data/secrets.yaml."
                )
            }
            if (!resp.isSuccessful) {
                throw IllegalStateException("HTTP ${resp.code}: $body")
            }
            return body
        }
    }

    fun postInbound(
        id: String,
        from: String,
        body: String,
        timeIso: String,
    ): String {
        val json = JSONObject()
            .put("id", id)
            .put("from", from)
            .put("body", body)
            .put("time", timeIso)
            .put("source", "notification")
            .toString()
        val req = Request.Builder()
            .url("$baseUrl/inbound/sms")
            .header("X-Arelis-Token", token)
            .header("Content-Type", "application/json")
            .post(json.toRequestBody(JSON.toMediaType()))
            .build()
        try {
            http.newCall(req).execute().use { resp ->
                val text = resp.body?.string().orEmpty()
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

    companion object {
        private val JSON = "application/json; charset=utf-8"

        fun normalizeBaseUrl(url: String): String {
            var value = url.trim()
            while (value.endsWith("/")) {
                value = value.dropLast(1)
            }
            // People sometimes paste the full ping path into the URL field.
            for (suffix in listOf("/inbound/ping", "/inbound/health", "/inbound/sms", "/inbound")) {
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
                    "Cannot connect to $baseUrl. Open Arelis on the PC, confirm " +
                        "Thinking shows the listening URL, update the IP if DHCP " +
                        "changed it, and allow TCP 8765 on a Private network."
                is SocketTimeoutException ->
                    "Timed out reaching $baseUrl. Same Wi‑Fi? Firewall blocking " +
                        "TCP 8765? PC asleep?"
                is UnknownHostException ->
                    "Unknown host in $baseUrl. Use the PC LAN IP, e.g. http://192.168.x.x:8765"
                else ->
                    "Failed to reach $baseUrl: ${root.message ?: root.javaClass.simpleName}"
            }
        }
    }
}
