package app.arelis

import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
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
    EmberScreen {
        GhostLink("← back", onBack)
        Spacer(Modifier.height(16.dp))
        Column(Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState())) {
            Text("texts", color = Campfire.text, fontSize = 26.sp, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(6.dp))
            Text(
                "Optional. Google Messages stays your messenger. These grants let the PC send from this SIM after Allow, and let inbound RCS reach the PC.",
                color = Campfire.dim,
                fontSize = 14.sp,
                lineHeight = 20.sp,
            )
            Spacer(Modifier.height(20.dp))
            StepRow(
                done = !grants.restrictedHint || (grants.sms && grants.notifications),
                title = "allow restricted settings",
                body = "Android 13+ hides SMS and notification access until you do this.",
                onClick = onOpenRestricted,
            )
            StepRow(
                done = grants.sms,
                title = "sms",
                body = "So she can send from this SIM after Allow on the phone or PC.",
                onClick = onGrantSms,
            )
            StepRow(
                done = grants.notifications,
                title = "notification access",
                body = "Inbound RCS from Google Messages. You still tap in Messages.",
                onClick = onOpenNotifications,
            )
            StepRow(
                done = grants.battery,
                title = "battery unrestricted",
                body = "Otherwise Doze drops inbound while the screen is off.",
                onClick = onOpenBattery,
            )
        }
    }
}
