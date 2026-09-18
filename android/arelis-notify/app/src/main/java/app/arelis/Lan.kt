package app.arelis

import android.content.Context
import android.net.ConnectivityManager
import android.net.LinkProperties
import android.net.NetworkCapabilities

fun wifiIpv4(context: Context): String? = firstIpv4(context, allowCellular = false)

/** Wi-Fi / ethernet first, then cellular. Never returns 0.0.0.0. */
fun listenIpv4(context: Context): String? = advertiseIpv4(firstIpv4(context, allowCellular = true))

fun listenUrlFor(context: Context, port: Int): String? {
    val ip = listenIpv4(context) ?: return null
    return "http://$ip:$port"
}

internal fun advertiseIpv4(ip: String?): String? {
    if (ip.isNullOrBlank() || ip == "0.0.0.0" || ip.startsWith("127.")) return null
    return ip
}

private fun firstIpv4(context: Context, allowCellular: Boolean): String? {
    val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
    var cellular: String? = null
    for (network in cm.allNetworks) {
        val caps = cm.getNetworkCapabilities(network) ?: continue
        val wifi = caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
        val ethernet = caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)
        val cell = caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR)
        if (!wifi && !ethernet && !(allowCellular && cell)) continue
        val ip = ipv4From(cm.getLinkProperties(network)) ?: continue
        if (wifi || ethernet) return ip
        if (cellular == null) cellular = ip
    }
    if (cellular != null) return cellular
    return ipv4From(cm.getLinkProperties(cm.activeNetwork))
}

private fun ipv4From(props: LinkProperties?): String? {
    if (props == null) return null
    for (addr in props.linkAddresses) {
        val inet = addr.address
        if (inet is java.net.Inet4Address && !inet.isLoopbackAddress) {
            val host = inet.hostAddress ?: continue
            if (host.startsWith("127.")) continue
            return host
        }
    }
    return null
}
