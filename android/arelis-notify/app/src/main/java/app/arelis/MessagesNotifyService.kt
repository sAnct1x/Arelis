package app.arelis

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Log
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import java.time.Instant
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors

/**
 * Forwards Google Messages notifications to Arelis over the LAN.
 *
 * RCS and SMS both surface here when the user has notifications enabled for
 * that conversation — which is the durable bridge a SEND_SMS radio cannot provide.
 */
class MessagesNotifyService : NotificationListenerService() {
    private val executor = Executors.newSingleThreadExecutor()
    private val recentIds = ConcurrentHashMap<String, Long>()

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        if (sbn == null) return
        if (sbn.packageName != MESSAGES_PACKAGE) return
        val prefs = Prefs(this)
        if (!prefs.enabled) return
        if (!prefs.readyToTalk) return
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
        if (text.isEmpty()) return

        val baseKey = sbn.key?.takeIf { it.isNotBlank() }
            ?: "${sbn.packageName}:${sbn.id}:${title.hashCode()}"
        val id = "$baseKey:${text.hashCode()}"
        val now = System.currentTimeMillis()
        prune(now)
        if (recentIds.putIfAbsent(id, now) != null) return

        val timeIso = Instant.ofEpochMilli(sbn.postTime).toString()
        val from = title.ifEmpty { "(unknown)" }
        executor.execute {
            try {
                ArelisClient(prefs.baseUrl, prefs.token).postInbound(id, from, text, timeIso)
            } catch (exc: Exception) {
                Log.w(TAG, "POST failed, queued: $exc")
                InboundQueue(this).enqueue(id, from, text, timeIso)
                WorkManager.getInstance(this).enqueueUniqueWork(
                    InboundWorker.UNIQUE,
                    ExistingWorkPolicy.REPLACE,
                    OneTimeWorkRequestBuilder<InboundWorker>().build(),
                )
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
