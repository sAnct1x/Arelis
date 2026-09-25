package app.arelis

import android.content.Context
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.io.FileOutputStream
import java.util.concurrent.TimeUnit

/** Gemma 4 E2B LiteRT pack. Offered at pair (~2.6 GB), not stuffed in the APK. */
object GemmaStore {
    const val FILE_NAME = "gemma-4-E2B-it.litertlm"
    const val MIN_BYTES = 50_000_000L
    const val URL =
        "https://huggingface.co/litert-community/gemma-4-E2B-it-litert-lm/resolve/main/gemma-4-E2B-it.litertlm"

    fun file(context: Context): File = File(context.filesDir, FILE_NAME)

    fun ready(context: Context): Boolean = ready(file(context))

    fun ready(dest: File): Boolean = dest.isFile && dest.length() > MIN_BYTES

    fun download(
        context: Context,
        onProgress: (Long, Long) -> Unit,
        fromHouse: ArelisClient? = null,
    ): File {
        val dest = file(context)
        val part = File(dest.absolutePath + ".part")
        if (fromHouse != null) {
            try {
                if (fromHouse.downloadCompanionGemma(part, onProgress)) {
                    return finish(dest, part)
                }
            } catch (_: Exception) {
                // House missing the file, or the LAN dropped. Hugging Face is the fallback.
            }
        }
        val client = OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.MINUTES)
            .build()
        val req = Request.Builder()
            .url(URL)
            .header("User-Agent", "Arelis/0.1")
            .build()
        client.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) {
                throw IllegalStateException("Could not download Gemma (HTTP ${resp.code}).")
            }
            writeStream(resp.body?.byteStream(), resp.body?.contentLength() ?: -1L, part, onProgress)
        }
        return finish(dest, part)
    }

    internal fun finish(dest: File, part: File): File {
        if (dest.exists()) dest.delete()
        if (!part.renameTo(dest)) {
            part.copyTo(dest, overwrite = true)
            part.delete()
        }
        return dest
    }

    internal fun writeStream(
        source: java.io.InputStream?,
        total: Long,
        part: File,
        onProgress: (Long, Long) -> Unit,
    ) {
        val input = source ?: throw IllegalStateException("Empty Gemma download.")
        FileOutputStream(part).use { out ->
            val buf = ByteArray(64 * 1024)
            var got = 0L
            while (true) {
                val n = input.read(buf)
                if (n < 0) break
                out.write(buf, 0, n)
                got += n
                onProgress(got, total)
            }
        }
    }
}
