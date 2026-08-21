package app.arelis

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
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
    val shape = RoundedCornerShape(12.dp)
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Campfire.bg0)
            .verticalScroll(rememberScrollState())
            .padding(24.dp),
    ) {
        if (onBack != null) {
            Text(
                "← back",
                color = Campfire.accent,
                modifier = Modifier.clickable(onClick = onBack).padding(bottom = 16.dp),
            )
        }
        Text("Arelis", color = Campfire.accent, fontSize = 28.sp, fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.height(8.dp))
        Text(headline, color = Campfire.text, fontSize = 16.sp)
        Spacer(Modifier.height(8.dp))
        Text(
            "Same Wi-Fi as the PC. Scan once. Then you talk. Texts from this SIM are optional, later.",
            color = Campfire.dim,
            fontSize = 13.sp,
        )
        Spacer(Modifier.height(8.dp))
        Text(
            "After pair, install the offline brain (~2.6 GB) so she still talks if the PC is down. Wi-Fi is nicer; mobile data is your call.",
            color = Campfire.hint,
            fontSize = 13.sp,
        )
        Spacer(Modifier.height(24.dp))
        Text(
            if (busy) "Pairing…" else "Scan the QR",
            color = Campfire.bg0,
            fontWeight = FontWeight.Medium,
            modifier = Modifier
                .clip(shape)
                .background(Campfire.accent)
                .clickable(enabled = !busy, onClick = onScan)
                .padding(horizontal = 16.dp, vertical = 12.dp),
        )
        Spacer(Modifier.height(20.dp))
        Text("Or paste the pairing text", color = Campfire.hint, fontSize = 13.sp)
        Spacer(Modifier.height(6.dp))
        BasicTextField(
            value = paste,
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
                if (paste.isEmpty()) {
                    Text("Paste from Settings → Notify", color = Campfire.coal, fontSize = 14.sp)
                }
                inner()
            },
        )
        Spacer(Modifier.height(10.dp))
        Text(
            "Use pasted pairing",
            color = Campfire.bg0,
            modifier = Modifier
                .clip(shape)
                .background(Campfire.accent)
                .clickable(enabled = !busy, onClick = onPasteApply)
                .padding(horizontal = 16.dp, vertical = 10.dp),
        )
    }
}
