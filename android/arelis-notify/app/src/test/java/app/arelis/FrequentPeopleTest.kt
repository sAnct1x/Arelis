package app.arelis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class FrequentPeopleTest {
    @Test
    fun ranksByCountThenRecency() {
        val now = 1_000L
        val hits = listOf(
            "5551112222" to now,
            "5551113333" to now + 5,
            "5551112222" to now + 1,
            "15551112222" to now + 2,
            "911" to now + 9,
        )
        val ranked = rankAddressHits(hits, limit = 10)
        assertEquals(2, ranked.size)
        assertEquals("5551112222", ranked[0].address)
        assertEquals(3, ranked[0].count)
        assertEquals("5551113333", ranked[1].address)
    }

    @Test
    fun dropsShortCodes() {
        val ranked = rankAddressHits(listOf("12345" to 1L, "5551112222" to 2L))
        assertEquals(listOf("5551112222"), ranked.map { it.address })
    }

    @Test
    fun jsonHasPeopleArray() {
        val body = peopleToJson(listOf(PhonePerson("5551112222", "Robin", 4)))
        assertTrue(body.has("people"))
        assertEquals(1, body.getJSONArray("people").length())
        assertEquals("Robin", body.getJSONArray("people").getJSONObject(0).getString("name"))
    }
}
