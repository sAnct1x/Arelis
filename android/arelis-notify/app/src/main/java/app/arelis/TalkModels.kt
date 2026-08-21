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
        HouseMode.Pairing -> "Scan the QR on the PC"
        HouseMode.Connecting -> "Connecting…"
        HouseMode.AtTheHouse -> when {
            confirm -> "At the house · Allow waiting"
            warmup -> "At the house · loading"
            else -> "At the house"
        }
        HouseMode.OnThePhone -> "On the phone"
    }
}
