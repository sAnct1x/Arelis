package app.arelis

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

data class TalkUi(
    val mode: HouseMode,
    val warmup: Boolean,
    val busy: Boolean,
    val draft: String,
    val bubbles: List<ChatBubble>,
    val allow: AllowCard?,
    val allowBusy: Boolean = false,
    val previewJpeg: ByteArray?,
    val gemma: GemmaUi,
    val error: String,
    val voiceMode: String,
    val listening: Boolean,
)

@Composable
fun TalkScreen(
    state: TalkUi,
    onDraft: (String) -> Unit,
    onSend: () -> Unit,
    onSettings: () -> Unit,
    onChats: () -> Unit,
    onFiles: () -> Unit,
    onCamera: () -> Unit,
    onDictate: () -> Unit,
    onTalk: () -> Unit,
    onAllow: () -> Unit,
    onDeny: () -> Unit,
    onGlance: (GlanceCard) -> Unit,
    onGemmaInstall: () -> Unit,
    onGemmaWaitWifi: () -> Unit,
    onGemmaLater: () -> Unit,
    onGemmaUseData: () -> Unit,
    onGemmaShow: () -> Unit,
) {
    val shape = RoundedCornerShape(12.dp)
    val list = rememberLazyListState()
    LaunchedEffect(state.bubbles.size, state.bubbles.lastOrNull()?.text) {
        if (state.bubbles.isNotEmpty()) {
            list.animateScrollToItem(state.bubbles.lastIndex)
        }
    }
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Campfire.bg0)
            .padding(16.dp),
    ) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Column(Modifier.weight(1f)) {
                Text("Arelis", color = Campfire.accent, fontSize = 22.sp, fontWeight = FontWeight.SemiBold)
                Text(
                    houseModeLabel(state.mode, state.warmup, state.allow != null),
                    color = Campfire.hint,
                    fontSize = 13.sp,
                )
            }
            Column(horizontalAlignment = Alignment.End) {
                if (state.mode == HouseMode.AtTheHouse) {
                    Text(
                        "chats",
                        color = Campfire.dim,
                        fontSize = 12.sp,
                        modifier = Modifier.clickable(onClick = onChats).padding(4.dp),
                    )
                    Text(
                        "files",
                        color = Campfire.dim,
                        fontSize = 12.sp,
                        modifier = Modifier.clickable(onClick = onFiles).padding(4.dp),
                    )
                }
                Text(
                    "settings",
                    color = Campfire.dim,
                    fontSize = 12.sp,
                    modifier = Modifier.clickable(onClick = onSettings).padding(4.dp),
                )
            }
        }
        if (state.error.isNotBlank()) {
            Spacer(Modifier.height(8.dp))
            Text(state.error, color = Campfire.danger, fontSize = 13.sp)
        }
        GemmaCard(
            state.gemma,
            onInstall = onGemmaInstall,
            onWaitWifi = onGemmaWaitWifi,
            onLater = onGemmaLater,
            onUseData = onGemmaUseData,
            onShow = onGemmaShow,
        )
        Spacer(Modifier.height(10.dp))
        LazyColumn(
            state = list,
            modifier = Modifier.weight(1f).fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            items(state.bubbles, key = { it.id }) { bubble ->
                BubbleView(bubble, onGlance)
            }
        }
        state.allow?.let { card ->
            Spacer(Modifier.height(8.dp))
            Column(
                Modifier
                    .fillMaxWidth()
                    .clip(shape)
                    .background(Campfire.bg1)
                    .border(1.dp, Campfire.accent.copy(alpha = 0.5f), shape)
                    .padding(12.dp),
            ) {
                Text(card.headline, color = Campfire.text, fontWeight = FontWeight.Medium)
                Text(card.summary, color = Campfire.dim, fontSize = 13.sp)
                Spacer(Modifier.height(10.dp))
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        if (state.allowBusy) "…" else "Allow",
                        color = Campfire.bg0,
                        fontWeight = FontWeight.Medium,
                        modifier = Modifier
                            .weight(1f)
                            .heightIn(min = 48.dp)
                            .clip(shape)
                            .background(if (state.allowBusy) Campfire.coal else Campfire.accent)
                            .clickable(enabled = !state.allowBusy, onClick = onAllow)
                            .padding(horizontal = 14.dp, vertical = 12.dp),
                    )
                    Text(
                        "Deny",
                        color = Campfire.danger,
                        fontWeight = FontWeight.Medium,
                        modifier = Modifier
                            .weight(1f)
                            .heightIn(min = 48.dp)
                            .clip(shape)
                            .background(Campfire.bg2)
                            .clickable(enabled = !state.allowBusy, onClick = onDeny)
                            .padding(horizontal = 14.dp, vertical = 12.dp),
                    )
                }
            }
        }
        state.previewJpeg?.let { bytes ->
            val bmp = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
            if (bmp != null) {
                Spacer(Modifier.height(8.dp))
                Image(
                    bitmap = bmp.asImageBitmap(),
                    contentDescription = "photo",
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(max = 160.dp)
                        .clip(shape),
                )
            }
        }
        Spacer(Modifier.height(8.dp))
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Latch(
                label = if (state.voiceMode == "dictate" && state.listening) "dictate…" else "dictate",
                on = state.voiceMode == "dictate",
                onClick = onDictate,
            )
            Latch(
                label = if (state.voiceMode == "conversation" && state.listening) "talk…" else "talk",
                on = state.voiceMode == "conversation",
                onClick = onTalk,
            )
            Text(
                "photo",
                color = Campfire.hint,
                modifier = Modifier.clickable(onClick = onCamera).padding(4.dp),
            )
        }
        Spacer(Modifier.height(8.dp))
        Row(
            Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.Bottom,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            BasicTextField(
                value = state.draft,
                onValueChange = onDraft,
                textStyle = TextStyle(color = Campfire.text, fontSize = 16.sp),
                cursorBrush = SolidColor(Campfire.accent),
                modifier = Modifier
                    .weight(1f)
                    .clip(shape)
                    .background(Campfire.well)
                    .border(1.dp, Campfire.rim, shape)
                    .padding(12.dp),
                decorationBox = { inner ->
                    Box {
                        if (state.draft.isEmpty()) {
                            Text(
                                when (state.voiceMode) {
                                    "dictate" -> "Speak — it lands here"
                                    "conversation" -> "Listening…"
                                    else -> "Talk to her"
                                },
                                color = Campfire.coal,
                                fontSize = 16.sp,
                            )
                        }
                        inner()
                    }
                },
            )
            Text(
                if (state.busy) "…" else "send",
                color = Campfire.bg0,
                modifier = Modifier
                    .clip(shape)
                    .background(if (state.busy) Campfire.coal else Campfire.accent)
                    .clickable(enabled = !state.busy, onClick = onSend)
                    .padding(horizontal = 12.dp, vertical = 10.dp),
            )
        }
    }
}

@Composable
private fun Latch(label: String, on: Boolean, onClick: () -> Unit) {
    val shape = RoundedCornerShape(12.dp)
    Text(
        label,
        color = if (on) Campfire.bg0 else Campfire.hint,
        fontSize = 13.sp,
        modifier = Modifier
            .clip(shape)
            .background(if (on) Campfire.accent else Campfire.bg2)
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 6.dp),
    )
}

@Composable
private fun GemmaCard(
    gemma: GemmaUi,
    onInstall: () -> Unit,
    onWaitWifi: () -> Unit,
    onLater: () -> Unit,
    onUseData: () -> Unit,
    onShow: () -> Unit,
) {
    val shape = RoundedCornerShape(12.dp)
    if (gemma.ready) return
    if (gemma.later && !gemma.downloading && !gemma.waitWifi && !gemma.confirmCellular) {
        Spacer(Modifier.height(8.dp))
        Text(
            "offline brain",
            color = Campfire.dim,
            fontSize = 12.sp,
            modifier = Modifier.clickable(onClick = onShow).padding(4.dp),
        )
        return
    }
    Spacer(Modifier.height(8.dp))
    Column(
        Modifier
            .fillMaxWidth()
            .clip(shape)
            .background(Campfire.bg1)
            .padding(12.dp),
    ) {
        when {
            gemma.downloading -> {
                Text(
                    gemma.progress.ifBlank { "Downloading the offline brain…" },
                    color = Campfire.accent2,
                    fontSize = 13.sp,
                )
            }
            gemma.confirmCellular -> {
                Text(
                    "This uses about 2.6 GB of mobile data and will run the battery. Same as any big update.",
                    color = Campfire.text,
                    fontSize = 13.sp,
                )
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Chip("Download now", accent = true, onClick = onUseData)
                    Chip("Wait for Wi-Fi", onClick = onWaitWifi)
                    Chip("Cancel", onClick = onLater)
                }
            }
            gemma.waitWifi -> {
                Text(
                    "Waiting for Wi-Fi to install the offline brain (~2.6 GB).",
                    color = Campfire.text,
                    fontSize = 13.sp,
                )
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Chip("Use mobile data", accent = true, onClick = onUseData)
                    Chip("Later", onClick = onLater)
                }
            }
            gemma.onWifi -> {
                Text(
                    "Install the offline brain (~2.6 GB) so you can still talk if the PC is down.",
                    color = Campfire.text,
                    fontSize = 13.sp,
                )
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Chip("Install", accent = true, onClick = onInstall)
                    Chip("Later", onClick = onLater)
                }
            }
            else -> {
                Text(
                    "Install the offline brain (~2.6 GB). Wi-Fi is nicer. Mobile data works if you want it now.",
                    color = Campfire.text,
                    fontSize = 13.sp,
                )
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Chip("Install now", accent = true, onClick = onInstall)
                    Chip("Wait for Wi-Fi", onClick = onWaitWifi)
                    Chip("Later", onClick = onLater)
                }
            }
        }
    }
}

@Composable
private fun Chip(label: String, accent: Boolean = false, onClick: () -> Unit) {
    val shape = RoundedCornerShape(12.dp)
    Text(
        label,
        color = if (accent) Campfire.bg0 else Campfire.hint,
        fontSize = 13.sp,
        modifier = Modifier
            .clip(shape)
            .background(if (accent) Campfire.accent else Campfire.bg2)
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 6.dp),
    )
}

@Composable
private fun BubbleView(bubble: ChatBubble, onGlance: (GlanceCard) -> Unit) {
    val mine = bubble.role == "user"
    val shape = RoundedCornerShape(12.dp)
    Column(
        modifier = Modifier.fillMaxWidth(),
        horizontalAlignment = if (mine) Alignment.End else Alignment.Start,
    ) {
        Text(
            text = bubble.text.ifBlank { if (bubble.streaming) "…" else "" },
            color = Campfire.text,
            fontSize = 15.sp,
            modifier = Modifier
                .clip(shape)
                .background(if (mine) Campfire.bg2 else Campfire.bg1)
                .padding(10.dp),
        )
        bubble.glances.forEach { glance ->
            Text(
                glance.title,
                color = Campfire.accent2,
                fontSize = 12.sp,
                modifier = Modifier
                    .padding(top = 4.dp)
                    .clip(shape)
                    .background(Campfire.raised)
                    .clickable { onGlance(glance) }
                    .padding(horizontal = 10.dp, vertical = 6.dp),
            )
        }
    }
}
