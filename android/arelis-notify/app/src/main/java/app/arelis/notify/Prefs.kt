package app.arelis.notify

import android.content.Context

class Prefs(context: Context) {
    private val sp = context.getSharedPreferences("arelis_notify", Context.MODE_PRIVATE)

    var baseUrl: String
        get() = sp.getString(KEY_URL, "")?.trim().orEmpty()
        set(value) = sp.edit().putString(KEY_URL, value.trim().trimEnd('/')).apply()

    var token: String
        get() = sp.getString(KEY_TOKEN, "")?.trim().orEmpty()
        set(value) = sp.edit().putString(KEY_TOKEN, value.trim()).apply()

    var enabled: Boolean
        get() = sp.getBoolean(KEY_ENABLED, true)
        set(value) = sp.edit().putBoolean(KEY_ENABLED, value).apply()

    companion object {
        private const val KEY_URL = "base_url"
        private const val KEY_TOKEN = "token"
        private const val KEY_ENABLED = "enabled"
    }
}
