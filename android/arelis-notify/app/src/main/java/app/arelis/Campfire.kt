package app.arelis

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/** Desktop sodium tokens from arelis/ui/theme.py COLORS — keep in lockstep. */
object Campfire {
    val bg0 = Color(0xFF160D07)
    val bg1 = Color(0xFF221408)
    val bg2 = Color(0xFF321C0E)
    val well = Color(0xFF26160C)
    val raised = Color(0xFF2E1A0C)
    val accent = Color(0xFFFF7A22)
    val accent2 = Color(0xFFFFC08A)
    val text = Color(0xFFFAE8DC)
    val hint = Color(0xFFF0C7A8)
    val dim = Color(0xFFC4906E)
    val coal = Color(0xFF8C5C3C)
    val danger = Color(0xFFF0A0A8)
    val rim = Color(0x6EFF7A22)
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
