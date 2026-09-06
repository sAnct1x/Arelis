package app.arelis

import org.junit.Assert.assertEquals
import org.junit.Test

class NotifyCopyTest {
    @Test
    fun messagingStyleBeatsBigTextDump() {
        assertEquals(
            "https://maps.app.goo.gl/park",
            NotifyCopy.pickBody(
                styleText = "https://maps.app.goo.gl/park",
                extraText = "Robin: https://maps.app.goo.gl/park",
                bigText = "yesterday\nhttps://maps.app.goo.gl/park",
            ),
        )
    }

    @Test
    fun extraTextWhenStyleIsEmpty() {
        assertEquals(
            "on my way",
            NotifyCopy.pickBody(extraText = "on my way", bigText = "older dump"),
        )
    }

    @Test
    fun blankPartsAreSkipped() {
        assertEquals(
            "Photo",
            NotifyCopy.pickBody(styleText = "  ", extraText = "", bigText = "Photo"),
        )
    }
}
