package app.arelis

import android.content.Context
import android.net.wifi.WifiManager
import android.util.Log
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.HttpURLConnection
import java.net.InetSocketAddress
import java.net.SocketTimeoutException
import java.net.URL

/** Reach the house after the PC's DHCP lease moved. Token still required. */
object HouseReach {
    fun findHouse(context: Context, prefs: Prefs): String? {
        if (!prefs.readyToTalk || prefs.instanceId.isBlank()) return null
        val port = prefs.ingestPort.takeIf { it > 0 } ?: portOf(prefs.baseUrl) ?: 8765
        val stored = (listOf(prefs.baseUrl) + prefs.lanUrls).distinct()
        val wifi = wifiIpv4(context)
        for (url in candidateHouseUrls(stored, wifi, port)) {
            if (matchesHouse(url, prefs.instanceId, prefs.token)) return url
        }
        val beacon = listenBeacon(context, prefs.instanceId, 1_600L) ?: return null
        val url = "http://${beacon.first}:${beacon.second}"
        return url.takeIf { matchesHouse(it, prefs.instanceId, prefs.token) }
    }

    fun adopt(prefs: Prefs, url: String) {
        val clean = url.trim().trimEnd('/')
        prefs.baseUrl = clean
        prefs.ingestPort = portOf(clean) ?: prefs.ingestPort
        prefs.lanUrls = (listOf(clean) + prefs.lanUrls).distinct()
    }

    fun matchesHouse(url: String, instance: String, token: String): Boolean {
        val health = get(url.trimEnd('/') + "/inbound/health", token = null, timeoutMs = 700) ?: return false
        if (health.first !in 200..299) return false
        val claimed = runCatching {
            JSONObject(health.second.ifBlank { "{}" }).optString("instance")
        }.getOrDefault("")
        if (claimed.isBlank() || claimed != instance) return false
        val ping = get(url.trimEnd('/') + "/inbound/ping", token = token, timeoutMs = 800) ?: return false
        return ping.first in 200..299
    }

    fun listenBeacon(context: Context, instance: String, waitMs: Long): Pair<String, Int>? {
        val wifi = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager
        val lock = wifi?.createMulticastLock("arelis-beacon")?.apply {
            setReferenceCounted(false)
            acquire()
        }
        val sock = DatagramSocket(null)
        return try {
            sock.reuseAddress = true
            sock.bind(InetSocketAddress(BEACON_PORT))
            sock.soTimeout = 250
            val buf = ByteArray(256)
            val deadline = System.currentTimeMillis() + waitMs
            while (System.currentTimeMillis() < deadline) {
                try {
                    val packet = DatagramPacket(buf, buf.size)
                    sock.receive(packet)
                    val decoded = decodeBeacon(packet.data.copyOf(packet.length)) ?: continue
                    if (decoded.instance != instance) continue
                    val host = packet.address.hostAddress ?: continue
                    if (host.contains(':')) continue
                    return host to decoded.port
                } catch (_: SocketTimeoutException) {
                    continue
                }
            }
            null
        } catch (exc: Exception) {
            Log.w("ArelisHouse", "beacon listen failed: $exc")
            null
        } finally {
            runCatching { sock.close() }
            runCatching { lock?.release() }
        }
    }

    private fun get(url: String, token: String?, timeoutMs: Int): Pair<Int, String>? {
        var conn: HttpURLConnection? = null
        return try {
            conn = (URL(url).openConnection() as HttpURLConnection).apply {
                connectTimeout = timeoutMs
                readTimeout = timeoutMs
                requestMethod = "GET"
                instanceFollowRedirects = false
                if (!token.isNullOrBlank()) {
                    setRequestProperty("X-Arelis-Token", token)
                }
            }
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val body = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            code to body
        } catch (_: Exception) {
            null
        } finally {
            conn?.disconnect()
        }
    }
}
