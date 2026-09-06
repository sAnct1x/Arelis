package app.arelis

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.net.Uri
import android.provider.ContactsContract
import android.provider.Telephony
import androidx.core.content.ContextCompat
import org.json.JSONArray
import org.json.JSONObject

data class PhonePerson(
    val phone: String,
    val name: String,
    val count: Int,
)

data class AddressHit(
    val address: String,
    val count: Int,
    val lastMs: Long,
)

/** Rank SMS addresses by how often and how recently they show up. */
fun rankAddressHits(hits: List<Pair<String, Long>>, limit: Int = 25): List<AddressHit> {
    val grouped = linkedMapOf<String, AddressHit>()
    for ((raw, dateMs) in hits) {
        val key = normalizeThreadAddress(raw)
        if (key.length < 10) continue
        val prior = grouped[key]
        if (prior == null) {
            grouped[key] = AddressHit(key, 1, dateMs)
        } else {
            grouped[key] = AddressHit(
                key,
                prior.count + 1,
                maxOf(prior.lastMs, dateMs),
            )
        }
    }
    return grouped.values
        .sortedWith(compareByDescending<AddressHit> { it.count }.thenByDescending { it.lastMs })
        .take(limit.coerceAtLeast(1))
}

fun normalizeThreadAddress(value: String): String {
    val digits = value.filter { it.isDigit() }
    return if (digits.length == 11 && digits.startsWith("1")) digits.drop(1) else digits
}

fun loadFrequentPeople(context: Context, limit: Int = 25): List<PhonePerson> {
    val hits = if (hasPermission(context, Manifest.permission.READ_SMS)) {
        loadSmsHits(context)
    } else {
        emptyList()
    }
    val ranked = rankAddressHits(hits, limit)
    if (ranked.isNotEmpty()) {
        return ranked.map { hit ->
            PhonePerson(
                phone = hit.address,
                name = lookupDisplayName(context, hit.address),
                count = hit.count,
            )
        }
    }
    return loadStarredPeople(context, limit)
}

fun peopleToJson(people: List<PhonePerson>): JSONObject {
    val rows = JSONArray()
    for (person in people) {
        rows.put(
            JSONObject()
                .put("phone", person.phone)
                .put("name", person.name)
                .put("count", person.count),
        )
    }
    return JSONObject().put("people", rows)
}

private fun hasPermission(context: Context, permission: String): Boolean =
    ContextCompat.checkSelfPermission(context, permission) == PackageManager.PERMISSION_GRANTED

private fun loadSmsHits(context: Context): List<Pair<String, Long>> {
    val out = ArrayList<Pair<String, Long>>(512)
    val uri = Telephony.Sms.CONTENT_URI
    val projection = arrayOf(Telephony.Sms.ADDRESS, Telephony.Sms.DATE)
    try {
        context.contentResolver.query(
            uri,
            projection,
            null,
            null,
            "${Telephony.Sms.DATE} DESC",
        )?.use { cursor ->
            val addr = cursor.getColumnIndex(Telephony.Sms.ADDRESS)
            val date = cursor.getColumnIndex(Telephony.Sms.DATE)
            var n = 0
            while (cursor.moveToNext() && n < 2000) {
                val address = cursor.getString(addr).orEmpty()
                val whenMs = cursor.getLong(date)
                if (address.isNotBlank()) out.add(address to whenMs)
                n += 1
            }
        }
    } catch (_: SecurityException) {
        return emptyList()
    }
    return out
}

private fun lookupDisplayName(context: Context, phone: String): String {
    if (!hasPermission(context, Manifest.permission.READ_CONTACTS)) return ""
    val uri = Uri.withAppendedPath(
        ContactsContract.PhoneLookup.CONTENT_FILTER_URI,
        Uri.encode(phone),
    )
    return try {
        context.contentResolver.query(
            uri,
            arrayOf(ContactsContract.PhoneLookup.DISPLAY_NAME),
            null,
            null,
            null,
        )?.use { cursor ->
            if (cursor.moveToFirst()) cursor.getString(0).orEmpty() else ""
        }.orEmpty()
    } catch (_: SecurityException) {
        ""
    }
}

private fun loadStarredPeople(context: Context, limit: Int): List<PhonePerson> {
    if (!hasPermission(context, Manifest.permission.READ_CONTACTS)) return emptyList()
    val out = ArrayList<PhonePerson>()
    try {
        context.contentResolver.query(
            ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
            arrayOf(
                ContactsContract.CommonDataKinds.Phone.NUMBER,
                ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME,
                ContactsContract.CommonDataKinds.Phone.STARRED,
            ),
            "${ContactsContract.CommonDataKinds.Phone.STARRED}=1",
            null,
            null,
        )?.use { cursor ->
            val num = cursor.getColumnIndex(ContactsContract.CommonDataKinds.Phone.NUMBER)
            val name = cursor.getColumnIndex(ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME)
            while (cursor.moveToNext() && out.size < limit) {
                val phone = normalizeThreadAddress(cursor.getString(num).orEmpty())
                if (phone.length < 10) continue
                if (out.any { it.phone == phone }) continue
                out.add(
                    PhonePerson(
                        phone = phone,
                        name = cursor.getString(name).orEmpty(),
                        count = 0,
                    ),
                )
            }
        }
    } catch (_: SecurityException) {
        return emptyList()
    }
    return out
}
