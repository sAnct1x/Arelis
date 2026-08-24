package app.arelis

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** Pairing and texts are once. Chat stays the home screen. */
@Composable
fun SettingsScreen(
    paired: Boolean,
    language: String,
    onBack: () -> Unit,
    onPair: () -> Unit,
    onTexts: () -> Unit,
    onLanguage: (String) -> Unit,
) {
    EmberScreen {
        ScreenTop(title = "settings", onBack = onBack, backLabel = "← talk")
        Spacer(Modifier.height(Ember.gap))
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
            Text(
                "Chat is home. Pairing and texts are one-time setup.",
                color = Campfire.dim,
                fontSize = 14.sp,
            )
            Spacer(Modifier.height(Ember.gap))
            GlassCard(onClick = onPair, modifier = Modifier.fillMaxWidth()) {
                Text(
                    "pairing",
                    color = Campfire.accent,
                    fontSize = 11.sp,
                    letterSpacing = 1.8.sp,
                    fontWeight = FontWeight.SemiBold,
                )
                Spacer(Modifier.height(6.dp))
                Text(
                    if (paired) "linked to this house" else "not linked yet",
                    color = Campfire.text,
                    fontWeight = FontWeight.Medium,
                    fontSize = 17.sp,
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    if (paired) {
                        "The phone finds this PC on the LAN after Wi-Fi or DHCP moves. Scan only for a different PC."
                    } else {
                        "Scan the QR on the PC. Same Wi-Fi. Once."
                    },
                    color = Campfire.dim,
                    fontSize = 13.sp,
                    lineHeight = 18.sp,
                )
            }
            Spacer(Modifier.height(Ember.gap))
            GlassCard(modifier = Modifier.fillMaxWidth()) {
                Text(
                    "language",
                    color = Campfire.accent,
                    fontSize = 11.sp,
                    letterSpacing = 1.8.sp,
                    fontWeight = FontWeight.SemiBold,
                )
                Spacer(Modifier.height(6.dp))
                Text(
                    TalkLanguage.of(language).label,
                    color = Campfire.text,
                    fontWeight = FontWeight.Medium,
                    fontSize = 17.sp,
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    "Replies, the keyboard, and dictate follow this. Voice in other languages comes later.",
                    color = Campfire.dim,
                    fontSize = 13.sp,
                    lineHeight = 18.sp,
                )
                Spacer(Modifier.height(10.dp))
                TalkLanguage.all.forEach { lang ->
                    val selected = lang.code == TalkLanguage.normalize(language)
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .clip(EmberShapeTight)
                            .clickable { onLanguage(lang.code) }
                            .padding(vertical = 10.dp, horizontal = 4.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            lang.label,
                            color = Campfire.text,
                            fontSize = 16.sp,
                            modifier = Modifier.weight(1f),
                        )
                        if (selected) {
                            Text("selected", color = Campfire.accent, fontSize = 12.sp)
                        }
                    }
                }
            }
            Spacer(Modifier.height(Ember.gap))
            GlassCard(onClick = onTexts, modifier = Modifier.fillMaxWidth()) {
                Text(
                    "texts",
                    color = Campfire.accent,
                    fontSize = 11.sp,
                    letterSpacing = 1.8.sp,
                    fontWeight = FontWeight.SemiBold,
                )
                Spacer(Modifier.height(6.dp))
                Text("optional radio", color = Campfire.text, fontWeight = FontWeight.Medium, fontSize = 17.sp)
                Spacer(Modifier.height(4.dp))
                Text(
                    "Google Messages stays your messenger. Skip this if you only talk to her.",
                    color = Campfire.dim,
                    fontSize = 13.sp,
                    lineHeight = 18.sp,
                )
            }
        }
    }
}
