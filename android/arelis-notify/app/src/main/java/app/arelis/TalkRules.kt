package app.arelis

/** Phone decisions that must stay honest without a device. */

fun readyToTalk(baseUrl: String, token: String): Boolean =
    baseUrl.isNotBlank() && token.isNotBlank()

fun shouldPingNotice(kind: String): Boolean = kind != "sms" && kind != "email"

fun toggleVoiceMode(current: String, tapped: String): String =
    if (current == tapped) "off" else tapped

data class VoiceDraft(
    val mode: String = "off",
    val anchor: String = "",
    val draft: String = "",
) {
    fun start(next: String): VoiceDraft {
        val mode = toggleVoiceMode(this.mode, next)
        return if (mode == "off") copy(mode = "off") else copy(mode = mode, anchor = draft)
    }

    fun partial(heard: String): VoiceDraft = when (mode) {
        "dictate" -> copy(draft = joinHeard(anchor, heard))
        "conversation" -> copy(draft = heard)
        else -> this
    }

    /** Second value is true when conversation should send the turn. */
    fun finalHeard(heard: String): Pair<VoiceDraft, Boolean> = when (mode) {
        "dictate" -> {
            val text = joinHeard(anchor, heard)
            copy(draft = text, anchor = text) to false
        }
        "conversation" -> copy(draft = heard) to true
        else -> this to false
    }
}

private fun joinHeard(anchor: String, heard: String): String =
    listOf(anchor, heard).filter { it.isNotBlank() }.joinToString(" ")
