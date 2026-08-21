package app.arelis

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * The conversation the pocket is actually in: last house thread, plus any
 * Gemma lines that have not copied in yet. Survives the app being killed.
 */
class PocketThread(
    private val file: File,
) {
    constructor(context: Context) : this(
        context.applicationContext.filesDir.resolve("pocket_thread.json"),
    )

    private val lock = Any()

    fun sessionId(): String = synchronized(lock) { loadLocked().first }

    fun lines(): List<TalkLine> = synchronized(lock) { loadLocked().second }

    fun replace(sessionId: String, lines: List<TalkLine>) {
        synchronized(lock) {
            saveLocked(sessionId.trim(), cap(lines))
        }
    }

    fun keepSession(sessionId: String) {
        val id = sessionId.trim()
        if (id.isEmpty()) return
        synchronized(lock) {
            saveLocked(id, loadLocked().second)
        }
    }

    fun append(role: String, text: String) {
        val cleaned = text.trim()
        if (role !in setOf("user", "assistant") || cleaned.isEmpty()) return
        synchronized(lock) {
            val (sid, items) = loadLocked()
            saveLocked(sid, cap(items + TalkLine(role, cleaned.take(8000))))
        }
    }

    private fun cap(lines: List<TalkLine>): List<TalkLine> =
        if (lines.size <= 40) lines else lines.takeLast(40)

    private fun loadLocked(): Pair<String, List<TalkLine>> {
        if (!file.exists()) return "" to emptyList()
        val raw = runCatching { file.readText() }.getOrNull().orEmpty()
        if (raw.isBlank()) return "" to emptyList()
        val obj = runCatching { JSONObject(raw) }.getOrNull() ?: return "" to emptyList()
        val sid = obj.optString("sessionId")
        val arr = obj.optJSONArray("lines") ?: JSONArray()
        val out = mutableListOf<TalkLine>()
        for (i in 0 until arr.length()) {
            val row = arr.optJSONObject(i) ?: continue
            val role = row.optString("role")
            val text = row.optString("text").trim()
            if (role in setOf("user", "assistant") && text.isNotEmpty()) {
                out.add(TalkLine(role, text))
            }
        }
        return sid to cap(out)
    }

    private fun saveLocked(sessionId: String, lines: List<TalkLine>) {
        val arr = JSONArray()
        for (item in lines) {
            arr.put(JSONObject().put("role", item.role).put("text", item.text))
        }
        file.writeText(
            JSONObject().put("sessionId", sessionId).put("lines", arr).toString(),
        )
    }
}
