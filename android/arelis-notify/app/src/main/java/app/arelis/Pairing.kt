package app.arelis

import org.json.JSONArray
import org.json.JSONObject

data class PairTicket(
    val instance: String,
    val urls: List<String>,
    val token: String,
    val pair: String,
)

fun parsePairTicket(raw: String): PairTicket {
    val text = raw.trim()
    if (text.startsWith("A1|")) {
        val parts = text.split("|")
        require(parts.size >= 5) { "Pairing text is missing pieces." }
        return PairTicket(
            instance = parts[1].trim(),
            token = parts[2].trim(),
            pair = parts[3].trim(),
            urls = parts.drop(4).map { it.trim() }.filter { it.isNotEmpty() },
        )
    }
    val obj = JSONObject(text)
    val urls = mutableListOf<String>()
    val arr: JSONArray? = obj.optJSONArray("urls")
    if (arr != null) {
        for (i in 0 until arr.length()) {
            val u = arr.optString(i).trim()
            if (u.isNotEmpty()) urls.add(u)
        }
    }
    val single = obj.optString("url").trim()
    if (single.isNotEmpty() && single !in urls) urls.add(0, single)
    val token = obj.optString("token").trim()
    val instance = obj.optString("instance").trim()
    val pair = obj.optString("pair").trim()
    require(urls.isNotEmpty() && token.isNotEmpty() && instance.isNotEmpty() && pair.isNotEmpty()) {
        "Pairing QR is missing a URL, token, instance, or pair secret."
    }
    return PairTicket(instance = instance, urls = urls, token = token, pair = pair)
}
