package app.arelis

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Log
import androidx.core.app.NotificationCompat
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
        val styleText = runCatching {
            NotificationCompat.MessagingStyle
                .extractMessagingStyleFromNotification(sbn.notification)
                ?.messages
                ?.lastOrNull()
                ?.text
                ?.toString()
                .orEmpty()
        }.getOrDefault("")
        var text = NotifyCopy.pickBody(
            styleText = styleText,
            extraText = extras.getCharSequence(Notification.EXTRA_TEXT)?.toString().orEmpty(),
            bigText = extras.getCharSequence(Notification.EXTRA_BIG_TEXT)?.toString().orEmpty(),
            subText = extras.getCharSequence(Notification.EXTRA_SUB_TEXT)?.toString().orEmpty(),
        )
        val imageJpeg = NotifyPicture.jpegBase64(sbn.notification, this)

        if (title.isEmpty() && text.isEmpty() && imageJpeg == null) return
        if (text.isEmpty() && imageJpeg != null) text = "Photo"
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
                ArelisClient.fromPrefs(prefs).postInbound(
                    id, from, text, timeIso, imageJpeg,
                )
            } catch (exc: Exception) {
                Log.w(TAG, "POST failed, queued: $exc")
                InboundQueue(this).enqueue(id, from, text, timeIso, imageJpeg)
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
