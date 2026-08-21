package app.arelis

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/** Gemma turns waiting to copy into the PC session when the house is back. */
data class TalkLine(
    val role: String,
    val text: String,
)

class TalkQueue(
    private val file: File,
) {
    constructor(context: Context) : this(
        context.applicationContext.filesDir.resolve("talk_sync.json"),
    )

    private val lock = Any()

    fun add(role: String, text: String) {
        val cleaned = text.trim()
        if (role !in setOf("user", "assistant") || cleaned.isEmpty()) return
        synchronized(lock) {
            val items = loadLocked().toMutableList()
            items.add(TalkLine(role, cleaned.take(8000)))
            while (items.size > 40) items.removeAt(0)
            saveLocked(items)
        }
    }

    fun take(): List<TalkLine> = synchronized(lock) {
        val items = loadLocked()
        saveLocked(emptyList())
        items
    }

    fun restore(rows: List<TalkLine>) {
        if (rows.isEmpty()) return
        synchronized(lock) {
            saveLocked(rows + loadLocked())
        }
    }

    fun isEmpty(): Boolean = synchronized(lock) { loadLocked().isEmpty() }

    private fun loadLocked(): List<TalkLine> {
        if (!file.exists()) return emptyList()
        val raw = runCatching { file.readText() }.getOrNull().orEmpty()
        if (raw.isBlank()) return emptyList()
        val arr = runCatching { JSONArray(raw) }.getOrNull() ?: return emptyList()
        val out = mutableListOf<TalkLine>()
        for (i in 0 until arr.length()) {
            val obj = arr.optJSONObject(i) ?: continue
            val role = obj.optString("role")
            val text = obj.optString("text").trim()
            if (role in setOf("user", "assistant") && text.isNotEmpty()) {
                out.add(TalkLine(role, text))
            }
        }
        return out
    }

    private fun saveLocked(items: List<TalkLine>) {
        val arr = JSONArray()
        for (item in items.takeLast(40)) {
            arr.put(JSONObject().put("role", item.role).put("text", item.text))
        }
        file.writeText(arr.toString())
    }
}
