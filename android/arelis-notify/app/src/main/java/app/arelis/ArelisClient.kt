package app.arelis

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
        .readTimeout(12, TimeUnit.SECONDS)
        .writeTimeout(12, TimeUnit.SECONDS)
        .build()

    fun ping(): String {
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
                throw IllegalStateException("Reached Arelis, but the token does not match.")
            }
            if (!resp.isSuccessful) {
                throw IllegalStateException("HTTP ${resp.code}: $body")
            }
            return body
        }
    }

    fun pair(instance: String, pair: String, listenUrl: String, deviceKey: String): String {
        val json = JSONObject()
            .put("instance", instance)
            .put("pair", pair)
            .put("listen_url", listenUrl)
            .put("device_key", deviceKey)
            .toString()
        val req = Request.Builder()
            .url("$baseUrl/inbound/pair")
            .header("X-Arelis-Token", token)
            .header("Content-Type", "application/json")
            .post(json.toRequestBody(JSON))
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
            .post(json.toRequestBody(JSON))
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
        private val JSON = "application/json; charset=utf-8".toMediaType()

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
