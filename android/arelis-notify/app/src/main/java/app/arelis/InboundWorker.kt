package app.arelis

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters

class InboundWorker(
    context: Context,
    params: WorkerParameters,
) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val prefs = Prefs(applicationContext)
        if (!prefs.readyToTalk) return Result.success()
        val queue = InboundQueue(applicationContext)
        val remaining = mutableListOf<QueuedInbound>()
        val client = ArelisClient(prefs.baseUrl, prefs.token)
        for (item in queue.snapshot()) {
            try {
                client.postInbound(item.id, item.from, item.body, item.timeIso)
            } catch (_: Exception) {
                remaining.add(item.copy(tries = item.tries + 1))
            }
        }
        queue.replaceAll(remaining)
        return if (remaining.isEmpty()) Result.success() else Result.retry()
    }

    companion object {
        const val UNIQUE = "arelis-inbound-flush"
    }
}
