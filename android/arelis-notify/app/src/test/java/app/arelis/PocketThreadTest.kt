package app.arelis

import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.File

class PocketThreadTest {
    @Test
    fun remembersTheHouseThreadAndGemmaLines() {
        val file = File.createTempFile("pocket", ".json")
        val thread = PocketThread(file)
        thread.replace(
            "s1",
            listOf(TalkLine("user", "from the desk"), TalkLine("assistant", "ok")),
        )
        thread.append("user", "from the plane")
        assertEquals("s1", thread.sessionId())
        assertEquals(
            listOf("from the desk", "ok", "from the plane"),
            thread.lines().map { it.text },
        )
        file.delete()
    }

    @Test
    fun keepSessionDoesNotWipeLines() {
        val file = File.createTempFile("pocket", ".json")
        val thread = PocketThread(file)
        thread.replace("old", listOf(TalkLine("user", "hi")))
        thread.keepSession("new")
        assertEquals("new", thread.sessionId())
        assertEquals(listOf("hi"), thread.lines().map { it.text })
        file.delete()
    }
}
