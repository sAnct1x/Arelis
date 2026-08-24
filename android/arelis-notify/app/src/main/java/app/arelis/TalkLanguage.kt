package app.arelis

data class TalkLang(
    val code: String,
    val label: String,
    val bcp47: String,
    val native: String,
)

/** English first and default, then alphabetical. Keyboard, dictate, and replies follow this. */
object TalkLanguage {
    const val DEFAULT = "en"

    val all: List<TalkLang> = listOf(
        TalkLang("en", "english", "en-US", "English"),
        TalkLang("zh", "chinese", "zh-CN", "Chinese"),
        TalkLang("fr", "french", "fr-FR", "French"),
        TalkLang("ja", "japanese", "ja-JP", "Japanese"),
        TalkLang("ko", "korean", "ko-KR", "Korean"),
        TalkLang("es", "spanish", "es-ES", "Spanish"),
    )

    fun normalize(raw: String): String {
        val key = raw.trim().lowercase().replace('_', '-')
        if (key.isEmpty()) return DEFAULT
        val short = key.substringBefore('-')
        return all.firstOrNull {
            it.code == key || it.code == short || it.bcp47.lowercase() == key
        }?.code ?: DEFAULT
    }

    fun of(raw: String): TalkLang = all.first { it.code == normalize(raw) }

    fun bcp47(raw: String): String = of(raw).bcp47

    fun isEnglish(raw: String): Boolean = normalize(raw) == DEFAULT

    fun instruction(raw: String): String {
        val lang = of(raw)
        if (lang.code == DEFAULT) return ""
        return "The user is writing in ${lang.native}. Reply in ${lang.native}. Do not switch languages unless they clearly ask."
    }

    fun withReply(persona: String, raw: String): String {
        val extra = instruction(raw)
        return if (extra.isEmpty()) persona else persona.trimEnd() + "\n\n" + extra
    }
}
