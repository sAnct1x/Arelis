package app.arelis

/** Pick the one line a Messages notification actually meant. */
object NotifyCopy {
    fun pickBody(
        styleText: String = "",
        extraText: String = "",
        bigText: String = "",
        subText: String = "",
    ): String {
        return sequenceOf(styleText, extraText, bigText, subText)
            .map { it.trim() }
            .firstOrNull { it.isNotEmpty() }
            .orEmpty()
    }
}
