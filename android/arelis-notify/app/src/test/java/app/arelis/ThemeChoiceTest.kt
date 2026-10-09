package app.arelis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ThemeChoiceTest {
    @Test
    fun everyDesktopThemeExists() {
        assertEquals(listOf("sodium", "filament", "night"), DeskThemes.ids)
        for (id in DeskThemes.ids) {
            val palette = DeskThemes.byId.getValue(id)
            assertEquals(id, palette.id)
            assertTrue(palette.bg0 != 0L)
            assertTrue(palette.text != 0L)
            assertTrue(palette.accent != 0L)
        }
    }

    @Test
    fun themesAreVisiblyDifferent() {
        val sodium = DeskThemes.byId.getValue("sodium")
        val filament = DeskThemes.byId.getValue("filament")
        val night = DeskThemes.byId.getValue("night")
        assertNotEquals(sodium.bg0, filament.bg0)
        assertNotEquals(sodium.accent, filament.accent)
        assertNotEquals(sodium.bg0, night.bg0)
        assertNotEquals(sodium.accent, night.accent)
        assertNotEquals(filament.text, night.text)
    }

    @Test
    fun followSystemPicksTheDesktopDefaults() {
        assertEquals("sodium", DeskThemes.resolvedId(DeskThemes.FOLLOW, systemDark = false))
        assertEquals("sodium", DeskThemes.resolvedId(DeskThemes.FOLLOW, systemDark = true))
        assertEquals("sodium", DeskThemes.palette(DeskThemes.FOLLOW, systemDark = false).id)
        assertEquals("sodium", DeskThemes.palette(DeskThemes.FOLLOW, systemDark = true).id)
    }

    @Test
    fun namedChoiceIgnoresTheSystem() {
        assertEquals("night", DeskThemes.resolvedId("night", systemDark = false))
        assertEquals("filament", DeskThemes.resolvedId("filament", systemDark = true))
    }

    @Test
    fun savedChoiceRoundTrips() {
        assertEquals(DeskThemes.FOLLOW, DeskThemes.normalize(null))
        assertEquals(DeskThemes.FOLLOW, DeskThemes.normalize(""))
        assertEquals(DeskThemes.FOLLOW, DeskThemes.normalize("system"))
        assertEquals("sodium", DeskThemes.normalize("Sodium"))
        assertEquals("filament", DeskThemes.normalize(" filament "))
        assertEquals("night", DeskThemes.normalize("night"))
        assertEquals(DeskThemes.FOLLOW, DeskThemes.normalize("no-such-theme"))
        assertEquals("night", DeskThemes.normalize(DeskThemes.normalize("NIGHT")))
    }
}
