package app.arelis

import org.json.JSONObject

/**
 * House-served APK. Newer versionCode only — never a downgrade, never a
 * guess when the house has no file.
 */
data class CompanionUpdate(
    val later: Boolean = false,
    val downloading: Boolean = false,
    val houseCode: Int = 0,
    val houseName: String = "",
    val sizeText: String = "",
    val sha256: String = "",
    val signed: String = "",
    val staleNoApk: Boolean = false,
    val expectedName: String = "",
    val arelisVersion: String = "",
) {
    fun reduce(event: CompanionEvent): CompanionUpdate = when (event) {
        CompanionEvent.Later -> copy(later = true, downloading = false)
        CompanionEvent.Show -> copy(later = false)
        CompanionEvent.Install -> copy(later = false, downloading = true)
        is CompanionEvent.Progress -> this
        CompanionEvent.Failed -> copy(downloading = false)
        CompanionEvent.Installed -> copy(downloading = false, later = true)
    }

    fun toUi(progress: String = "", phoneCode: Int = 0, phoneName: String = ""): CompanionUpdateUi =
        CompanionUpdateUi(
            available = houseCode > phoneCode && houseCode > 0 && !later,
            downloading = downloading,
            progress = progress,
            later = later,
            staleNoApk = staleNoApk && !later,
            houseName = houseName,
            sizeText = sizeText,
            expectedName = expectedName,
            arelisVersion = arelisVersion,
            phoneName = phoneName,
            signed = signed,
        )
}

data class CompanionUpdateUi(
    val available: Boolean = false,
    val downloading: Boolean = false,
    val progress: String = "",
    val later: Boolean = false,
    val staleNoApk: Boolean = false,
    val houseName: String = "",
    val sizeText: String = "",
    val expectedName: String = "",
    val arelisVersion: String = "",
    val phoneName: String = "",
    val signed: String = "",
)

sealed class CompanionEvent {
    data object Later : CompanionEvent()
    data object Show : CompanionEvent()
    data object Install : CompanionEvent()
    data object Failed : CompanionEvent()
    data object Installed : CompanionEvent()
    data class Progress(val text: String) : CompanionEvent()
}

data class CompanionManifest(
    val arelisVersion: String,
    val houseCode: Int,
    val houseName: String,
    val sha256: String,
    val size: Long,
    val signed: String,
    val expectedCode: Int,
    val expectedName: String,
    val gemmaAvailable: Boolean,
) {
    fun offerFor(phoneCode: Int, dismissedCode: Int): CompanionUpdate {
        val newer = houseCode > phoneCode && houseCode > 0
        val stale = !newer && expectedCode > phoneCode && houseCode <= 0
        return CompanionUpdate(
            later = dismissedCode != 0 && dismissedCode == houseCode && newer,
            houseCode = houseCode,
            houseName = houseName,
            sizeText = sizeText(size),
            sha256 = sha256,
            signed = signed,
            staleNoApk = stale,
            expectedName = expectedName,
            arelisVersion = arelisVersion,
        )
    }

    companion object {
        fun parse(obj: JSONObject): CompanionManifest {
            val apk = obj.optJSONObject("apk")
            val expected = obj.optJSONObject("expected")
            val gemma = obj.optJSONObject("gemma")
            return CompanionManifest(
                arelisVersion = obj.optString("arelis"),
                houseCode = apk?.optInt("version_code") ?: 0,
                houseName = apk?.optString("version_name").orEmpty(),
                sha256 = apk?.optString("sha256").orEmpty(),
                size = apk?.optLong("size") ?: 0L,
                signed = apk?.optString("signed").orEmpty(),
                expectedCode = expected?.optInt("version_code") ?: 0,
                expectedName = expected?.optString("version_name").orEmpty(),
                gemmaAvailable = gemma?.optBoolean("available") == true,
            )
        }

        fun sizeText(size: Long): String = when {
            size >= 1_000_000 -> "${size / 1_000_000} MB"
            size >= 1_000 -> "${size / 1_000} KB"
            size > 0 -> "$size B"
            else -> ""
        }
    }
}

fun companionUpdateAvailable(phoneCode: Int, houseCode: Int): Boolean =
    houseCode > 0 && phoneCode > 0 && houseCode > phoneCode
