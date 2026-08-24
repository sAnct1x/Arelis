package app.arelis

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.os.Handler
import android.os.Looper
import android.util.Log
import java.util.concurrent.Executors

/** True on Wi-Fi or ethernet. Cellular is still allowed; this only changes the copy. */
fun onWifi(context: Context): Boolean {
    val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
    val net = cm.activeNetwork ?: return false
    val caps = cm.getNetworkCapabilities(net) ?: return false
    return caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) ||
        caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)
}

/** Re-register listen URL when Wi-Fi DHCP moves. */
class WifiWatcher(private val context: Context) {
    private val io = Executors.newSingleThreadExecutor()
    private val main = Handler(Looper.getMainLooper())
    private var callback: ConnectivityManager.NetworkCallback? = null

    fun start() {
        val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val cb = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) = schedule()
            override fun onLost(network: Network) = Unit
            override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) {
                if (caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) ||
                    caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)
                ) {
                    schedule()
                }
            }
        }
        callback = cb
        val req = NetworkRequest.Builder()
            .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .build()
        cm.registerNetworkCallback(req, cb)
    }

    fun stop() {
        val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        callback?.let { runCatching { cm.unregisterNetworkCallback(it) } }
        callback = null
    }

    private fun schedule() {
        main.removeCallbacksAndMessages(null)
        main.postDelayed({ io.execute { reregister() } }, 800)
    }

    private fun reregister() {
        val prefs = Prefs(context)
        if (!prefs.paired || !prefs.readyToTalk) return
        if (!onWifi(context)) return
        HouseReach.findHouse(context, prefs)?.let { found ->
            if (found != prefs.baseUrl) HouseReach.adopt(prefs, found)
        }
        val guessed = listenUrlFor(context, prefs.listenPort) ?: return
        if (guessed == prefs.listenUrl) return
        prefs.listenUrl = ""
        RadioService.start(context)
        var listen = ""
        val deadline = System.currentTimeMillis() + 2_000
        while (listen.isBlank() && System.currentTimeMillis() < deadline) {
            Thread.sleep(50)
            listen = prefs.listenUrl
        }
        listen = listen.ifBlank { guessed }
        prefs.listenUrl = listen
        try {
            ArelisClient(prefs.baseUrl, prefs.token).pair(
                instance = prefs.instanceId,
                pair = "",
                listenUrl = listen,
                deviceKey = prefs.deviceKey,
            )
        } catch (exc: Exception) {
            Log.w("ArelisWifi", "re-pair failed: $exc")
        }
    }
}
