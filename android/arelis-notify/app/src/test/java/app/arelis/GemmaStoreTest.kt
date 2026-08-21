package app.arelis

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.io.RandomAccessFile

class GemmaStoreTest {
    @Test
    fun aTinyFileIsNotReady() {
        val dest = File.createTempFile("gemma", ".litertlm")
        dest.writeBytes(ByteArray(1024))
        assertFalse(GemmaStore.ready(dest))
        dest.delete()
    }

    @Test
    fun aMissingFileIsNotReady() {
        assertFalse(GemmaStore.ready(File("no-such-gemma.litertlm")))
    }

    @Test
    fun aFileOverTheFloorIsReady() {
        val dest = File.createTempFile("gemma", ".litertlm")
        RandomAccessFile(dest, "rw").use { it.setLength(GemmaStore.MIN_BYTES + 1) }
        assertTrue(GemmaStore.ready(dest))
        dest.delete()
    }
}
