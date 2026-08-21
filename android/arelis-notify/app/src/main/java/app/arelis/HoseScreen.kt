package app.arelis

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** Optional SMS/RCS hose. Talking does not require any of this. */
@Composable
fun HoseScreen(
    grants: GrantState,
    onBack: () -> Unit,
    onOpenRestricted: () -> Unit,
    onGrantSms: () -> Unit,
    onOpenNotifications: () -> Unit,
    onOpenBattery: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Campfire.bg0)
            .verticalScroll(rememberScrollState())
            .padding(24.dp),
    ) {
        Text(
            "← back",
            color = Campfire.accent,
            modifier = Modifier.clickable(onClick = onBack).padding(bottom = 16.dp),
        )
        Text("Texts (optional)", color = Campfire.text, fontSize = 22.sp, fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.height(8.dp))
        Text(
            "Google Messages stays your messenger. These grants only let the PC send from this SIM after Allow, and let inbound RCS reach the PC. Skip this if you only want to talk to her.",
            color = Campfire.dim,
            fontSize = 13.sp,
        )
        Spacer(Modifier.height(20.dp))
        StepRow(
            done = !grants.restrictedHint || (grants.sms && grants.notifications),
            title = "Allow restricted settings",
            body = "Android 13+ hides SMS and notification access until you do this.",
            onClick = onOpenRestricted,
        )
        StepRow(
            done = grants.sms,
            title = "SMS",
            body = "So she can send from this SIM after Allow on the phone or PC.",
            onClick = onGrantSms,
        )
        StepRow(
            done = grants.notifications,
            title = "Notification access",
            body = "Inbound RCS from Google Messages. You still tap in Messages.",
            onClick = onOpenNotifications,
        )
        StepRow(
            done = grants.battery,
            title = "Battery Unrestricted",
            body = "Otherwise Doze drops inbound while the screen is off.",
            onClick = onOpenBattery,
        )
    }
}
