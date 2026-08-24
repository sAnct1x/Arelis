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
        assertEquals("at the house", houseModeLabel(HouseMode.AtTheHouse, warmup = false, confirm = false))
        assertEquals(
            "at the house · allow waiting",
            houseModeLabel(HouseMode.AtTheHouse, warmup = false, confirm = true),
        )
        assertEquals("connecting…", houseModeLabel(HouseMode.Connecting, warmup = false, confirm = false))
        assertEquals("on the phone", houseModeLabel(HouseMode.OnThePhone, warmup = false, confirm = false))
        assertEquals("scan the qr on the pc", houseModeLabel(HouseMode.Pairing, warmup = false, confirm = false))
    }

    @Test
    fun phoneSubtitleSaysWhenTheBrainIsMissing() {
        val missing = GemmaUi(ready = false)
        assertEquals(
            "on the phone · no offline brain",
            talkSubtitle(HouseMode.OnThePhone, false, false, "", missing),
        )
        assertEquals(
            "on the phone",
            talkSubtitle(HouseMode.OnThePhone, false, false, "", GemmaUi(ready = true)),
        )
        assertEquals(
            "at the house · Physics",
            talkSubtitle(HouseMode.AtTheHouse, false, false, "Physics", GemmaUi(ready = true)),
        )
    }

    @Test
    fun gemmaPredicateErrorIsHuman() {
        val msg = humanGemmaError(NoSuchElementException("Array contains no element matching the predicate."))
        assertFalse(msg.contains("predicate"))
        assertTrue(msg.contains("LiteRT"))
        assertTrue(isPhoneBrainError("Array contains no element matching the predicate."))
    }

    @Test
    fun deadFocusDoesNotKeepADeletedChat() {
        val chats = listOf(
            ChatHint("general", ""),
            ChatHint("physics", "room-1"),
        )
        assertEquals("general", pickFocusChat("ghost", chats))
        assertEquals("physics", pickFocusChat("physics", chats))
        assertEquals("", pickFocusChat("ghost", listOf(ChatHint("physics", "room-1"))))
    }

    @Test
    fun missingChatHttpIsHuman() {
        val body = """{"ok": false, "error": "No conversation '07275e64c0a54e42bea8431bbebf0344'."}"""
        assertTrue(isMissingChatFailure(404, body))
        assertEquals("That chat is gone.", houseErrorMessage(404, body))
        assertFalse(houseErrorMessage(404, body).contains("07275"))
    }

    @Test
    fun pocketTitleUsesTheLastThingYouSaid() {
        assertEquals("on the phone", pocketThreadTitle(emptyList()))
        assertEquals(
            "bring milk",
            pocketThreadTitle(
                listOf(
                    TalkLine("user", "hi"),
                    TalkLine("assistant", "hey"),
                    TalkLine("user", "bring milk"),
                ),
            ),
        )
    }

    @Test
    fun phoneSeatIsNotThePcSeat() {
        assertTrue(sameSeat("abc", "abc"))
        assertFalse(sameSeat("phone", "pc-room"))
        assertFalse(sameSeat("", "pc-room"))
    }

    @Test
    fun englishIsFirstThenAlphabetical() {
        assertEquals("en", TalkLanguage.all.first().code)
        assertEquals(
            listOf("chinese", "french", "japanese", "korean", "spanish"),
            TalkLanguage.all.drop(1).map { it.label },
        )
        assertEquals("en", TalkLanguage.normalize("English"))
        assertEquals("zh", TalkLanguage.normalize("zh-CN"))
        assertEquals("", TalkLanguage.instruction("en"))
        assertTrue(TalkLanguage.instruction("zh").contains("Chinese"))
    }

    @Test
    fun gemmaKeepsTheHouseThread() {
        val lines = listOf(
            TalkLine("user", "we were talking about dinner"),
            TalkLine("assistant", "pasta tonight"),
            TalkLine("user", "and dessert"),
        )
        val block = gemmaHistoryBlock(priorTalkLines(lines, "and dessert"))
        assertTrue(block.contains("dinner"))
        assertTrue(block.contains("pasta tonight"))
        assertFalse(block.contains("and dessert"))
        assertTrue(block.contains("Continue it"))
    }

    @Test
    fun cameraSampleKeepsEnoughPixelsForVision() {
        assertEquals(1, CapturePhoto.sampleSize(1200, 800))
        assertEquals(2, CapturePhoto.sampleSize(4000, 3000))
        assertEquals(1, CapturePhoto.sampleSize(1600, 1600))
        assertTrue(pocketFileReply().contains("can't open files"))
        assertFalse(pocketFileReply().contains("can't see photos"))
        assertTrue(
            phoneIdleBody(HouseMode.OnThePhone, GemmaUi(ready = true)).contains("photos"),
        )
        assertTrue(isImageAttach("dinner.heic", ""))
        assertTrue(isImageAttach("x", "image/jpeg"))
        assertFalse(isImageAttach("notes.pdf", "application/pdf"))
    }
}
