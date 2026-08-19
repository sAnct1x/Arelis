package app.arelis

import android.Manifest
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat

data class GrantState(
    val restrictedHint: Boolean,
    val sms: Boolean,
    val notifications: Boolean,
    val battery: Boolean,
    val camera: Boolean,
)

fun grantState(context: Context): GrantState {
    val sms = ContextCompat.checkSelfPermission(context, Manifest.permission.SEND_SMS) ==
        PackageManager.PERMISSION_GRANTED
    val notifications = isNotificationListenerEnabled(context)
    val battery = isBatteryUnrestricted(context)
    val camera = ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
        PackageManager.PERMISSION_GRANTED
    return GrantState(
        restrictedHint = !sms || !notifications,
        sms = sms,
        notifications = notifications,
        battery = battery,
        camera = camera,
    )
}

fun isNotificationListenerEnabled(context: Context): Boolean {
    val cn = ComponentName(context, MessagesNotifyService::class.java)
    val flat = Settings.Secure.getString(
        context.contentResolver,
        "enabled_notification_listeners",
    ) ?: return false
    return flat.split(":").any { it.equals(cn.flattenToString(), ignoreCase = true) }
}

fun isBatteryUnrestricted(context: Context): Boolean {
    val pm = context.getSystemService(Context.POWER_SERVICE) as PowerManager
    return pm.isIgnoringBatteryOptimizations(context.packageName)
}

fun openAppDetails(context: Context) {
    context.startActivity(
        Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
            data = Uri.fromParts("package", context.packageName, null)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        },
    )
}

fun openNotificationAccess(context: Context) {
    context.startActivity(
        Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        },
    )
}

fun openBatterySettings(context: Context) {
    val ask = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).apply {
        data = Uri.parse("package:${context.packageName}")
        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    }
    try {
        context.startActivity(ask)
    } catch (_: Exception) {
        context.startActivity(
            Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            },
        )
    }
}

fun notificationsAllowed(context: Context): Boolean {
    if (Build.VERSION.SDK_INT < 33) return true
    return NotificationManagerCompat.from(context).areNotificationsEnabled()
}
