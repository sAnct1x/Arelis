package app.arelis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import kotlin.io.path.createTempDirectory

class InboundQueueTest {
    @Test
    fun sameIdIsNotQueuedTwice() {
        val file = File.createTempFile("inbound", ".json")
        val queue = InboundQueue(file)
        queue.enqueue("m1", "Robin", "hi", "2026-08-21T00:00:00Z")
        queue.enqueue("m1", "Robin", "hi again", "2026-08-21T00:01:00Z")
        assertEquals(1, queue.snapshot().size)
        assertEquals("hi", queue.snapshot()[0].body)
        file.delete()
    }

    @Test
    fun dropsEntriesOlderThanTheWindow() {
        val dir = createTempDirectory("inbound").toFile()
        val file = File(dir, "inbound_queue.json")
        var now = 1_000L
        val queue = InboundQueue(file, nowMs = { now }, maxAgeMs = 1_000L)
        queue.enqueue("old", "Robin", "yesterday", "t")
        now = 10_000L
        assertTrue(queue.snapshot().isEmpty())
        queue.enqueue("new", "Robin", "now", "t")
        assertEquals(listOf("new"), queue.snapshot().map { it.id })
        dir.deleteRecursively()
    }

    @Test
    fun emptyFileIsAnEmptyQueue() {
        val file = File.createTempFile("inbound", ".json")
        file.writeText("")
        assertTrue(InboundQueue(file).isEmpty())
        file.delete()
    }
}
