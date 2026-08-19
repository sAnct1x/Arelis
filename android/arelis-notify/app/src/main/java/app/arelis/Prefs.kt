package app.arelis

import android.content.Context
import java.util.UUID

class Prefs(context: Context) {
    private val sp = context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    var baseUrl: String
        get() = sp.getString(KEY_URL, "")?.trim().orEmpty()
        set(value) = sp.edit().putString(KEY_URL, value.trim().trimEnd('/')).apply()

    var token: String
        get() = sp.getString(KEY_TOKEN, "")?.trim().orEmpty()
        set(value) = sp.edit().putString(KEY_TOKEN, value.trim()).apply()

    var instanceId: String
        get() = sp.getString(KEY_INSTANCE, "")?.trim().orEmpty()
        set(value) = sp.edit().putString(KEY_INSTANCE, value.trim()).apply()

    var deviceKey: String
        get() {
            val existing = sp.getString(KEY_DEVICE, "")?.trim().orEmpty()
            if (existing.isNotEmpty()) return existing
            val minted = UUID.randomUUID().toString().replace("-", "")
            sp.edit().putString(KEY_DEVICE, minted).apply()
            return minted
        }
        set(value) = sp.edit().putString(KEY_DEVICE, value.trim()).apply()

    var listenPort: Int
        get() = sp.getInt(KEY_PORT, 8080)
        set(value) = sp.edit().putInt(KEY_PORT, value).apply()

    var listenUrl: String
        get() = sp.getString(KEY_LISTEN, "")?.trim().orEmpty()
        set(value) = sp.edit().putString(KEY_LISTEN, value.trim().trimEnd('/')).apply()

    var paired: Boolean
        get() = sp.getBoolean(KEY_PAIRED, false)
        set(value) = sp.edit().putBoolean(KEY_PAIRED, value).apply()

    var enabled: Boolean
        get() = sp.getBoolean(KEY_ENABLED, true)
        set(value) = sp.edit().putBoolean(KEY_ENABLED, value).apply()

    val readyToTalk: Boolean
        get() = baseUrl.isNotBlank() && token.isNotBlank()

    companion object {
        private const val PREFS = "arelis"
        private const val KEY_URL = "base_url"
        private const val KEY_TOKEN = "token"
        private const val KEY_INSTANCE = "instance"
        private const val KEY_DEVICE = "device_key"
        private const val KEY_PORT = "listen_port"
        private const val KEY_LISTEN = "listen_url"
        private const val KEY_PAIRED = "paired"
        private const val KEY_ENABLED = "enabled"
    }
}
