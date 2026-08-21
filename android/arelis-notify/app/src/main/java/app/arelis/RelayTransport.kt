package app.arelis

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

class HouseAwayException : IOException("The house is not on the mailbox.")

class RelayTransport(
    relayUrl: String,
    private val token: String,
    private val instance: String,
) {
    private val relayUrl = relayUrl.trim().trimEnd('/')
    private val key = RelayCrypto.e2eKey(token, instance)
    private val aad = instance.toByteArray()
    private val http = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(70, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()
    private val longHttp = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.MINUTES)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    data class Unary(val code: Int, val body: ByteArray, val contentType: String)

    fun unary(method: String, path: String, jsonBody: ByteArray? = null): Unary {
        val blob = sealRequest(method, path, jsonBody, stream = false)
        val payload = JSONObject()
            .put("instance", instance)
            .put("blob", blob)
            .put("stream", false)
            .toString()
        val req = Request.Builder()
            .url("$relayUrl/v1/phone/call")
            .header("Content-Type", "application/json")
            .post(payload.toRequestBody(JSON))
            .build()
        http.newCall(req).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (resp.code == 503) throw HouseAwayException()
            if (!resp.isSuccessful) {
                throw IOException("mailbox HTTP ${resp.code}: $text")
            }
            val replyBlob = JSONObject(text.ifBlank { "{}" }).optString("blob")
            if (replyBlob.isBlank()) throw IOException("empty mailbox reply")
            val opened = RelayCrypto.open(key, RelayCrypto.unb64(replyBlob), aad)
            val env = JSONObject(String(opened, Charsets.UTF_8))
            val body = env.optString("body_b64").let {
                if (it.isBlank()) ByteArray(0) else RelayCrypto.unb64(it)
            }
            return Unary(
                code = env.optInt("status", 502),
                body = body,
                contentType = env.optString("content_type"),
            )
        }
    }

    fun streamTurn(jsonBody: String, onLine: (JSONObject) -> Unit) {
        val blob = sealRequest("POST", "/mobile/turn", jsonBody.toByteArray(), stream = true)
        val payload = JSONObject()
            .put("instance", instance)
            .put("blob", blob)
            .put("stream", true)
            .toString()
        val req = Request.Builder()
            .url("$relayUrl/v1/phone/call")
            .header("Content-Type", "application/json")
            .post(payload.toRequestBody(JSON))
            .build()
        longHttp.newCall(req).execute().use { resp ->
            if (resp.code == 503) throw HouseAwayException()
            if (!resp.isSuccessful) {
                throw IOException("mailbox HTTP ${resp.code}")
            }
            val stream = resp.body?.byteStream() ?: return
            stream.bufferedReader().use { reader ->
                while (true) {
                    val line = reader.readLine() ?: break
                    if (line.isBlank()) continue
                    val opened = RelayCrypto.open(key, RelayCrypto.unb64(line), aad)
                    val env = JSONObject(String(opened, Charsets.UTF_8))
                    when (env.optString("kind")) {
                        "chunk" -> {
                            val text = env.optString("text")
                            if (text.isNotBlank()) onLine(JSONObject(text))
                        }
                        "end" -> return
                    }
                }
            }
        }
    }

    private fun sealRequest(
        method: String,
        path: String,
        jsonBody: ByteArray?,
        stream: Boolean,
    ): String {
        val env = JSONObject()
            .put("v", 1)
            .put("method", method)
            .put("path", path)
            .put("stream", stream)
            .put(
                "headers",
                JSONObject().put("X-Arelis-Token", token),
            )
        if (jsonBody != null && jsonBody.isNotEmpty()) {
            env.put("body_b64", RelayCrypto.b64(jsonBody))
        }
        val sealed = RelayCrypto.seal(key, env.toString().toByteArray(), aad)
        return RelayCrypto.b64(sealed)
    }

    companion object {
        private val JSON = "application/json; charset=utf-8".toMediaType()
    }
}
