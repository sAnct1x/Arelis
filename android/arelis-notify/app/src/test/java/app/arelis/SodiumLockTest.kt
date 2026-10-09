package app.arelis

import androidx.compose.ui.graphics.Color
import org.junit.Assert.assertEquals
import org.junit.Test

class SodiumLockTest {
    @Test
    fun sodiumThemeMatchesTheDesktopLockLines() {
        assertEquals(SodiumLock.bg0, Color(DeskThemes.sodium.bg0))
        assertEquals(SodiumLock.accent, Color(DeskThemes.sodium.accent))
        assertEquals(SodiumLock.accent2, Color(DeskThemes.sodium.accent2))
    }
}
