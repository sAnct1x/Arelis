package app.arelis

import android.content.Context
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit

/** Rediscover the PC and flush queued texts without opening the app. */
object BridgeKeepalive {
    const val UNIQUE = "arelis-bridge-keep"

    fun ensure(context: Context) {
        val req = PeriodicWorkRequestBuilder<BridgeWorker>(15, TimeUnit.MINUTES)
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build(),
            )
            .build()
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
            UNIQUE,
            ExistingPeriodicWorkPolicy.KEEP,
            req,
        )
    }
}
