package app.arelis

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/** Desktop sodium tokens from arelis/ui/theme.py COLORS — keep in lockstep. */
object Campfire {
    val bg0 = Color(0xFF100D0B)
    val bg1 = Color(0xFF2A221C)
    val bg2 = Color(0xFF40342B)
    val well = Color(0xFF4A3C32)
    val raised = Color(0xFF3A3028)
    val accent = Color(0xFFFF7A22)
    val accent2 = Color(0xFFFFC08A)
    val text = Color(0xFFF8F1EA)
    val hint = Color(0xFFE6B892)
    val dim = Color(0xFFC4906E)
    val coal = Color(0xFF946848)
    val danger = Color(0xFFF0A0A8)
    val rim = Color(0x96FF7A22)
}

@Composable
fun ArelisTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            background = Campfire.bg0,
            surface = Campfire.bg1,
            primary = Campfire.accent,
            onPrimary = Campfire.bg0,
            onBackground = Campfire.text,
            onSurface = Campfire.text,
        ),
        content = content,
    )
}
