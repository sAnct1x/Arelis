package app.arelis

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import java.io.File
import java.security.MessageDigest

/** Sideload the house APK with the system installer. One tap. Not silent. */
object CompanionInstall {
    fun apkFile(activity: Activity): File {
        val dir = File(activity.cacheDir, "updates")
        if (!dir.isDirectory) dir.mkdirs()
        return File(dir, "arelis.apk")
    }

    fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buf = ByteArray(64 * 1024)
            while (true) {
                val n = input.read(buf)
                if (n < 0) break
                digest.update(buf, 0, n)
            }
        }
        return digest.digest().joinToString("") { b -> "%02x".format(b) }
    }

    fun canInstall(activity: Activity): Boolean {
        return if (Build.VERSION.SDK_INT >= 26) {
            activity.packageManager.canRequestPackageInstalls()
        } else {
            true
        }
    }

    fun askInstallPermission(activity: Activity) {
        if (Build.VERSION.SDK_INT < 26) return
        val uri = Uri.parse("package:${activity.packageName}")
        activity.startActivity(
            Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, uri),
        )
    }

    fun prompt(activity: Activity, apk: File) {
        val uri = FileProvider.getUriForFile(
            activity,
            "${activity.packageName}.files",
            apk,
        )
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        activity.startActivity(intent)
    }
}
