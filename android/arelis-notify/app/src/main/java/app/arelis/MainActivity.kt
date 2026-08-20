package app.arelis

import android.Manifest
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.app.ActivityCompat
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import java.util.concurrent.Executors

class MainActivity : ComponentActivity() {
    private lateinit var prefs: Prefs
    private val io = Executors.newSingleThreadExecutor()
    private var wifiWatcher: WifiWatcher? = null
    private var headline by mutableStateOf("Waiting to pair.")
    private var grants by mutableStateOf(
        GrantState(restrictedHint = true, sms = false, notifications = false, battery = false, camera = false),
    )
    private var paste by mutableStateOf("")
    private var busy by mutableStateOf(false)
    private var paired by mutableStateOf(false)

    private val scanLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { result ->
        val payload = result.data?.getStringExtra(ScanActivity.EXTRA_PAYLOAD).orEmpty()
        if (payload.isNotBlank()) applyTicket(payload)
    }

    private val smsPermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { refresh() }

    private val notifyPermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { refresh() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        if (Build.VERSION.SDK_INT >= 33) {
            notifyPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        wifiWatcher = WifiWatcher(this).also { it.start() }
        if (prefs.paired) {
            RadioService.start(this)
            WorkManager.getInstance(this).enqueueUniqueWork(
                InboundWorker.UNIQUE,
                ExistingWorkPolicy.KEEP,
                OneTimeWorkRequestBuilder<InboundWorker>().build(),
            )
        }
        setContent {
            ArelisTheme {
                HomeScreen(
                    state = HomeState(headline, grants, paste, busy, paired),
                    onOpenRestricted = { openAppDetails(this) },
                    onGrantSms = {
                        smsPermission.launch(Manifest.permission.SEND_SMS)
                    },
                    onOpenNotifications = { openNotificationAccess(this) },
                    onOpenBattery = { openBatterySettings(this) },
                    onScan = {
                        scanLauncher.launch(Intent(this, ScanActivity::class.java))
                    },
                    onPasteChange = { paste = it },
                    onPasteApply = {
                        if (paste.isNotBlank()) applyTicket(paste)
                    },
                )
            }
        }
    }

    override fun onResume() {
        super.onResume()
        refresh()
    }

    override fun onDestroy() {
        wifiWatcher?.stop()
        super.onDestroy()
    }

    private fun refresh() {
        grants = grantState(this)
        paired = prefs.paired
        headline = when {
            prefs.paired && grants.notifications && grants.sms && grants.battery ->
                "Paired. Radio on. Google Messages still handles the tapping."
            prefs.paired && (!grants.sms || !grants.notifications) ->
                "Paired, but a grant is still missing — restricted settings, then SMS and notification access."
            prefs.paired && !grants.battery ->
                "Paired. Set battery to Unrestricted or inbound will miss when the screen is off."
            prefs.readyToTalk ->
                "PC address is saved. Scan again if ping fails after DHCP moved."
            else ->
                "Waiting to pair. Open Settings → Notify on the PC and scan the QR."
        }
    }

    private fun applyTicket(raw: String) {
        if (busy) return
        val ticket = try {
            parsePairTicket(raw)
        } catch (exc: Exception) {
            Toast.makeText(this, exc.message ?: "Could not read pairing.", Toast.LENGTH_LONG).show()
            return
        }
        busy = true
        headline = "Pairing…"
        prefs.token = ticket.token
        prefs.instanceId = ticket.instance
        prefs.baseUrl = ticket.urls.first()
        prefs.deviceKey
        prefs.listenUrl = ""
        RadioService.start(this)
        io.execute {
            val error = runCatching { pairNow(ticket) }.exceptionOrNull()
            runOnUiThread {
                busy = false
                if (error != null) {
                    headline = error.message ?: "Pairing failed."
                    Toast.makeText(this, headline, Toast.LENGTH_LONG).show()
                } else {
                    paste = ""
                    refresh()
                    ActivityCompat.requestPermissions(
                        this,
                        arrayOf(Manifest.permission.SEND_SMS),
                        0,
                    )
                    Toast.makeText(this, "Paired.", Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    private fun pairNow(ticket: PairTicket) {
        val listen = waitForListenUrl(2_500)
            ?: throw IllegalStateException("No Wi-Fi address yet. Same network as the PC?")
        prefs.listenUrl = listen
        var last: Exception? = null
        for (url in ticket.urls) {
            prefs.baseUrl = url
            try {
                ArelisClient(url, ticket.token).pair(
                    instance = ticket.instance,
                    pair = ticket.pair,
                    listenUrl = listen,
                    deviceKey = prefs.deviceKey,
                )
                last = null
                break
            } catch (exc: Exception) {
                last = exc
            }
        }
        if (last != null) throw last
        prefs.paired = true
        RadioService.start(this)
        WorkManager.getInstance(this).enqueueUniqueWork(
            InboundWorker.UNIQUE,
            ExistingWorkPolicy.KEEP,
            OneTimeWorkRequestBuilder<InboundWorker>().build(),
        )
    }

    private fun waitForListenUrl(timeoutMs: Long): String? {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val url = prefs.listenUrl
            if (url.isNotBlank()) return url
            Thread.sleep(50)
        }
        return listenUrlFor(this, prefs.listenPort)
    }
}
