package app.arelis

import android.content.Context
import android.net.ConnectivityManager
import android.net.LinkProperties
import android.net.NetworkCapabilities
import java.net.Inet4Address

fun wifiIpv4(context: Context): String? {
    val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
    val networks = cm.allNetworks
    for (network in networks) {
        val caps = cm.getNetworkCapabilities(network) ?: continue
        val wifi = caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
        val ethernet = caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)
        if (!wifi && !ethernet) continue
        val ip = ipv4From(cm.getLinkProperties(network)) ?: continue
        return ip
    }
    return ipv4From(cm.getLinkProperties(cm.activeNetwork))
}

fun listenUrlFor(context: Context, port: Int): String? {
    val ip = wifiIpv4(context) ?: return null
    return "http://$ip:$port"
}

private fun ipv4From(props: LinkProperties?): String? {
    if (props == null) return null
    for (addr in props.linkAddresses) {
        val inet = addr.address
        if (inet is Inet4Address && !inet.isLoopbackAddress) {
            val host = inet.hostAddress ?: continue
            if (host.startsWith("127.")) continue
            return host
        }
    }
    return null
}
