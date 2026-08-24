package app.arelis

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@Composable
fun PairScreen(
    headline: String,
    paste: String,
    busy: Boolean,
    onBack: (() -> Unit)? = null,
    onScan: () -> Unit,
    onPasteChange: (String) -> Unit,
    onPasteApply: () -> Unit,
) {
    EmberScreen {
        if (onBack != null) {
            GhostLink("← back", onBack)
            Spacer(Modifier.height(12.dp))
        }
        BrandMark(subtitle = headline, mode = HouseMode.Pairing)
        Spacer(Modifier.height(8.dp))
        Text(
            "Same Wi-Fi as the PC. Scan once. The phone finds the house again after you leave and come back — no new QR for a DHCP move.",
            color = Campfire.dim,
            fontSize = 14.sp,
            lineHeight = 20.sp,
        )
        Spacer(Modifier.height(10.dp))
        Text(
            "After pair, install the offline brain (~2.6 GB) so she still talks if the PC is down.",
            color = Campfire.coal,
            fontSize = 13.sp,
            lineHeight = 18.sp,
        )
        Spacer(Modifier.height(28.dp))
        EmberButton(
            if (busy) "pairing…" else "scan the qr",
            onClick = onScan,
            modifier = Modifier.fillMaxWidth(),
            enabled = !busy,
        )
        Spacer(Modifier.height(28.dp))
        Text(
            "or paste the pairing text",
            color = Campfire.coal,
            fontSize = 11.sp,
            letterSpacing = 1.6.sp,
            fontWeight = FontWeight.SemiBold,
        )
        Spacer(Modifier.height(8.dp))
        BasicTextField(
            value = paste,
            onValueChange = onPasteChange,
            textStyle = TextStyle(color = Campfire.text, fontSize = 14.sp),
            cursorBrush = SolidColor(Campfire.accent),
            modifier = Modifier
                .fillMaxWidth()
                .clip(EmberShape)
                .background(Campfire.well)
                .border(1.dp, Campfire.rim, EmberShape)
                .padding(14.dp)
                .height(72.dp)
                .verticalScroll(rememberScrollState()),
            decorationBox = { inner ->
                if (paste.isEmpty()) {
                    Text("From Settings → Notify", color = Campfire.coal, fontSize = 14.sp)
                }
                inner()
            },
        )
        Spacer(Modifier.height(12.dp))
        EmberButton(
            "use pasted pairing",
            onClick = onPasteApply,
            modifier = Modifier.fillMaxWidth(),
            accent = false,
            enabled = !busy,
        )
    }
}
