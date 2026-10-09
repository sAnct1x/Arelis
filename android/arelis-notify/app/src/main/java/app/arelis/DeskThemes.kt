package app.arelis

/**
 * Desktop rooms from theme_tokens.py. There is no separate light palette.
 * The desktop default is sodium, and the dark alias is sodium too, so
 * Follow system uses sodium in both phone modes.
 */
data class DeskPalette(
    val id: String,
    val bg0: Long,
    val bg1: Long,
    val bg2: Long,
    val well: Long,
    val raised: Long,
    val accent: Long,
    val accent2: Long,
    val text: Long,
    val hint: Long,
    val dim: Long,
    val coal: Long,
    val danger: Long,
    val rim: Long,
    val codeFill: Long,
) {
    fun ink(): ReplyInk = ReplyInk(text = text, dim = dim, codeFill = codeFill, accent = accent)
}

data class ThemeMenu(val id: String, val label: String)

object DeskThemes {
    const val FOLLOW = "system"

    /** Desktop DEFAULT_THEME. No light palette exists. */
    const val LIGHT = "sodium"

    /** Desktop alias "dark" resolves to sodium, not night. */
    const val DARK = "sodium"

    val ids = listOf("sodium", "filament", "night")

    val menu = listOf(
        ThemeMenu(FOLLOW, "Follow system"),
        ThemeMenu("sodium", "sodium"),
        ThemeMenu("filament", "filament"),
        ThemeMenu("night", "night"),
    )

    val sodium = DeskPalette(
        id = "sodium",
        bg0 = 0xFF100D0B,
        bg1 = 0xFF2A221C,
        bg2 = 0xFF40342B,
        well = 0xFF4A3C32,
        raised = 0xFF3A3028,
        accent = 0xFFFF7A22,
        accent2 = 0xFFFFC08A,
        text = 0xFFF8F1EA,
        hint = 0xFFE6B892,
        dim = 0xFFC4906E,
        coal = 0xFF946848,
        danger = 0xFFF0A0A8,
        rim = 0x96FF7A22,
        codeFill = 0xB40A0807,
    )

    val filament = DeskPalette(
        id = "filament",
        bg0 = 0xFF07080B,
        bg1 = 0xFF101218,
        bg2 = 0xFF181C24,
        well = 0xFF1C1E26,
        raised = 0xFF24262E,
        accent = 0xFFC4A06A,
        accent2 = 0xFFE4C896,
        text = 0xFFE8D4B0,
        hint = 0xFFD4B888,
        dim = 0xFFA88858,
        coal = 0xFF7A6240,
        danger = 0xFFF0A0A8,
        rim = 0x6EC4A06A,
        codeFill = 0xB40C0E12,
    )

    val night = DeskPalette(
        id = "night",
        bg0 = 0xFF060A20,
        bg1 = 0xFF0B0C26,
        bg2 = 0xFF161436,
        well = 0xFF0E0F2D,
        raised = 0xFF161436,
        accent = 0xFF8050B0,
        accent2 = 0xFF8060B0,
        text = 0xFFFFFFFF,
        hint = 0xFF9088A8,
        dim = 0xFF7A7290,
        coal = 0xFF5C5678,
        danger = 0xFFF0A0A8,
        rim = 0xA08060B0,
        codeFill = 0xB4020418,
    )

    val byId = mapOf(
        "sodium" to sodium,
        "filament" to filament,
        "night" to night,
    )

    fun normalize(raw: String?): String {
        val value = raw?.trim()?.lowercase().orEmpty()
        if (value.isEmpty() || value == FOLLOW) return FOLLOW
        if (value in ids) return value
        return FOLLOW
    }

    fun resolvedId(saved: String, systemDark: Boolean): String {
        val choice = normalize(saved)
        if (choice != FOLLOW) return choice
        return if (systemDark) DARK else LIGHT
    }

    fun palette(saved: String, systemDark: Boolean): DeskPalette =
        byId.getValue(resolvedId(saved, systemDark))

    fun label(saved: String): String =
        menu.firstOrNull { it.id == normalize(saved) }?.label ?: "Follow system"
}
