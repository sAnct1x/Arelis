package app.arelis

/**
 * Offline-brain install. Wi-Fi is nicer; mobile data is allowed if you say so.
 * Pure so a unit test can fail the "2.6 GB on a plane" hypothesis without a phone.
 */
data class GemmaInstall(
    val ready: Boolean = false,
    val downloading: Boolean = false,
    val waitWifi: Boolean = false,
    val later: Boolean = false,
    val confirmCellular: Boolean = false,
    val onWifi: Boolean = true,
) {
    fun reduce(event: GemmaEvent): GemmaInstall {
        if (ready && event != GemmaEvent.BecameReady) {
            return copy(waitWifi = false, confirmCellular = false, downloading = false)
        }
        return when (event) {
            GemmaEvent.Install -> {
                val clear = copy(later = false)
                if (clear.onWifi) clear.startDownload() else clear.copy(confirmCellular = true)
            }
            GemmaEvent.WaitWifi -> {
                val queued = copy(confirmCellular = false, later = false, waitWifi = true)
                if (queued.onWifi) queued.startDownload() else queued
            }
            GemmaEvent.Later -> copy(
                confirmCellular = false,
                waitWifi = false,
                later = true,
            )
            GemmaEvent.UseData -> copy(later = false).startDownload()
            GemmaEvent.Show -> copy(later = false)
            GemmaEvent.WifiAppeared -> {
                val next = copy(onWifi = true)
                if (next.waitWifi) next.startDownload() else next
            }
            GemmaEvent.BecameReady -> copy(
                ready = true,
                downloading = false,
                waitWifi = false,
                confirmCellular = false,
                later = false,
            )
        }
    }

    fun toUi(progress: String = ""): GemmaUi = GemmaUi(
        ready = ready,
        downloading = downloading,
        progress = progress,
        waitWifi = waitWifi,
        onWifi = onWifi,
        later = later,
        confirmCellular = confirmCellular,
    )

    private fun startDownload(): GemmaInstall = copy(
        confirmCellular = false,
        waitWifi = false,
        later = false,
        downloading = true,
    )
}

enum class GemmaEvent {
    Install,
    WaitWifi,
    Later,
    UseData,
    Show,
    WifiAppeared,
    BecameReady,
}
