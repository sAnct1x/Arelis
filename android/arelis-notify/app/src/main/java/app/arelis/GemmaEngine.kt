package app.arelis

import android.content.Context
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/**
 * On-phone brain when the PC is gone. No tools. LiteRT-LM + Gemma 4 E2B.
 * Loaded by reflection so unit tests (and a Kotlin 1.9 compile) do not depend
 * on whichever LiteRT AAR Maven handed us this week.
 */
class GemmaEngine {
    private val lock = Any()
    private var engine: AutoCloseable? = null
    private var conversation: AutoCloseable? = null

    fun loaded(): Boolean = synchronized(lock) { engine != null }

    fun unload() {
        synchronized(lock) {
            try {
                conversation?.close()
            } catch (_: Exception) {
            }
            conversation = null
            try {
                engine?.close()
            } catch (_: Exception) {
            }
            engine = null
        }
    }

    fun ensure(context: Context, model: File, system: String) {
        synchronized(lock) {
            if (engine != null) return
            val backendCls = cls("com.google.ai.edge.litertlm.Backend")
            val cpu = backendCls.methods.first { it.name == "CPU" && it.parameterCount == 0 }
                .invoke(null)
            val cfgCls = cls("com.google.ai.edge.litertlm.EngineConfig")
            val cfg = construct(
                cfgCls,
                model.absolutePath,
                cpu,
                context.cacheDir.absolutePath,
            )
            val engCls = cls("com.google.ai.edge.litertlm.Engine")
            val eng = construct(engCls, cfg)
            engCls.getMethod("initialize").invoke(eng)
            val contents = cls("com.google.ai.edge.litertlm.Contents")
                .methods.first { it.name == "of" && it.parameterCount == 1 }
                .invoke(null, system)
            val convCfg = construct(
                cls("com.google.ai.edge.litertlm.ConversationConfig"),
                contents,
            )
            val conv = engCls.methods.first {
                it.name == "createConversation" && it.parameterCount >= 1
            }.invoke(eng, convCfg)
            engine = eng as AutoCloseable
            conversation = conv as AutoCloseable
        }
    }

    fun reply(userText: String, onDelta: (String) -> Unit): String {
        val conv = synchronized(lock) { conversation }
            ?: throw IllegalStateException("Gemma is not loaded.")
        val send = conv.javaClass.methods.firstOrNull {
            it.name == "sendMessage" && it.parameterCount == 1
        }
        if (send != null) {
            val text = extractText(send.invoke(conv, userText))
            if (text.isNotEmpty()) {
                onDelta(text)
                return text
            }
        }
        return streamAsync(conv, userText, onDelta)
    }

    private fun streamAsync(conv: Any, userText: String, onDelta: (String) -> Unit): String {
        val async = conv.javaClass.methods.firstOrNull {
            it.name == "sendMessageAsync" && it.parameterCount >= 1
        } ?: return ""
        val latch = CountDownLatch(1)
        val acc = StringBuilder()
        val err = AtomicReference<Throwable?>(null)
        val callbackClass = try {
            Class.forName("com.google.ai.edge.litertlm.MessageCallback")
        } catch (_: ClassNotFoundException) {
            return extractText(async.invoke(conv, userText)).also {
                if (it.isNotEmpty()) onDelta(it)
            }
        }
        val callback = java.lang.reflect.Proxy.newProxyInstance(
            callbackClass.classLoader,
            arrayOf(callbackClass),
        ) { _, method, args ->
            when (method.name) {
                "onMessage" -> {
                    val piece = extractText(args?.getOrNull(0))
                    if (piece.isNotEmpty()) {
                        acc.append(piece)
                        onDelta(piece)
                    }
                }
                "onDone" -> latch.countDown()
                "onError" -> {
                    err.set(args?.getOrNull(0) as? Throwable)
                    latch.countDown()
                }
            }
            null
        }
        async.invoke(conv, userText, callback)
        latch.await(3, TimeUnit.MINUTES)
        err.get()?.let { throw it }
        return acc.toString()
    }

    private fun extractText(value: Any?): String {
        if (value == null) return ""
        if (value is CharSequence) return value.toString()
        return try {
            val field = value.javaClass.methods.firstOrNull {
                it.name == "getText" && it.parameterCount == 0
            } ?: value.javaClass.methods.firstOrNull {
                it.name == "text" && it.parameterCount == 0
            }
            field?.invoke(value)?.toString().orEmpty().ifBlank { value.toString() }
        } catch (_: Exception) {
            value.toString()
        }
    }

    private fun cls(name: String): Class<*> = try {
        Class.forName(name)
    } catch (exc: ClassNotFoundException) {
        throw IllegalStateException("LiteRT is not in this APK.", exc)
    }

    private fun construct(type: Class<*>, vararg args: Any?): Any {
        val wanted = args.map { it?.javaClass }
        val ctor = type.constructors.firstOrNull { ctor ->
            ctor.parameterCount == args.size &&
                ctor.parameterTypes.zip(wanted).all { (need, got) ->
                    got == null || need.isAssignableFrom(got)
                }
        } ?: type.constructors.maxByOrNull { it.parameterCount }
            ?: throw IllegalStateException("No constructor for ${type.name}")
        val padded = Array(ctor.parameterCount) { i -> if (i < args.size) args[i] else null }
        return ctor.newInstance(*padded)
    }
}
