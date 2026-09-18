package app.arelis

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.ListenableWorker
import androidx.work.WorkerParameters

class InboundWorker(
    context: Context,
    params: WorkerParameters,
) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result = flush(applicationContext)

    companion object {
        const val UNIQUE = "arelis-inbound-flush"

        fun flush(context: Context): ListenableWorker.Result {
            val prefs = Prefs(context)
            if (!prefs.readyToTalk) return Result.success()
            val queue = InboundQueue(context)
            val remaining = mutableListOf<QueuedInbound>()
            var client = ArelisClient.fromPrefs(prefs)
            var reached = false
            for (item in queue.snapshot()) {
                val image = item.imageJpeg.ifBlank { null }
                val sent = try {
                    client.postInbound(item.id, item.from, item.body, item.timeIso, image)
                    true
                } catch (_: Exception) {
                    if (!reached) {
                        reached = HouseReach.recover(context, prefs)
                        if (reached) client = ArelisClient.fromPrefs(prefs)
                    }
                    if (reached) {
                        try {
                            client.postInbound(item.id, item.from, item.body, item.timeIso, image)
                            true
                        } catch (_: Exception) {
                            false
                        }
                    } else {
                        false
                    }
                }
                if (!sent) remaining.add(item.copy(tries = item.tries + 1))
            }
            queue.replaceAll(remaining)
            return if (remaining.isEmpty()) Result.success() else Result.retry()
        }
    }
}
