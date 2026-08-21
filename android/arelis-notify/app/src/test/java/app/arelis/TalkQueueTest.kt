package app.arelis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class TalkQueueTest {
    @Test
    fun takeClearsAndRestorePutsRowsBack() {
        val file = File.createTempFile("talk", ".json")
        val queue = TalkQueue(file)
        queue.add("user", "hi")
        queue.add("assistant", "hello from the plane")
        val rows = queue.take()
        assertEquals(2, rows.size)
        assertTrue(queue.isEmpty())
        queue.restore(rows)
        assertEquals(listOf("user", "assistant"), queue.take().map { it.role })
        file.delete()
    }

    @Test
    fun skipsBlankAndCapsAtForty() {
        val file = File.createTempFile("talk", ".json")
        val queue = TalkQueue(file)
        queue.add("user", "   ")
        queue.add("system", "nope")
        repeat(50) { i -> queue.add("user", "m$i") }
        val rows = queue.take()
        assertEquals(40, rows.size)
        assertEquals("m10", rows.first().text)
        file.delete()
    }
}
