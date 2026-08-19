package app.arelis

import android.content.Context
import android.telephony.SmsManager
import android.telephony.SubscriptionManager

class SmsSender(private val context: Context) {
    fun send(phone: String, body: String, simNumber: Int) {
        val manager = managerFor(simNumber)
        val parts = manager.divideMessage(body)
        if (parts == null || parts.size <= 1) {
            manager.sendTextMessage(phone, null, body, null, null)
        } else {
            manager.sendMultipartTextMessage(phone, null, parts, null, null)
        }
    }

    private fun managerFor(simNumber: Int): SmsManager {
        val fallback = SmsManager.getDefault()
        if (simNumber <= 0) return fallback
        val sm = context.getSystemService(Context.TELEPHONY_SUBSCRIPTION_SERVICE) as? SubscriptionManager
            ?: return fallback
        val info = sm.activeSubscriptionInfoList?.firstOrNull { it.simSlotIndex == simNumber - 1 }
        val subId = info?.subscriptionId ?: return fallback
        return SmsManager.getSmsManagerForSubscriptionId(subId)
    }
}
