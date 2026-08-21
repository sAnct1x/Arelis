package app.arelis

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer

/**
 * Dictate and conversation, same idea as the desktop.
 * Dictate lands in the composer. Conversation sends when you stop talking.
 * Not hold-to-talk.
 */
class VoiceListen(private val context: Context) {
    var mode: String = "off"
        private set
    var listening: Boolean = false
        private set

    var onPartial: (String) -> Unit = {}
    var onFinal: (String) -> Unit = {}
    var onState: (Boolean) -> Unit = {}
    var onError: (String) -> Unit = {}

    private val main = Handler(Looper.getMainLooper())
    private var recognizer: SpeechRecognizer? = null
    private var want = false
    private var restart: Runnable? = null

    fun toggle(next: String) {
        if (mode == next) stop() else start(next)
    }

    fun start(next: String) {
        mode = next
        want = true
        main.post { begin() }
    }

    fun pause() {
        want = false
        cancelRestart()
        main.post { destroyRecognizer() }
        listening = false
        onState(false)
    }

    fun resumeIfLatched() {
        if (mode == "off") return
        want = true
        main.post { begin() }
    }

    fun stop() {
        mode = "off"
        want = false
        cancelRestart()
        main.post { destroyRecognizer() }
        listening = false
        onState(false)
    }

    private fun begin() {
        if (!want || mode == "off") return
        if (!SpeechRecognizer.isRecognitionAvailable(context)) {
            onError("This phone has no dictate engine. Type instead.")
            stop()
            return
        }
        destroyRecognizer()
        val rec = SpeechRecognizer.createSpeechRecognizer(context)
        rec.setRecognitionListener(
            object : RecognitionListener {
                override fun onReadyForSpeech(params: Bundle?) {
                    listening = true
                    onState(true)
                }

                override fun onBeginningOfSpeech() {}

                override fun onRmsChanged(rmsdB: Float) {}

                override fun onBufferReceived(buffer: ByteArray?) {}

                override fun onEndOfSpeech() {}

                override fun onError(error: Int) {
                    listening = false
                    onState(false)
                    if (!want || mode == "off") return
                    if (error == SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS) {
                        onError("Mic permission is needed to talk out loud.")
                        return
                    }
                    scheduleRestart()
                }

                override fun onResults(results: Bundle?) {
                    listening = false
                    onState(false)
                    val text = results
                        ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                        ?.firstOrNull()
                        ?.trim()
                        .orEmpty()
                    if (text.isNotEmpty()) onFinal(text)
                    if (want && mode == "dictate") scheduleRestart()
                }

                override fun onPartialResults(partialResults: Bundle?) {
                    val text = partialResults
                        ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                        ?.firstOrNull()
                        .orEmpty()
                    if (text.isNotBlank()) onPartial(text)
                }

                override fun onEvent(eventType: Int, params: Bundle?) {}
            },
        )
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(
                RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                RecognizerIntent.LANGUAGE_MODEL_FREE_FORM,
            )
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
        }
        recognizer = rec
        rec.startListening(intent)
    }

    private fun scheduleRestart() {
        cancelRestart()
        val run = Runnable { if (want && mode != "off") begin() }
        restart = run
        main.postDelayed(run, 280)
    }

    private fun cancelRestart() {
        restart?.let { main.removeCallbacks(it) }
        restart = null
    }

    private fun destroyRecognizer() {
        try {
            recognizer?.cancel()
        } catch (_: Exception) {
        }
        try {
            recognizer?.destroy()
        } catch (_: Exception) {
        }
        recognizer = null
    }
}
