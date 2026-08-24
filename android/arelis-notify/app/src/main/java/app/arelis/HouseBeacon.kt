package app.arelis

import java.net.URI

const val BEACON_PORT = 18765
const val BEACON_PREFIX = "ARELIS1"

data class HouseBeacon(
    val instance: String,
    val port: Int,
)

fun encodeBeacon(instance: String, port: Int): String =
    "$BEACON_PREFIX|${instance.trim()}|$port"

fun decodeBeacon(raw: String): HouseBeacon? {
    val parts = raw.trim().split("|")
    if (parts.size < 3 || parts[0] != BEACON_PREFIX) return null
    val instance = parts[1].trim()
    val port = parts[2].trim().toIntOrNull() ?: return null
    if (instance.isEmpty() || port !in 1..65535) return null
    return HouseBeacon(instance, port)
}

fun decodeBeacon(bytes: ByteArray): HouseBeacon? =
    decodeBeacon(bytes.toString(Charsets.US_ASCII))

fun hostOf(url: String): String? = try {
    URI(url.trim()).host
} catch (_: Exception) {
    null
}

fun portOf(url: String): Int? = try {
    URI(url.trim()).port.takeIf { it > 0 }
} catch (_: Exception) {
    null
}

fun ipv4Octet(host: String): Int? {
    val parts = host.split(".")
    if (parts.size != 4) return null
    return parts[3].toIntOrNull()?.takeIf { it in 1..254 }
}

fun subnetPrefix(ipv4: String): String? {
    val parts = ipv4.split(".")
    if (parts.size != 4) return null
    return parts.take(3).joinToString(".")
}

/**
 * URLs to try before giving up and listening for a beacon.
 * Stored addresses first, then the last known host rewritten onto the
 * phone's current /24 (Nest Wifi / DHCP after you leave and come back).
 */
fun candidateHouseUrls(
    stored: List<String>,
    wifiIpv4: String?,
    port: Int,
): List<String> {
    val out = LinkedHashSet<String>()
    val clean = stored.map { it.trim().trimEnd('/') }.filter { it.isNotEmpty() }
    out.addAll(clean)
    val p = if (port > 0) port else clean.firstNotNullOfOrNull(::portOf) ?: 8765
    val net = wifiIpv4?.let(::subnetPrefix)
    if (net != null) {
        for (url in clean) {
            val oct = hostOf(url)?.let(::ipv4Octet) ?: continue
            out.add("http://$net.$oct:$p")
        }
    }
    return out.toList()
}
