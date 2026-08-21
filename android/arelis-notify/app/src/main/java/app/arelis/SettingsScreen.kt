package app.arelis

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** Pairing and texts are once. Chat stays the home screen. */
@Composable
fun SettingsScreen(
    paired: Boolean,
    onBack: () -> Unit,
    onPair: () -> Unit,
    onTexts: () -> Unit,
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
            "← talk",
            color = Campfire.accent,
            modifier = Modifier.clickable(onClick = onBack).padding(bottom = 16.dp),
        )
        Text("Settings", color = Campfire.text, fontSize = 22.sp, fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.height(8.dp))
        Text(
            "Chat is home. Pairing and texts are one-time setup.",
            color = Campfire.dim,
            fontSize = 13.sp,
        )
        Spacer(Modifier.height(20.dp))
        Column(
            Modifier
                .fillMaxWidth()
                .clip(shape)
                .background(Campfire.bg1)
                .clickable(onClick = onPair)
                .padding(14.dp),
        ) {
            Text("Pairing", color = Campfire.text, fontWeight = FontWeight.Medium)
            Text(
                if (paired) {
                    "Already paired. Scan again only if the PC or this Wi-Fi changed."
                } else {
                    "Scan the QR on the PC. Same Wi-Fi. Once."
                },
                color = Campfire.dim,
                fontSize = 13.sp,
            )
        }
        Spacer(Modifier.height(10.dp))
        Column(
            Modifier
                .fillMaxWidth()
                .clip(shape)
                .background(Campfire.bg1)
                .clickable(onClick = onTexts)
                .padding(14.dp),
        ) {
            Text("Texts", color = Campfire.text, fontWeight = FontWeight.Medium)
            Text(
                "Optional. Google Messages stays your messenger. Skip this if you only talk to her.",
                color = Campfire.dim,
                fontSize = 13.sp,
            )
        }
    }
}
