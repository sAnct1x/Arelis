package app.arelis

data class ChatBubble(
    val id: String,
    val role: String, // user | assistant | system
    val text: String,
    val glances: List<GlanceCard> = emptyList(),
    val streaming: Boolean = false,
)

data class GlanceCard(
    val id: String,
    val title: String,
    val kind: String,
)

data class AllowCard(
    val id: String,
    val headline: String,
    val summary: String,
)

enum class HouseMode {
    Pairing,
    Connecting,
    AtTheHouse,
    OnThePhone,
}

data class GemmaUi(
    val ready: Boolean = false,
    val downloading: Boolean = false,
    val progress: String = "",
    val waitWifi: Boolean = false,
    val onWifi: Boolean = true,
    val later: Boolean = false,
    val confirmCellular: Boolean = false,
)

fun houseModeLabel(mode: HouseMode, warmup: Boolean, confirm: Boolean): String {
    return when (mode) {
        HouseMode.Pairing -> "scan the qr on the pc"
        HouseMode.Connecting -> "connecting…"
        HouseMode.AtTheHouse -> when {
            confirm -> "at the house · allow waiting"
            warmup -> "at the house · loading"
            else -> "at the house"
        }
        HouseMode.OnThePhone -> "on the phone"
    }
}

fun talkSubtitle(
    mode: HouseMode,
    warmup: Boolean,
    confirm: Boolean,
    roomName: String,
    gemma: GemmaUi,
): String {
    if (mode == HouseMode.OnThePhone) {
        return when {
            gemma.downloading -> "on the phone · installing…"
            !gemma.ready -> "on the phone · no offline brain"
            else -> "on the phone"
        }
    }
    val base = houseModeLabel(mode, warmup, confirm)
    return if (roomName.isNotBlank() && mode == HouseMode.AtTheHouse) "$base · $roomName" else base
}

fun phoneIdleBody(mode: HouseMode, gemma: GemmaUi): String {
    if (mode != HouseMode.OnThePhone) {
        return if (mode == HouseMode.Connecting) {
            "Same Wi-Fi. She'll pick up when the PC answers."
        } else {
            ""
        }
    }
    return when {
        gemma.downloading -> gemma.progress.ifBlank { "Downloading the offline brain (~2.6 GB)…" }
        gemma.ready -> "The PC is out of reach. Talk and photos stay on this phone until the house is back."
        else -> "The PC is out of reach. Install the offline brain (~2.6 GB) so she can still talk here."
    }
}

fun humanGemmaError(exc: Throwable): String {
    val chain = generateSequence(exc) { it.cause }.take(8).toList()
    val root = chain.last()
    val raw = chain.mapNotNull { it.message }.firstOrNull { it.isNotBlank() }.orEmpty()
    val tag = root.javaClass.simpleName
    val short = raw.take(180)
    return when {
        root is UnsatisfiedLinkError ||
            root is ExceptionInInitializerError ||
            short.contains("litertlm_jni") ||
            short.contains("dlopen") ->
            "The on-phone native library didn't load ($tag: $short)"
        root is NoSuchMethodError ->
            "LiteRT called a Kotlin API this 1.9 app doesn't ship ($tag: $short)"
        chain.any { it is NoSuchElementException } ||
            short.contains("matching the predicate", ignoreCase = true) ->
            "This build still looks up LiteRT the wrong way ($tag)"
        short.contains("litert returned nothing", ignoreCase = true) ->
            "The engine treated a void LiteRT call as failure ($tag)"
        raw.contains("runtime is missing", ignoreCase = true) -> raw
        short.isNotBlank() -> "$tag: $short"
        else -> "On the phone, but Gemma is not ready."
    }
}

class MissingChatException(message: String = "That chat is gone.") : IllegalStateException(message)

data class ChatHint(val id: String, val roomId: String = "")

fun pickFocusChat(stored: String, chats: List<ChatHint>): String {
    val want = stored.trim()
    if (want.isNotBlank() && chats.any { it.id == want }) return want
    return chats.firstOrNull { it.roomId.isBlank() }?.id ?: ""
}

fun isMissingChatFailure(code: Int, body: String): Boolean {
    if (code != 404) return false
    val t = body.lowercase()
    return t.contains("no conversation") ||
        t.contains("missing_chat") ||
        t.contains("could not open that chat")
}

fun houseErrorMessage(code: Int, body: String): String {
    if (isMissingChatFailure(code, body)) return "That chat is gone."
    val err = jsonField(body, "error")
    if (err.isNotBlank() && !err.startsWith("{") && !err.startsWith("HTTP")) return err
    return when (code) {
        401 -> "Token does not match this Arelis."
        409 -> "Finish or stop the current turn first."
        503 -> "Open Arelis on the PC."
        else -> "The house said no."
    }
}

internal fun jsonField(body: String, key: String): String {
    val needle = "\"$key\""
    val at = body.indexOf(needle)
    if (at < 0) return ""
    val colon = body.indexOf(':', at + needle.length)
    if (colon < 0) return ""
    val start = body.indexOf('"', colon + 1)
    if (start < 0) return ""
    val end = body.indexOf('"', start + 1)
    if (end <= start) return ""
    return body.substring(start + 1, end)
}

fun isPhoneBrainError(text: String): Boolean {
    val t = text.lowercase()
    return t.contains("matching the predicate") ||
        t.contains("offline brain") ||
        t.contains("gemma is not ready") ||
        t.contains("on-phone brain") ||
        t.contains("native library") ||
        t.contains("litert")
}

fun priorTalkLines(lines: List<TalkLine>, currentUser: String = ""): List<TalkLine> {
    if (lines.isEmpty()) return emptyList()
    val last = lines.last()
    val ask = currentUser.trim()
    return if (ask.isNotEmpty() && last.role == "user" && last.text.trim() == ask) {
        lines.dropLast(1)
    } else {
        lines
    }
}

fun gemmaHistoryBlock(lines: List<TalkLine>, maxChars: Int = 3200): String {
    if (lines.isEmpty()) return ""
    val body = StringBuilder()
    for (line in lines.takeLast(24)) {
        val who = if (line.role == "user") "User" else "Arelis"
        body.append(who).append(": ").append(line.text.trim()).append('\n')
    }
    var text = body.toString().trim()
    if (text.length > maxChars) text = text.takeLast(maxChars)
    return "\n\nThis is the conversation so far. Continue it. Do not restart or greet as if this is new.\n\n$text"
}
