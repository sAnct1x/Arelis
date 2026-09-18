package app.arelis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class LanAdvertiseTest {
    @Test
    fun zeroAddressIsBindOnly() {
        assertNull(advertiseIpv4(null))
        assertNull(advertiseIpv4(""))
        assertNull(advertiseIpv4("0.0.0.0"))
        assertNull(advertiseIpv4("127.0.0.1"))
        assertEquals("192.168.1.20", advertiseIpv4("192.168.1.20"))
    }
}
