package app.arelis

import android.app.Notification
import android.graphics.Bitmap
import android.os.Bundle
import android.util.Base64
import java.io.ByteArrayOutputStream

/** Compress a Messages notification picture so the LAN POST stays small. */
object NotifyPicture {
    const val MAX_BYTES = 400_000
    const val MAX_EDGE = 800

    fun jpegBase64(extras: Bundle): String? {
        return try {
            val bitmap = pictureBitmap(extras) ?: return null
            val scaled = scale(bitmap)
            val out = ByteArrayOutputStream()
            var quality = 80
            do {
                out.reset()
                scaled.compress(Bitmap.CompressFormat.JPEG, quality, out)
                quality -= 10
            } while (out.size() > MAX_BYTES && quality >= 40)
            if (out.size() > MAX_BYTES) return null
            Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP)
        } catch (_: Exception) {
            null
        }
    }

    @Suppress("DEPRECATION")
    private fun pictureBitmap(extras: Bundle): Bitmap? {
        val picture = extras.getParcelable<Bitmap>(Notification.EXTRA_PICTURE)
        if (picture != null) return picture
        return extras.getParcelable(Notification.EXTRA_LARGE_ICON)
    }

    private fun scale(src: Bitmap): Bitmap {
        val w = src.width
        val h = src.height
        val edge = maxOf(w, h)
        if (edge <= MAX_EDGE) return src
        val scale = MAX_EDGE.toFloat() / edge.toFloat()
        return Bitmap.createScaledBitmap(
            src,
            maxOf(1, (w * scale).toInt()),
            maxOf(1, (h * scale).toInt()),
            true,
        )
    }
}
