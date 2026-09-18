package app.arelis

import java.nio.charset.StandardCharsets
import java.util.Base64

fun radioAuthorized(headers: Map<String, String>, deviceKey: String): Boolean {
    if (deviceKey.isBlank()) return false
    val auth = headers["authorization"].orEmpty()
    if (auth.startsWith("Bearer ", ignoreCase = true)) {
        return auth.substring(7).trim() == deviceKey
    }
    if (auth.startsWith("Basic ", ignoreCase = true)) {
        val decoded = decodeBasic(auth.substring(6).trim())
        val password = decoded.substringAfter(":", missingDelimiterValue = "")
        return password == deviceKey
    }
    return headers["x-arelis-token"] == deviceKey
}

fun radioRoute(method: String, path: String): Int = when {
    method == "GET" && (path == "/health" || path == "/") -> 200
    method == "POST" && path == "/messages" -> 200
    else -> 404
}

private fun decodeBasic(b64: String): String {
    if (b64.isBlank()) return ""
    return runCatching {
        val padded = when (b64.length % 4) {
            2 -> "$b64=="
            3 -> "$b64="
            else -> b64
        }
        String(Base64.getDecoder().decode(padded), StandardCharsets.UTF_8)
    }.getOrDefault("")
}
