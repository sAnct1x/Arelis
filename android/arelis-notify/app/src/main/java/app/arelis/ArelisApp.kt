package app.arelis

import android.app.Application
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager

class ArelisApp : Application() {
    override fun onCreate() {
        super.onCreate()
        WorkManager.getInstance(this).enqueueUniqueWork(
            InboundWorker.UNIQUE,
            ExistingWorkPolicy.KEEP,
            OneTimeWorkRequestBuilder<InboundWorker>().build(),
        )
    }
}
