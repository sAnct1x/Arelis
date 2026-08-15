package app.arelis.notify

import android.content.Intent
import android.os.Bundle
import android.provider.Settings
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import app.arelis.notify.databinding.ActivityMainBinding
import java.util.concurrent.Executors

class MainActivity : AppCompatActivity() {
    private lateinit var binding: ActivityMainBinding
    private lateinit var prefs: Prefs
    private val io = Executors.newSingleThreadExecutor()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        prefs = Prefs(this)

        binding.inputUrl.setText(prefs.baseUrl)
        binding.inputToken.setText(prefs.token)
        binding.switchEnabled.isChecked = prefs.enabled

        binding.btnSave.setOnClickListener {
            prefs.baseUrl = binding.inputUrl.text?.toString().orEmpty()
            prefs.token = binding.inputToken.text?.toString().orEmpty()
            prefs.enabled = binding.switchEnabled.isChecked
            binding.statusText.text = "Saved. Notification listener uses these values immediately."
            Toast.makeText(this, "Saved", Toast.LENGTH_SHORT).show()
        }

        binding.btnAccess.setOnClickListener {
            startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        }

        binding.btnPing.setOnClickListener {
            prefs.baseUrl = binding.inputUrl.text?.toString().orEmpty()
            prefs.token = binding.inputToken.text?.toString().orEmpty()
            val url = prefs.baseUrl
            val token = prefs.token
            if (url.isBlank() || token.isBlank()) {
                binding.statusText.text = "Set URL and token first."
                return@setOnClickListener
            }
            binding.statusText.text = "Pinging…"
            io.execute {
                val message = try {
                    val body = ArelisClient(url, token).ping()
                    "Ping OK: $body"
                } catch (exc: Exception) {
                    "Ping failed: ${exc.message}"
                }
                runOnUiThread { binding.statusText.text = message }
            }
        }
    }
}
