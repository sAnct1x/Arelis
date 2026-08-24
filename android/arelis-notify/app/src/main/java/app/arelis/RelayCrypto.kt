package app.arelis

import android.util.Base64
import java.io.ByteArrayOutputStream
import javax.crypto.Cipher
import javax.crypto.Mac
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

object RelayCrypto {
    private val info = "arelis-e2e-v1".toByteArray()

    fun e2eKey(token: String, instance: String): ByteArray =
        hkdf(token.toByteArray(), instance.toByteArray(), info, 32)

    fun seal(key: ByteArray, plaintext: ByteArray, aad: ByteArray): ByteArray {
        val nonce = ByteArray(12)
        java.security.SecureRandom().nextBytes(nonce)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, nonce))
        cipher.updateAAD(aad)
        return nonce + cipher.doFinal(plaintext)
    }

    fun open(key: ByteArray, blob: ByteArray, aad: ByteArray): ByteArray {
        require(blob.size >= 12 + 16) { "short box" }
        val nonce = blob.copyOfRange(0, 12)
        val ct = blob.copyOfRange(12, blob.size)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, nonce))
        cipher.updateAAD(aad)
        return cipher.doFinal(ct)
    }

    fun b64(data: ByteArray): String = Base64.encodeToString(data, Base64.NO_WRAP)

    fun unb64(text: String): ByteArray = Base64.decode(text, Base64.DEFAULT)

    fun hkdf(ikm: ByteArray, salt: ByteArray, info: ByteArray, length: Int): ByteArray {
        val mac = Mac.getInstance("HmacSHA256")
        val saltKey = if (salt.isEmpty()) ByteArray(32) else salt
        mac.init(SecretKeySpec(saltKey, "HmacSHA256"))
        val prk = mac.doFinal(ikm)
        val out = ByteArrayOutputStream()
        var prev = ByteArray(0)
        var counter = 1
        while (out.size() < length) {
            mac.init(SecretKeySpec(prk, "HmacSHA256"))
            mac.update(prev)
            mac.update(info)
            mac.update(counter.toByte())
            prev = mac.doFinal()
            out.write(prev)
            counter += 1
        }
        return out.toByteArray().copyOf(length)
    }
}

fun isMailboxUrl(url: String): Boolean {
    val trimmed = url.trim()
    if (trimmed.startsWith("https://", ignoreCase = true)) return true
    if (isLanIngestUrl(trimmed)) return false
    val host = try {
        java.net.URI(trimmed).host ?: return false
    } catch (_: Exception) {
        return false
    }
    return host.all { it.isDigit() || it == '.' }
}

fun isLanIngestUrl(url: String): Boolean {
    val host = try {
        java.net.URI(url).host?.lowercase() ?: return false
    } catch (_: Exception) {
        return false
    }
    if (host == "localhost" || host.endsWith(".local")) return true
    if (host.startsWith("127.")) return true
    if (host.startsWith("10.")) return true
    if (host.startsWith("192.168.")) return true
    if (host.startsWith("172.")) {
        val second = host.split(".").getOrNull(1)?.toIntOrNull() ?: return false
        return second in 16..31
    }
    return host.startsWith("<this-pc")
}
