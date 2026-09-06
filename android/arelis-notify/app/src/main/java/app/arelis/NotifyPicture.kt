package app.arelis

import android.app.Notification
import android.content.ContentResolver
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.drawable.BitmapDrawable
import android.graphics.drawable.Icon
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.util.Base64
import androidx.core.app.NotificationCompat
import java.io.ByteArrayOutputStream

/** Compress a Messages notification picture so the LAN POST stays small. */
object NotifyPicture {
    const val MAX_BYTES = 400_000
    const val MAX_EDGE = 800
    // Framework EXTRA_PICTURE_ICON is API 31; the extra key is stable.
    private const val EXTRA_PICTURE_ICON = "android.pictureIcon"

    fun jpegBase64(notification: Notification, context: Context): String? {
        return try {
            val bitmap = pictureBitmap(notification, context) ?: return null
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
    private fun pictureBitmap(notification: Notification, context: Context): Bitmap? {
        extrasPicture(notification.extras, context)?.let { return it }
        return stylePicture(notification, context.contentResolver)
    }

    @Suppress("DEPRECATION")
    private fun extrasPicture(extras: Bundle, context: Context): Bitmap? {
        extras.getParcelable<Bitmap>(Notification.EXTRA_PICTURE)?.let { return it }
        if (Build.VERSION.SDK_INT < 31) return null
        val icon = extras.getParcelable<Icon>(EXTRA_PICTURE_ICON) ?: return null
        val drawable = icon.loadDrawable(context) ?: return null
        if (drawable is BitmapDrawable && drawable.bitmap != null) return drawable.bitmap
        val width = drawable.intrinsicWidth.coerceAtLeast(1)
        val height = drawable.intrinsicHeight.coerceAtLeast(1)
        val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bitmap)
        drawable.setBounds(0, 0, canvas.width, canvas.height)
        drawable.draw(canvas)
        return bitmap
    }

    private fun stylePicture(notification: Notification, resolver: ContentResolver): Bitmap? {
        val style = NotificationCompat.MessagingStyle
            .extractMessagingStyleFromNotification(notification)
            ?: return null
        for (message in style.messages.asReversed()) {
            val mime = message.dataMimeType ?: continue
            val uri = message.dataUri ?: continue
            if (!mime.startsWith("image/")) continue
            bitmapFromUri(resolver, uri)?.let { return it }
        }
        return null
    }

    private fun bitmapFromUri(resolver: ContentResolver, uri: Uri): Bitmap? {
        return try {
            resolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it) }
        } catch (_: Exception) {
            null
        }
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
