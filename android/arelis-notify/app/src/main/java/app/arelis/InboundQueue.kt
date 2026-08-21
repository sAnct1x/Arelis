package app.arelis

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.concurrent.TimeUnit

data class QueuedInbound(
    val id: String,
    val from: String,
    val body: String,
    val timeIso: String,
    val enqueuedAt: Long,
    val tries: Int,
    val imageJpeg: String = "",
)

class InboundQueue(
    private val file: File,
    private val nowMs: () -> Long = { System.currentTimeMillis() },
    private val maxAgeMs: Long = TimeUnit.DAYS.toMillis(7),
) {
    constructor(context: Context) : this(
        context.applicationContext.filesDir.resolve("inbound_queue.json"),
    )

    private val lock = Any()

    fun enqueue(
        id: String,
        from: String,
        body: String,
        timeIso: String,
        imageJpeg: String? = null,
    ) {
        synchronized(lock) {
            val items = loadLocked().toMutableList()
            if (items.any { it.id == id }) return
            items.add(
                QueuedInbound(
                    id = id,
                    from = from,
                    body = body,
                    timeIso = timeIso,
                    enqueuedAt = nowMs(),
                    tries = 0,
                    imageJpeg = imageJpeg.orEmpty(),
                ),
            )
            saveLocked(items)
        }
    }

    fun snapshot(): List<QueuedInbound> = synchronized(lock) { loadLocked() }

    fun replaceAll(items: List<QueuedInbound>) {
        synchronized(lock) { saveLocked(items) }
    }

    fun isEmpty(): Boolean = synchronized(lock) { loadLocked().isEmpty() }

    private fun loadLocked(): List<QueuedInbound> {
        if (!file.exists()) return emptyList()
        val raw = runCatching { file.readText() }.getOrNull().orEmpty()
        if (raw.isBlank()) return emptyList()
        val arr = runCatching { JSONArray(raw) }.getOrNull() ?: return emptyList()
        val cutoff = nowMs() - maxAgeMs
        val out = mutableListOf<QueuedInbound>()
        for (i in 0 until arr.length()) {
            val obj = arr.optJSONObject(i) ?: continue
            val enqueued = obj.optLong("enqueuedAt")
            if (enqueued in 1 until cutoff) continue
            out.add(
                QueuedInbound(
                    id = obj.optString("id"),
                    from = obj.optString("from"),
                    body = obj.optString("body"),
                    timeIso = obj.optString("time"),
                    enqueuedAt = enqueued,
                    tries = obj.optInt("tries"),
                    imageJpeg = obj.optString("imageJpeg"),
                ),
            )
        }
        return out
    }

    private fun saveLocked(items: List<QueuedInbound>) {
        val arr = JSONArray()
        for (item in items) {
            arr.put(
                JSONObject()
                    .put("id", item.id)
                    .put("from", item.from)
                    .put("body", item.body)
                    .put("time", item.timeIso)
                    .put("enqueuedAt", item.enqueuedAt)
                    .put("tries", item.tries)
                    .put("imageJpeg", item.imageJpeg),
            )
        }
        file.writeText(arr.toString())
    }
}
