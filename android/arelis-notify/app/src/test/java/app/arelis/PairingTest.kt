package app.arelis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class PairingTest {
    @Test
    fun pipeFormKeepsEveryLanUrl() {
        val ticket = parsePairTicket(
            "A1|inst-1|token-1|pair-1|http://192.168.1.4:8765|http://10.0.0.2:8765",
        )
        assertEquals("inst-1", ticket.instance)
        assertEquals("token-1", ticket.token)
        assertEquals("pair-1", ticket.pair)
        assertEquals(
            listOf("http://192.168.1.4:8765", "http://10.0.0.2:8765"),
            ticket.urls,
        )
    }

    @Test
    fun pipeFormRejectsAShortTicket() {
        assertThrows(IllegalArgumentException::class.java) {
            parsePairTicket("A1|inst|token")
        }
    }

    @Test
    fun jsonFormReadsUrlArrayAndSingleUrl() {
        val ticket = parsePairTicket(
            """
            {"instance":"i","token":"t","pair":"p",
             "url":"http://pc:8765",
             "urls":["http://192.168.1.4:8765"]}
            """.trimIndent(),
        )
        assertEquals("i", ticket.instance)
        assertTrue(ticket.urls[0] == "http://pc:8765")
        assertTrue("http://192.168.1.4:8765" in ticket.urls)
    }

    @Test
    fun pipeFormTreatsHttpsAsTheMailbox() {
        val ticket = parsePairTicket(
            "A1|inst-1|token-1|pair-1|http://192.168.1.4:8765|https://relay.example.com",
        )
        assertEquals("https://relay.example.com", ticket.relayUrl)
        assertEquals(listOf("http://192.168.1.4:8765"), ticket.lanUrls)
    }

    @Test
    fun jsonFormReadsRelayField() {
        val ticket = parsePairTicket(
            """
            {"instance":"i","token":"t","pair":"p",
             "url":"http://192.168.1.4:8765",
             "relay":"https://relay.example.com"}
            """.trimIndent(),
        )
        assertEquals("https://relay.example.com", ticket.relayUrl)
        assertEquals("http://192.168.1.4:8765", ticket.lanUrls[0])
    }

    @Test
    fun jsonFormRejectsAMissingToken() {
        assertThrows(IllegalArgumentException::class.java) {
            parsePairTicket("""{"instance":"i","pair":"p","url":"http://pc:8765"}""")
        }
    }
}
