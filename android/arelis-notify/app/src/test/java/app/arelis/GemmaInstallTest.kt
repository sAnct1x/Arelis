package app.arelis

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class GemmaInstallTest {
    @Test
    fun installOnWifiStartsTheDownload() {
        val next = GemmaInstall(onWifi = true).reduce(GemmaEvent.Install)
        assertTrue(next.downloading)
        assertFalse(next.confirmCellular)
        assertFalse(next.waitWifi)
        assertFalse(next.later)
    }

    @Test
    fun installOnCellularAsksBeforeUsingData() {
        val next = GemmaInstall(onWifi = false).reduce(GemmaEvent.Install)
        assertTrue(next.confirmCellular)
        assertFalse(next.downloading)
    }

    @Test
    fun waitForWifiQueuesUntilWifiAppears() {
        val queued = GemmaInstall(onWifi = false).reduce(GemmaEvent.WaitWifi)
        assertTrue(queued.waitWifi)
        assertFalse(queued.downloading)
        val started = queued.reduce(GemmaEvent.WifiAppeared)
        assertTrue(started.downloading)
        assertFalse(started.waitWifi)
    }

    @Test
    fun waitForWifiWhileAlreadyOnWifiStartsNow() {
        val next = GemmaInstall(onWifi = true).reduce(GemmaEvent.WaitWifi)
        assertTrue(next.downloading)
        assertFalse(next.waitWifi)
    }

    @Test
    fun useDataStartsEvenOffWifi() {
        val next = GemmaInstall(onWifi = false, confirmCellular = true)
            .reduce(GemmaEvent.UseData)
        assertTrue(next.downloading)
        assertFalse(next.confirmCellular)
        assertFalse(next.later)
    }

    @Test
    fun laterHidesTheCardAndShowBringsItBack() {
        val hidden = GemmaInstall().reduce(GemmaEvent.Later)
        assertTrue(hidden.later)
        assertFalse(hidden.waitWifi)
        val shown = hidden.reduce(GemmaEvent.Show)
        assertFalse(shown.later)
    }

    @Test
    fun alreadyReadyNeverStartsADownload() {
        val next = GemmaInstall(ready = true, onWifi = false)
            .reduce(GemmaEvent.Install)
        assertFalse(next.downloading)
        assertFalse(next.confirmCellular)
    }
}
