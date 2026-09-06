package app.arelis

/** Phone decisions that must stay honest without a device. */

fun readyToTalk(baseUrl: String, token: String): Boolean =
    baseUrl.isNotBlank() && token.isNotBlank()

fun shouldPingNotice(kind: String): Boolean = kind != "sms" && kind != "email"

fun toggleVoiceMode(current: String, tapped: String): String =
    if (current == tapped) "off" else tapped

fun pocketThreadTitle(lines: List<TalkLine>): String {
    val lastUser = lines.lastOrNull { it.role == "user" }?.text?.trim().orEmpty()
    return lastUser.take(48).ifBlank { "on the phone" }
}

fun sameSeat(focusId: String, houseChatId: String): Boolean =
    focusId.isNotBlank() && houseChatId == focusId

/** Local calendar day, `YYYY-MM-DD`. Empty when the clock is unusable. */
fun talkDayStamp(epochMillis: Long, zoneId: String = java.time.ZoneId.systemDefault().id): String {
    if (epochMillis <= 0L) return ""
    return runCatching {
        java.time.Instant.ofEpochMilli(epochMillis)
            .atZone(java.time.ZoneId.of(zoneId))
            .toLocalDate()
            .toString()
    }.getOrDefault("")
}

/** First open of a new local day starts orbit, like glass cold launch. */
fun shouldOpenFreshChat(lastDay: String, today: String): Boolean {
    val day = today.trim()
    if (day.isEmpty()) return false
    return lastDay.trim() != day
}

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
