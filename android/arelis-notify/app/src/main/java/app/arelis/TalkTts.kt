package app.arelis

import android.content.Context
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import java.io.File
import java.util.Locale
import java.util.UUID

/**
 * Conversation-mode speak-back on this phone only.
 * House turns play a Kokoro WAV from the PC (same voice as desktop).
 * Gemma / other languages use the system TTS engine.
 */
class TalkTts(context: Context) {
    private val app = context.applicationContext
    private val main = Handler(Looper.getMainLooper())
    private var engine: TextToSpeech? = null
    private var player: MediaPlayer? = null
    private var ready = false

    @Volatile
    var busy: Boolean = false
        private set

    var onDone: () -> Unit = {}

    var language: String = TalkLanguage.DEFAULT
        set(value) {
            field = TalkLanguage.normalize(value)
            applyLanguage()
        }

    init {
        engine = TextToSpeech(app) { status ->
            ready = status == TextToSpeech.SUCCESS
            applyLanguage()
        }
    }

    fun speak(text: String) {
        val clipped = text.trim()
        if (clipped.isEmpty()) return
        main.post {
            stopPlayback()
            val tts = engine
            if (!ready || tts == null) {
                finish()
                return@post
            }
            busy = true
            val id = UUID.randomUUID().toString()
            tts.setOnUtteranceProgressListener(
                object : UtteranceProgressListener() {
                    override fun onStart(utteranceId: String?) {}
                    override fun onDone(utteranceId: String?) { finish() }
                    @Deprecated("deprecated in API")
                    override fun onError(utteranceId: String?) { finish() }
                    override fun onError(utteranceId: String?, errorCode: Int) { finish() }
                },
            )
            tts.speak(clipped, TextToSpeech.QUEUE_FLUSH, null, id)
        }
    }

    fun playWav(bytes: ByteArray) {
        if (bytes.isEmpty()) return
        main.post {
            stopPlayback()
            busy = true
            val file = File(app.cacheDir, "arelis-speak.wav")
            try {
                file.writeBytes(bytes)
                val mp = MediaPlayer()
                mp.setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_ASSISTANT)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                        .build(),
                )
                mp.setDataSource(file.absolutePath)
                mp.setOnCompletionListener { finish() }
                mp.setOnErrorListener { _, _, _ ->
                    finish()
                    true
                }
                mp.prepare()
                mp.start()
                player = mp
            } catch (_: Exception) {
                finish()
            }
        }
    }

    fun stop() {
        main.post {
            stopPlayback()
            busy = false
        }
    }

    fun shutdown() {
        main.post {
            stopPlayback()
            engine?.shutdown()
            engine = null
            ready = false
        }
    }

    private fun applyLanguage() {
        val tts = engine ?: return
        if (!ready) return
        val tag = TalkLanguage.bcp47(language)
        val locale = Locale.forLanguageTag(tag)
        tts.language = locale
    }

    private fun stopPlayback() {
        try {
            engine?.stop()
        } catch (_: Exception) {
        }
        try {
            player?.stop()
        } catch (_: Exception) {
        }
        try {
            player?.release()
        } catch (_: Exception) {
        }
        player = null
    }

    private fun finish() {
        main.post {
            stopPlayback()
            val was = busy
            busy = false
            if (was) onDone()
        }
    }
}
