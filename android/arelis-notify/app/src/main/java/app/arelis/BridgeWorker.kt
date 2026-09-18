package app.arelis

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters

class BridgeWorker(
    context: Context,
    params: WorkerParameters,
) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val prefs = Prefs(applicationContext)
        if (!prefs.readyToTalk) return Result.success()
        HouseReach.recover(applicationContext, prefs)
        return InboundWorker.flush(applicationContext)
    }
}
