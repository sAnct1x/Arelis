package app.arelis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TalkRulesTest {
    @Test
    fun talkDoesNotNeedARadioUrl() {
        assertTrue(readyToTalk("http://pc:8765", "token"))
        assertFalse(readyToTalk("http://pc:8765", ""))
        assertFalse(readyToTalk("", "token"))
    }

    @Test
    fun smsAndMailNeverBecomeArelisPings() {
        assertFalse(shouldPingNotice("sms"))
        assertFalse(shouldPingNotice("email"))
        assertTrue(shouldPingNotice("allow"))
        assertTrue(shouldPingNotice("job"))
    }

    @Test
    fun tappingTheSameVoiceLatchTurnsItOff() {
        assertEquals("dictate", toggleVoiceMode("off", "dictate"))
        assertEquals("off", toggleVoiceMode("dictate", "dictate"))
        assertEquals("conversation", toggleVoiceMode("dictate", "conversation"))
    }

    @Test
    fun dictateLandsInTheBoxAndDoesNotSend() {
        val started = VoiceDraft(draft = "typed").start("dictate")
        val (final, send) = started.finalHeard("spoken")
        assertEquals("typed spoken", final.draft)
        assertFalse(send)
    }

    @Test
    fun conversationSendsWhenYouStopTalking() {
        val started = VoiceDraft().start("conversation")
        val (final, send) = started.finalHeard("what's the weather")
        assertEquals("what's the weather", final.draft)
        assertTrue(send)
    }

    @Test
    fun houseLabelNamesAllowWithoutLyingAboutTheMode() {
        assertEquals("At the house", houseModeLabel(HouseMode.AtTheHouse, warmup = false, confirm = false))
        assertEquals(
            "At the house · Allow waiting",
            houseModeLabel(HouseMode.AtTheHouse, warmup = false, confirm = true),
        )
        assertEquals("On the phone", houseModeLabel(HouseMode.OnThePhone, warmup = false, confirm = false))
    }
}
