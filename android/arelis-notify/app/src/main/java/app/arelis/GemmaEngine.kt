package app.arelis

import android.content.Context
import java.io.File
import java.lang.reflect.InvocationTargetException
import java.lang.reflect.Method
import java.lang.reflect.Proxy
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
    private var loadedSystem = ""
    private var sees = false

    fun loaded(): Boolean = synchronized(lock) { engine != null }

    fun unload() {
        synchronized(lock) { unloadUnsafe() }
    }

    private fun unloadUnsafe() {
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
        loadedSystem = ""
        sees = false
    }

    fun ensure(context: Context, model: File, system: String) {
        synchronized(lock) {
            if (engine != null && conversation != null) return
            try {
                if (engine == null) {
                    Class.forName("com.google.ai.edge.litertlm.LiteRtLmJni")
                    engine = runCatching { openEngine(context, model, withVision = true) }
                        .onSuccess { sees = true }
                        .recoverCatching {
                            sees = false
                            openEngine(context, model, withVision = false)
                        }
                        .getOrThrow()
                }
                if (conversation == null) {
                    val contents = GemmaReflect.companionCall(
                        GemmaReflect.cls("com.google.ai.edge.litertlm.Contents"),
                        "of",
                        system,
                    )
                    val convCfg = GemmaReflect.construct(
                        GemmaReflect.cls("com.google.ai.edge.litertlm.ConversationConfig"),
                        contents,
                    )
                    val conv = GemmaReflect.call(engine!!, "createConversation", convCfg)
                        ?: throw IllegalStateException("Could not start a Gemma conversation.")
                    conversation = conv as AutoCloseable
                    loadedSystem = system
                }
            } catch (exc: Exception) {
                unloadUnsafe()
                throw IllegalStateException(humanGemmaError(exc), exc)
            }
        }
    }

    private fun openEngine(context: Context, model: File, withVision: Boolean): AutoCloseable {
        val cpu = GemmaReflect.backend("CPU")
        val vision = if (withVision) {
            runCatching { GemmaReflect.backend("GPU") }.getOrElse { GemmaReflect.backend("CPU") }
        } else {
            null
        }
        val cfg = GemmaReflect.construct(
            GemmaReflect.cls("com.google.ai.edge.litertlm.EngineConfig"),
            model.absolutePath,
            cpu,
            vision,
            null,
            null,
            if (withVision) 4 else null,
            context.cacheDir.absolutePath,
        )
        val eng = GemmaReflect.construct(GemmaReflect.cls("com.google.ai.edge.litertlm.Engine"), cfg)
        try {
            GemmaReflect.call(eng, "initialize")
        } catch (exc: Exception) {
            runCatching { (eng as AutoCloseable).close() }
            throw exc
        }
        return eng as AutoCloseable
    }

    fun reply(userText: String, onDelta: (String) -> Unit): String =
        reply(userText, imageJpeg = null, onDelta = onDelta)

    fun reply(userText: String, imageJpeg: ByteArray?, onDelta: (String) -> Unit): String {
        val (conv, canSee) = synchronized(lock) {
            conversation to sees
        }
        if (conv == null) throw IllegalStateException("Gemma is not loaded.")
        if (imageJpeg != null && imageJpeg.isNotEmpty() && !canSee) {
            throw IllegalStateException(
                "Gemma's vision encoder didn't start on this phone. Talk still works; photos wait until the house is back.",
            )
        }
        val payload = messagePayload(userText, imageJpeg)
        val empty = java.util.HashMap<String, Any>()
        val sent = runCatching {
            GemmaReflect.call(conv, "sendMessage", payload, empty)
        }.recoverCatching {
            GemmaReflect.call(conv, "sendMessage", payload)
        }.getOrNull()
        val text = extractText(sent)
        if (text.isNotEmpty()) {
            onDelta(text)
            return text
        }
        return streamAsync(conv, payload, onDelta)
    }

    private fun messagePayload(userText: String, imageJpeg: ByteArray?): Any {
        val prompt = userText.trim().ifBlank { "Look at this photo and describe what you see." }
        if (imageJpeg == null || imageJpeg.isEmpty()) return prompt
        val contentCls = GemmaReflect.cls("com.google.ai.edge.litertlm.Content")
        val image = GemmaReflect.construct(GemmaReflect.nested(contentCls, "ImageBytes"), imageJpeg)
        val text = GemmaReflect.construct(GemmaReflect.nested(contentCls, "Text"), prompt)
        return GemmaReflect.contentsOf(image, text)
    }

    private fun streamAsync(conv: Any, payload: Any, onDelta: (String) -> Unit): String {
        val callbackClass = try {
            Class.forName("com.google.ai.edge.litertlm.MessageCallback")
        } catch (_: ClassNotFoundException) {
            return ""
        }
        val latch = CountDownLatch(1)
        val acc = StringBuilder()
        val err = AtomicReference<Throwable?>(null)
        val callback = Proxy.newProxyInstance(
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
        val empty = java.util.HashMap<String, Any>()
        val started = runCatching {
            GemmaReflect.call(conv, "sendMessageAsync", payload, callback, empty)
        }.recoverCatching {
            GemmaReflect.call(conv, "sendMessageAsync", payload, callback)
        }
        if (started.isFailure) return ""
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

    companion object {
        fun present(): Boolean = try {
            Class.forName("com.google.ai.edge.litertlm.Engine")
            true
        } catch (_: ClassNotFoundException) {
            false
        }
    }
}

/** Reflection against LiteRT-LM 0.13.1. Nested CPU is a data class, not Backend.CPU(). */
internal object GemmaReflect {
    fun cls(name: String): Class<*> = try {
        Class.forName(name)
    } catch (exc: ClassNotFoundException) {
        throw IllegalStateException(
            "The on-phone brain runtime is missing from this APK. Rebuild from Android Studio.",
            exc,
        )
    }

    fun nested(parent: Class<*>, simple: String): Class<*> {
        return parent.declaredClasses.firstOrNull { it.simpleName == simple }
            ?: Class.forName("${parent.name}\$$simple")
    }

    fun backend(kind: String): Any {
        val nested = nested(cls("com.google.ai.edge.litertlm.Backend"), kind)
        return runCatching { construct(nested) }.getOrElse { construct(nested, null) }
    }

    fun construct(type: Class<*>, vararg args: Any?): Any {
        val ctors = type.declaredConstructors.filter { ctor ->
            ctor.parameterTypes.none { it.name.contains("DefaultConstructorMarker") }
        }
        val exact = ctors.firstOrNull { ctor ->
            ctor.parameterCount == args.size &&
                ctor.parameterTypes.zip(args.toList()).all { (need, got) -> compatible(need, got) }
        }
        val ctor = exact ?: ctors
            .filter { it.parameterCount >= args.size }
            .minByOrNull { it.parameterCount }
            ?: throw IllegalStateException("No constructor for ${type.name}")
        ctor.isAccessible = true
        val padded = Array<Any?>(ctor.parameterCount) { i -> if (i < args.size) args[i] else null }
        return unwrap(newJava(ctor, padded))
            ?: throw IllegalStateException("Could not construct ${type.name}")
    }

    fun contentsOf(vararg parts: Any): Any {
        val contentsCls = cls("com.google.ai.edge.litertlm.Contents")
        val contentCls = cls("com.google.ai.edge.litertlm.Content")
        val arr = java.lang.reflect.Array.newInstance(contentCls, parts.size)
        parts.forEachIndexed { i, part -> java.lang.reflect.Array.set(arr, i, part) }
        val methods = (contentsCls.methods + runCatching {
            contentsCls.getDeclaredField("Companion").apply { isAccessible = true }
                .get(null)?.javaClass?.methods ?: emptyArray()
        }.getOrDefault(emptyArray())).filter { it.name == "of" && !it.isSynthetic }
        val vararg = methods.firstOrNull {
            it.parameterCount == 1 && it.parameterTypes[0].isArray
        }
        if (vararg != null) {
            val target = if (java.lang.reflect.Modifier.isStatic(vararg.modifiers)) {
                null
            } else {
                contentsCls.getDeclaredField("Companion").apply { isAccessible = true }.get(null)
            }
            vararg.isAccessible = true
            return unwrap(callJava(vararg, target, arrayOf(arr)))
                ?: throw IllegalStateException("Could not pack photo contents.")
        }
        return companionCall(contentsCls, "of", *parts)
            ?: throw IllegalStateException("Could not pack photo contents.")
    }

    fun companionCall(type: Class<*>, name: String, vararg args: Any?): Any? {
        val static = pick(
            type.methods.filter { it.name == name && java.lang.reflect.Modifier.isStatic(it.modifiers) },
            args,
        )
        if (static != null) {
            static.isAccessible = true
            return unwrap(callJava(static, null, args))
        }
        val companion = type.getDeclaredField("Companion").apply { isAccessible = true }.get(null)
            ?: throw IllegalStateException("No Companion on ${type.name}")
        return call(companion, name, *args)
    }

    fun call(target: Any, name: String, vararg args: Any?): Any? {
        val method = pick(target.javaClass.methods.filter { it.name == name }, args)
            ?: throw IllegalStateException(
                "No $name(${args.joinToString { it?.javaClass?.simpleName ?: "null" }}) on ${target.javaClass.name}",
            )
        method.isAccessible = true
        return unwrap(callJava(method, target, args))
    }

    @Suppress("UNCHECKED_CAST")
    private fun newJava(ctor: java.lang.reflect.Constructor<*>, args: Array<Any?>): Any? {
        return ctor.newInstance(*(args as Array<Any>))
    }

    @Suppress("UNCHECKED_CAST")
    private fun callJava(method: Method, target: Any?, args: Array<out Any?>): Any? {
        return method.invoke(target, *(args as Array<Any>))
    }

    internal fun pick(methods: List<Method>, args: Array<out Any?>): Method? {
        return methods
            .filter { !it.isSynthetic && !it.isBridge }
            .firstOrNull { method ->
                method.parameterCount == args.size &&
                    method.parameterTypes.zip(args.toList()).all { (need, got) -> compatible(need, got) }
            }
    }

    internal fun compatible(need: Class<*>, got: Any?): Boolean {
        if (got == null) return !need.isPrimitive
        if (need.isAssignableFrom(got.javaClass)) return true
        val boxes = mapOf(
            java.lang.Integer.TYPE to java.lang.Integer::class.java,
            java.lang.Long.TYPE to java.lang.Long::class.java,
            java.lang.Boolean.TYPE to java.lang.Boolean::class.java,
            java.lang.Double.TYPE to java.lang.Double::class.java,
            java.lang.Float.TYPE to java.lang.Float::class.java,
        )
        return boxes[need] == got.javaClass
    }

    private fun unwrap(value: Any?): Any? {
        if (value is InvocationTargetException) {
            throw (value.cause ?: value)
        }
        return value
    }
}
