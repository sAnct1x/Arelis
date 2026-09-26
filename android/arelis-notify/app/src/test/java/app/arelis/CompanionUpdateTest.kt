package app.arelis

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CompanionUpdateTest {
    @Test
    fun newerHouseCodeIsAnUpdate() {
        assertTrue(companionUpdateAvailable(5, 6))
        assertFalse(companionUpdateAvailable(6, 6))
        assertFalse(companionUpdateAvailable(7, 6))
        assertFalse(companionUpdateAvailable(6, 0))
    }

    @Test
    fun parseManifestReadsApkAndGemma() {
        val raw = JSONObject(
            """
            {
              "arelis": "0.2.9",
              "apk": {
                "version_code": 6,
                "version_name": "0.3.3",
                "sha256": "ab",
                "size": 12000000,
                "signed": "debug"
              },
              "expected": {"version_code": 6, "version_name": "0.3.3"},
              "gemma": {"available": true}
            }
            """.trimIndent(),
        )
        val manifest = CompanionManifest.parse(raw)
        assertEquals("0.2.9", manifest.arelisVersion)
        assertEquals(6, manifest.houseCode)
        assertEquals("0.3.3", manifest.houseName)
        assertEquals(12_000_000L, manifest.size)
        assertTrue(manifest.gemmaAvailable)
        val offer = manifest.offerFor(phoneCode = 5, dismissedCode = 0)
        assertEquals(6, offer.houseCode)
        assertFalse(offer.later)
        assertFalse(offer.staleNoApk)
        val ui = offer.toUi(phoneCode = 5, phoneName = "0.3.2")
        assertTrue(ui.available)
        assertEquals("12 MB", ui.sizeText)
    }

    @Test
    fun laterHidesTheSameHouseCode() {
        val manifest = CompanionManifest.parse(
            JSONObject("""{"apk":{"version_code":6,"version_name":"0.3.3","size":1}}"""),
        )
        val hidden = manifest.offerFor(phoneCode = 5, dismissedCode = 6)
        assertTrue(hidden.later)
        assertFalse(hidden.toUi(phoneCode = 5).available)
    }

    @Test
    fun missingApkWithNewerExpectedIsStale() {
        val manifest = CompanionManifest.parse(
            JSONObject("""{"expected":{"version_code":6,"version_name":"0.3.3"},"gemma":{"available":false}}"""),
        )
        val offer = manifest.offerFor(phoneCode = 5, dismissedCode = 0)
        assertTrue(offer.staleNoApk)
        assertFalse(offer.toUi(phoneCode = 5).available)
        assertTrue(offer.toUi(phoneCode = 5).staleNoApk)
    }

    @Test
    fun sameOrOlderHouseIsNotAnUpdate() {
        val manifest = CompanionManifest.parse(
            JSONObject("""{"apk":{"version_code":5,"version_name":"0.3.2"}}"""),
        )
        val ui = manifest.offerFor(phoneCode = 6, dismissedCode = 0).toUi(phoneCode = 6)
        assertFalse(ui.available)
        assertFalse(ui.staleNoApk)
    }

    @Test
    fun installStartsDownloadAndLaterHides() {
        val started = CompanionUpdate(houseCode = 6, houseName = "0.3.3")
            .reduce(CompanionEvent.Install)
        assertTrue(started.downloading)
        val hidden = started.reduce(CompanionEvent.Later)
        assertTrue(hidden.later)
        assertFalse(hidden.downloading)
    }
}
