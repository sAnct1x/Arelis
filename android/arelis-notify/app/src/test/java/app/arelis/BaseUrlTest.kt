package app.arelis

import org.junit.Assert.assertEquals
import org.junit.Test

class BaseUrlTest {
    @Test
    fun stripsInboundPingAndTrailingSlash() {
        assertEquals(
            "http://192.168.1.4:8765",
            ArelisClient.normalizeBaseUrl("http://192.168.1.4:8765/inbound/ping/"),
        )
    }

    @Test
    fun stripsMobileStatusFromAPastedTalkUrl() {
        assertEquals(
            "http://pc:8765",
            ArelisClient.normalizeBaseUrl("http://pc:8765/mobile/status"),
        )
    }

    @Test
    fun leavesABareIngestRootAlone() {
        assertEquals(
            "http://pc:8765",
            ArelisClient.normalizeBaseUrl("http://pc:8765"),
        )
    }
}
