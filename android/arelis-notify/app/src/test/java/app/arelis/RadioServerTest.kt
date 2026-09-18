package app.arelis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Base64

class RadioServerTest {
    @Test
    fun missingKeyIsUnauthorized() {
        assertFalse(radioAuthorized(emptyMap(), ""))
        assertFalse(radioAuthorized(mapOf("authorization" to "Bearer secret"), ""))
        assertFalse(radioAuthorized(emptyMap(), "secret"))
    }

    @Test
    fun bearerMatch() {
        assertTrue(radioAuthorized(mapOf("authorization" to "Bearer secret"), "secret"))
    }

    @Test
    fun bearerMismatchIsRejected() {
        assertFalse(radioAuthorized(mapOf("authorization" to "Bearer other"), "secret"))
        assertFalse(radioAuthorized(mapOf("authorization" to "Bearer "), "secret"))
    }

    @Test
    fun basicArelisKeyMatches() {
        val b64 = Base64.getEncoder().encodeToString("arelis:secret".toByteArray())
        assertTrue(radioAuthorized(mapOf("authorization" to "Basic $b64"), "secret"))
    }

    @Test
    fun xArelisTokenMatches() {
        assertTrue(radioAuthorized(mapOf("x-arelis-token" to "secret"), "secret"))
        assertFalse(radioAuthorized(mapOf("x-arelis-token" to "other"), "secret"))
    }

    @Test
    fun healthRoute() {
        assertEquals(200, radioRoute("GET", "/health"))
        assertEquals(200, radioRoute("GET", "/"))
        assertEquals(200, radioRoute("POST", "/messages"))
    }

    @Test
    fun unknownPathIs404() {
        assertEquals(404, radioRoute("GET", "/nope"))
        assertEquals(404, radioRoute("DELETE", "/messages"))
        assertEquals(404, radioRoute("POST", "/health"))
    }
}
