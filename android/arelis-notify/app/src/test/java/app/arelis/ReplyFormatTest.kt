package app.arelis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ReplyFormatTest {
    private val ink = ReplyInk(
        text = 0xFFF8F1EA,
        dim = 0xFFC4906E,
        codeFill = 0xB40A0807,
        accent = 0xFFFF7A22,
    )

    @Test
    fun boldHidesTheStars() {
        val doc = formatReply("see **bold** now", ink)
        assertEquals("see bold now", doc.visible)
        val hit = doc.runs.first { it.text == "bold" }
        assertTrue(hit.bold)
        assertFalse(hit.italic)
    }

    @Test
    fun italicsHidesTheStars() {
        val doc = formatReply("a *soft* word", ink)
        assertEquals("a soft word", doc.visible)
        val hit = doc.runs.first { it.text == "soft" }
        assertTrue(hit.italic)
        assertFalse(hit.bold)
    }

    @Test
    fun boldItalicsTogether() {
        val doc = formatReply("***both***", ink)
        assertEquals("both", doc.visible)
        assertTrue(doc.runs.single().bold)
        assertTrue(doc.runs.single().italic)
    }

    @Test
    fun inlineCodeIsMonospace() {
        val doc = formatReply("use `code` here", ink)
        assertEquals("use code here", doc.visible)
        val hit = doc.runs.first { it.text == "code" }
        assertTrue(hit.code)
        assertEquals(ink.codeFill, hit.codeFill)
        assertFalse(hit.bold)
    }

    @Test
    fun fencedCodeStaysABlock() {
        val doc = formatReply("before\n```\n**not bold**\n```\nafter", ink)
        assertEquals("before\n**not bold**\nafter", doc.visible)
        val block = doc.runs.first { it.codeBlock }
        assertEquals("**not bold**", block.text)
        assertTrue(block.code)
        assertFalse(block.bold)
        assertEquals(ink.codeFill, block.codeFill)
    }

    @Test
    fun headingDropsTheMarks() {
        val doc = formatReply("# Title", ink)
        assertEquals("Title", doc.visible)
        val hit = doc.runs.first { it.text == "Title" }
        assertEquals(1, hit.heading)
        assertTrue(hit.bold)
    }

    @Test
    fun bulletsUseARealBullet() {
        val doc = formatReply("- one\n- two", ink)
        assertEquals("• one\n• two", doc.visible)
        assertTrue(doc.runs.any { it.list })
        assertFalse(doc.visible.contains("*"))
    }

    @Test
    fun numberedListKeepsTheNumbers() {
        val doc = formatReply("1. first\n2. second", ink)
        assertEquals("1. first\n2. second", doc.visible)
        assertTrue(doc.runs.any { it.list })
    }

    @Test
    fun httpsLinkIsTappable() {
        val doc = formatReply("see [docs](https://example.com/a)", ink)
        assertEquals("see docs", doc.visible)
        val hit = doc.runs.first { it.text == "docs" }
        assertEquals("https://example.com/a", hit.link)
        assertEquals(ink.accent, hit.linkColor)
    }

    @Test
    fun nonHttpLinkStaysPlain() {
        val doc = formatReply("see [docs](javascript:alert(1))", ink)
        assertTrue(doc.visible.contains("[docs]"))
        assertTrue(doc.runs.all { it.link == null })
    }

    @Test
    fun nestedBoldAndItalic() {
        val doc = formatReply("**see *this* now**", ink)
        assertEquals("see this now", doc.visible)
        assertTrue(doc.runs.first { it.text == "see " }.bold)
        val inner = doc.runs.first { it.text == "this" }
        assertTrue(inner.bold)
        assertTrue(inner.italic)
        assertTrue(doc.runs.first { it.text == " now" }.bold)
    }

    @Test
    fun unclosedMarkerStaysPlain() {
        val doc = formatReply("hello **nope", ink)
        assertEquals("hello **nope", doc.visible)
        assertFalse(doc.runs.any { it.bold })
    }

    @Test
    fun plainTextIsUnchanged() {
        val doc = formatReply("just words", ink)
        assertEquals("just words", doc.visible)
        val hit = doc.runs.single()
        assertFalse(hit.bold)
        assertFalse(hit.italic)
        assertFalse(hit.code)
        assertFalse(hit.codeBlock)
        assertEquals(0, hit.heading)
        assertNull(hit.link)
        assertFalse(hit.quote)
    }

    @Test
    fun blockQuoteDropsTheMark() {
        val doc = formatReply("> quoted line", ink)
        assertEquals("quoted line", doc.visible)
        assertTrue(doc.runs.first { it.text == "quoted line" }.quote)
    }
}
