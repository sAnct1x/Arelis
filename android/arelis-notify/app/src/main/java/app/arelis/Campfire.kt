package app.arelis

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.Color

/** Colours of the room that is on screen. Screens read these and repaint. */
object Campfire {
    private var active by mutableStateOf(DeskThemes.sodium)

    fun apply(palette: DeskPalette) {
        active = palette
    }

    val palette: DeskPalette get() = active

    val bg0: Color get() = Color(active.bg0)
    val bg1: Color get() = Color(active.bg1)
    val bg2: Color get() = Color(active.bg2)
    val well: Color get() = Color(active.well)
    val raised: Color get() = Color(active.raised)
    val accent: Color get() = Color(active.accent)
    val accent2: Color get() = Color(active.accent2)
    val text: Color get() = Color(active.text)
    val hint: Color get() = Color(active.hint)
    val dim: Color get() = Color(active.dim)
    val coal: Color get() = Color(active.coal)
    val danger: Color get() = Color(active.danger)
    val rim: Color get() = Color(active.rim)
}

@Composable
fun ArelisTheme(content: @Composable () -> Unit) {
    val bg0 = Campfire.bg0
    val bg1 = Campfire.bg1
    val accent = Campfire.accent
    val text = Campfire.text
    MaterialTheme(
        colorScheme = darkColorScheme(
            background = bg0,
            surface = bg1,
            primary = accent,
            onPrimary = bg0,
            onBackground = text,
            onSurface = text,
        ),
        content = content,
    )
}
