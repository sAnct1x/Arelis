package app.arelis

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat

class RadioService : Service() {
    private var server: RadioServer? = null
    private var wifiWatcher: WifiWatcher? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val prefs = Prefs(this)
        // Bind during first pair too — the PC needs this listen URL in POST
        // /inbound/pair. Auth is still the device key; unpaired means the PC
        // does not have it yet.
        ensureChannel()
        val notification = NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_radio)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(getString(R.string.radio_notification))
            .setOngoing(true)
            .setColor(ContextCompat.getColor(this, R.color.accent))
            .setContentIntent(
                PendingIntent.getActivity(
                    this,
                    0,
                    Intent(this, MainActivity::class.java),
                    PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
                ),
            )
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(
                NOTIF_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE,
            )
        } else {
            startForeground(NOTIF_ID, notification)
        }
        startRadio(prefs)
        if (wifiWatcher == null) {
            wifiWatcher = WifiWatcher(applicationContext).also { it.start() }
        }
        BridgeKeepalive.ensure(this)
        return START_STICKY
    }

    private fun startRadio(prefs: Prefs) {
        server?.stop()
        val ip = listenIpv4(this)
        val bindHost = ip ?: "0.0.0.0"
        val wanted = prefs.listenPort.takeIf { it > 0 } ?: 8080
        val radio = RadioServer(this, prefs, bindHost, wanted)
        radio.start()
        prefs.listenPort = radio.boundPort
        // 0.0.0.0 is bind-only. WifiWatcher fills listenUrl when an address lands.
        prefs.listenUrl = if (ip != null) "http://$ip:${radio.boundPort}" else ""
        server = radio
    }

    override fun onDestroy() {
        wifiWatcher?.stop()
        wifiWatcher = null
        server?.stop()
        server = null
        super.onDestroy()
    }

    private fun ensureChannel() {
        if (Build.VERSION.SDK_INT < 26) return
        val nm = getSystemService(NotificationManager::class.java)
        val channel = NotificationChannel(
            CHANNEL,
            getString(R.string.radio_channel_name),
            NotificationManager.IMPORTANCE_LOW,
        )
        channel.setShowBadge(false)
        nm.createNotificationChannel(channel)
    }

    companion object {
        const val CHANNEL = "arelis-radio"
        const val NOTIF_ID = 27

        fun start(context: Context) {
            val intent = Intent(context, RadioService::class.java)
            if (Build.VERSION.SDK_INT >= 26) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }
    }
}
