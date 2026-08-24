package app.arelis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class HouseBeaconTest {
    @Test
    fun beaconRoundTrip() {
        val raw = encodeBeacon("inst0123456789ab", 8765)
        assertEquals("ARELIS1|inst0123456789ab|8765", raw)
        val got = decodeBeacon(raw)!!
        assertEquals("inst0123456789ab", got.instance)
        assertEquals(8765, got.port)
    }

    @Test
    fun junkIsNotABeacon() {
        assertNull(decodeBeacon(""))
        assertNull(decodeBeacon("nope"))
        assertNull(decodeBeacon("ARELIS1|inst|x"))
        assertNull(decodeBeacon("ARELIS1||8765"))
    }

    @Test
    fun storedUrlsStayFirstThenRewriteOntoThisSubnet() {
        val urls = candidateHouseUrls(
            stored = listOf("http://192.168.86.248:8765", "http://10.0.0.2:8765"),
            wifiIpv4 = "192.168.86.31",
            port = 8765,
        )
        assertEquals("http://192.168.86.248:8765", urls[0])
        assertTrue("http://192.168.86.2:8765" in urls)
        assertTrue(urls.contains("http://10.0.0.2:8765"))
    }

    @Test
    fun leavingAndComingBackRebuildsTheLastOctetOnANewSubnet() {
        val urls = candidateHouseUrls(
            stored = listOf("http://192.168.1.10:8765"),
            wifiIpv4 = "192.168.86.40",
            port = 8765,
        )
        assertTrue("http://192.168.86.10:8765" in urls)
        assertTrue("http://192.168.1.10:8765" in urls)
    }
}
