package app.arelis

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.media.ExifInterface
import java.io.ByteArrayOutputStream
import java.io.File

/**
 * Full camera files, not TakePicturePreview thumbnails.
 *
 * The preview contract returns a tiny (sometimes hardware) bitmap. Compressing
 * that is how a roasted chicken becomes a "crab on a beach".
 */
object CapturePhoto {
    const val MAX_EDGE = 1600
    const val QUALITY = 88
    const val MAX_FILE_BYTES = 8 * 1024 * 1024

    fun sampleSize(width: Int, height: Int, maxEdge: Int = MAX_EDGE): Int {
        val edge = maxOf(width, height, 1)
        var sample = 1
        while (edge / (sample * 2) >= maxEdge) {
            sample *= 2
        }
        return sample
    }

    fun jpegFromFile(file: File): ByteArray {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(file.absolutePath, bounds)
        val opts = BitmapFactory.Options().apply {
            inSampleSize = sampleSize(bounds.outWidth, bounds.outHeight)
            inPreferredConfig = Bitmap.Config.ARGB_8888
        }
        val raw = BitmapFactory.decodeFile(file.absolutePath, opts)
            ?: throw IllegalStateException("Could not read that photo.")
        val oriented = applyExif(file, raw)
        val frame = scale(oriented, MAX_EDGE)
        val software = if (frame.config == Bitmap.Config.HARDWARE) {
            frame.copy(Bitmap.Config.ARGB_8888, false) ?: frame
        } else {
            frame
        }
        val out = ByteArrayOutputStream()
        if (!software.compress(Bitmap.CompressFormat.JPEG, QUALITY, out) || out.size() == 0) {
            throw IllegalStateException("Could not keep that photo.")
        }
        return out.toByteArray()
    }

    private fun scale(src: Bitmap, maxEdge: Int): Bitmap {
        val edge = maxOf(src.width, src.height)
        if (edge <= maxEdge) return src
        val factor = maxEdge.toFloat() / edge.toFloat()
        return Bitmap.createScaledBitmap(
            src,
            maxOf(1, (src.width * factor).toInt()),
            maxOf(1, (src.height * factor).toInt()),
            true,
        )
    }

    private fun applyExif(file: File, src: Bitmap): Bitmap {
        val orient = try {
            ExifInterface(file.absolutePath).getAttributeInt(
                ExifInterface.TAG_ORIENTATION,
                ExifInterface.ORIENTATION_NORMAL,
            )
        } catch (_: Exception) {
            return src
        }
        val matrix = Matrix()
        when (orient) {
            ExifInterface.ORIENTATION_ROTATE_90 -> matrix.postRotate(90f)
            ExifInterface.ORIENTATION_ROTATE_180 -> matrix.postRotate(180f)
            ExifInterface.ORIENTATION_ROTATE_270 -> matrix.postRotate(270f)
            ExifInterface.ORIENTATION_FLIP_HORIZONTAL -> matrix.preScale(-1f, 1f)
            ExifInterface.ORIENTATION_FLIP_VERTICAL -> matrix.preScale(1f, -1f)
            else -> return src
        }
        return Bitmap.createBitmap(src, 0, 0, src.width, src.height, matrix, true)
    }
}

fun pocketFileReply(): String =
    "I can talk and look at a photo on this phone, but I can't open files until the house is back. Keep it and send again when we're on the same Wi-Fi."

fun pocketAttachReply(): String = pocketFileReply()

fun isImageAttach(name: String, mime: String = ""): Boolean {
    if (mime.startsWith("image/")) return true
    val n = name.lowercase()
    return n.endsWith(".jpg") || n.endsWith(".jpeg") || n.endsWith(".png") ||
        n.endsWith(".webp") || n.endsWith(".gif") || n.endsWith(".heic") ||
        n.endsWith(".heif")
}
