package app.arelis

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

data class HomeState(
    val headline: String,
    val grants: GrantState,
    val paste: String,
    val busy: Boolean,
    val paired: Boolean,
)

@Composable
fun HomeScreen(
    state: HomeState,
    onOpenRestricted: () -> Unit,
    onGrantSms: () -> Unit,
    onOpenNotifications: () -> Unit,
    onOpenBattery: () -> Unit,
    onScan: () -> Unit,
    onPasteChange: (String) -> Unit,
    onPasteApply: () -> Unit,
) {
    val shape = RoundedCornerShape(12.dp)
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Campfire.bg0)
            .verticalScroll(rememberScrollState())
            .padding(24.dp),
    ) {
        Text(
            text = "Arelis",
            color = Campfire.accent,
            fontSize = 28.sp,
            fontWeight = FontWeight.SemiBold,
        )
        Spacer(Modifier.height(8.dp))
        Text(
            text = state.headline,
            color = Campfire.text,
            fontSize = 16.sp,
        )
        Spacer(Modifier.height(8.dp))
        Text(
            text = "Google Messages stays your messenger. This app is the hose: inbound RCS, and SMS out after you allow it on the PC.",
            color = Campfire.dim,
            fontSize = 13.sp,
        )
        Spacer(Modifier.height(24.dp))
        Text(
            text = "Walk-through",
            color = Campfire.hint,
            fontSize = 13.sp,
            fontWeight = FontWeight.Medium,
        )
        Spacer(Modifier.height(10.dp))
        StepRow(
            done = !state.grants.restrictedHint || (state.grants.sms && state.grants.notifications),
            title = "Allow restricted settings",
            body = "Settings → Apps → Arelis → ⋮ → Allow restricted settings. Android 13+ hides SMS and notification access until you do this.",
            onClick = onOpenRestricted,
        )
        StepRow(
            done = state.grants.sms,
            title = "SMS",
            body = "Grant SMS so she can send from this SIM after the card on the PC. You still text people in Google Messages.",
            onClick = onGrantSms,
        )
        StepRow(
            done = state.grants.notifications,
            title = "Notification access",
            body = "Turn on Arelis. That is how RCS arrives — SMSGate never sees those chats.",
            onClick = onOpenNotifications,
        )
        StepRow(
            done = state.grants.battery,
            title = "Battery Unrestricted",
            body = "Otherwise Doze drops inbound while the screen is off. Same miss as before.",
            onClick = onOpenBattery,
        )
        StepRow(
            done = state.paired,
            title = "Scan the QR",
            body = "On the PC: Settings → Notify. Same Wi-Fi. Uninstall the old Notify app and SMSGate after this pairs.",
            onClick = onScan,
        )
        Spacer(Modifier.height(20.dp))
        Text(
            text = "Paste instead",
            color = Campfire.hint,
            fontSize = 13.sp,
        )
        Spacer(Modifier.height(6.dp))
        BasicTextField(
            value = state.paste,
            onValueChange = onPasteChange,
            textStyle = TextStyle(color = Campfire.text, fontSize = 14.sp),
            cursorBrush = SolidColor(Campfire.accent),
            modifier = Modifier
                .fillMaxWidth()
                .clip(shape)
                .background(Campfire.well)
                .border(1.dp, Campfire.rim, shape)
                .padding(12.dp),
            decorationBox = { inner ->
                if (state.paste.isEmpty()) {
                    Text("Paste the pairing text from the PC", color = Campfire.coal, fontSize = 14.sp)
                }
                inner()
            },
        )
        Spacer(Modifier.height(10.dp))
        Text(
            text = if (state.busy) "Pairing…" else "Use pasted pairing",
            color = Campfire.bg0,
            fontWeight = FontWeight.Medium,
            modifier = Modifier
                .clip(shape)
                .background(Campfire.accent)
                .clickable(enabled = !state.busy, onClick = onPasteApply)
                .padding(horizontal = 16.dp, vertical = 10.dp),
        )
    }
}

@Composable
private fun StepRow(
    done: Boolean,
    title: String,
    body: String,
    onClick: () -> Unit,
) {
    val shape = RoundedCornerShape(12.dp)
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(bottom = 10.dp)
            .clip(shape)
            .background(Campfire.bg1)
            .border(1.dp, if (done) Campfire.accent.copy(alpha = 0.45f) else Campfire.rim, shape)
            .clickable(onClick = onClick)
            .padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(title, color = Campfire.text, fontWeight = FontWeight.Medium, fontSize = 15.sp)
            Text(if (done) "done" else "open", color = if (done) Campfire.accent else Campfire.hint, fontSize = 12.sp)
        }
        Text(body, color = Campfire.dim, fontSize = 13.sp)
    }
}
