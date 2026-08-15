package app.arelis.notify

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Log
import java.time.Instant
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import kotlin.math.min

/**
 * Forwards Google Messages notifications to Arelis over the LAN.
 *
 * RCS and SMS both surface here when the user has notifications enabled for
 * that conversation — which is the durable bridge SMSGate cannot provide.
 */
class MessagesNotifyService : NotificationListenerService() {
    private val executor = Executors.newSingleThreadExecutor()
    private val recentIds = ConcurrentHashMap<String, Long>()

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        if (sbn == null) return
        if (sbn.packageName != MESSAGES_PACKAGE) return
        val prefs = Prefs(this)
        if (!prefs.enabled) return
        if (prefs.baseUrl.isBlank() || prefs.token.isBlank()) return
        if (sbn.isOngoing) return

        val extras = sbn.notification.extras
        val title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString()?.trim().orEmpty()
        val text = sequenceOf(
            extras.getCharSequence(Notification.EXTRA_BIG_TEXT),
            extras.getCharSequence(Notification.EXTRA_TEXT),
            extras.getCharSequence(Notification.EXTRA_SUB_TEXT),
        ).mapNotNull { it?.toString()?.trim() }
            .firstOrNull { it.isNotEmpty() }
            .orEmpty()

        if (title.isEmpty() && text.isEmpty()) return
        // Group summaries / "X new messages" without a body are noisy.
        if (text.isEmpty()) return

        val baseKey = sbn.key?.takeIf { it.isNotBlank() }
            ?: "${sbn.packageName}:${sbn.id}:${title.hashCode()}"
        // Include body hash so conversation *updates* that reuse the same
        // notification key still forward (otherwise looks like random misses).
        val id = "$baseKey:${text.hashCode()}"
        val now = System.currentTimeMillis()
        prune(now)
        if (recentIds.putIfAbsent(id, now) != null) return

        val client = ArelisClient(prefs.baseUrl, prefs.token)
        val timeIso = Instant.ofEpochMilli(sbn.postTime).toString()
        executor.execute {
            var attempt = 0
            var delayMs = 1_000L
            while (attempt < 4) {
                try {
                    client.postInbound(id, title.ifEmpty { "(unknown)" }, text, timeIso)
                    return@execute
                } catch (exc: Exception) {
                    Log.w(TAG, "POST failed attempt=${attempt + 1}: $exc")
                    attempt += 1
                    try {
                        Thread.sleep(delayMs)
                    } catch (_: InterruptedException) {
                        return@execute
                    }
                    delayMs = min(delayMs * 2, 8_000L)
                }
            }
        }
    }

    private fun prune(now: Long) {
        val cutoff = now - 10 * 60_000L
        recentIds.entries.removeIf { it.value < cutoff }
    }

    companion object {
        private const val TAG = "ArelisNotify"
        const val MESSAGES_PACKAGE = "com.google.android.apps.messaging"
    }
}
