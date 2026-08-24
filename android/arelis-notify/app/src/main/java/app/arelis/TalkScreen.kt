package app.arelis

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
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
    val attachName: String = "",
    val gemma: GemmaUi,
    val error: String,
    val voiceMode: String,
    val listening: Boolean,
    val roomName: String = "",
    val languageTag: String = "en-US",
)

@Composable
fun TalkScreen(
    state: TalkUi,
    onDraft: (String) -> Unit,
    onSend: () -> Unit,
    onSettings: () -> Unit,
    onChats: () -> Unit,
    onFiles: () -> Unit,
    onAttach: (String) -> Unit,
    onClearAttach: () -> Unit,
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
    val list = rememberLazyListState()
    LaunchedEffect(state.bubbles.size) {
        if (state.bubbles.isNotEmpty()) {
            list.animateScrollToItem(state.bubbles.lastIndex)
        }
    }
    val subtitle = talkSubtitle(
        state.mode,
        state.warmup,
        state.allow != null,
        state.roomName,
        state.gemma,
    )
    val idle = state.bubbles.isEmpty()
    var attachOpen by remember { mutableStateOf(false) }
    BackHandler(enabled = attachOpen) { attachOpen = false }
    HintImeLanguage(state.languageTag)
    Box(Modifier.fillMaxSize()) {
    EmberScreen {
        if (idle) {
            Box(Modifier.weight(1f).fillMaxSize()) {
                IdleFace(
                    title = when (state.mode) {
                        HouseMode.OnThePhone -> "on the phone"
                        HouseMode.Connecting -> "finding the house"
                        else -> "what are we working on"
                    },
                    body = phoneIdleBody(state.mode, state.gemma),
                    thinking = state.warmup || state.busy,
                    modifier = Modifier
                        .align(Alignment.Center)
                        .offset(y = (-20).dp),
                )
                Column(Modifier.align(Alignment.TopStart).fillMaxWidth()) {
                    TalkTopBar(
                        state = state,
                        subtitle = subtitle,
                        showGemma = false,
                        onChats = onChats,
                        onFiles = onFiles,
                        onSettings = onSettings,
                        onGemmaInstall = onGemmaInstall,
                        onGemmaWaitWifi = onGemmaWaitWifi,
                        onGemmaLater = onGemmaLater,
                        onGemmaUseData = onGemmaUseData,
                        onGemmaShow = onGemmaShow,
                    )
                }
                Column(Modifier.align(Alignment.BottomStart).fillMaxWidth()) {
                    GemmaBanner(
                        state.gemma,
                        onInstall = onGemmaInstall,
                        onWaitWifi = onGemmaWaitWifi,
                        onLater = onGemmaLater,
                        onUseData = onGemmaUseData,
                        onShow = onGemmaShow,
                    )
                    TalkComposer(
                        state = state,
                        onDraft = onDraft,
                        onSend = onSend,
                        onAttach = { attachOpen = true },
                        onClearAttach = onClearAttach,
                        onDictate = onDictate,
                        onTalk = onTalk,
                        onAllow = onAllow,
                        onDeny = onDeny,
                    )
                }
            }
        } else {
            TalkTopBar(
                state = state,
                subtitle = subtitle,
                showGemma = true,
                onChats = onChats,
                onFiles = onFiles,
                onSettings = onSettings,
                onGemmaInstall = onGemmaInstall,
                onGemmaWaitWifi = onGemmaWaitWifi,
                onGemmaLater = onGemmaLater,
                onGemmaUseData = onGemmaUseData,
                onGemmaShow = onGemmaShow,
            )
            Spacer(Modifier.height(Ember.gap))
            LazyColumn(
                state = list,
                modifier = Modifier.weight(1f).fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(Ember.gap),
            ) {
                items(state.bubbles, key = { it.id }) { bubble ->
                    BubbleView(bubble, onGlance)
                }
            }
            TalkComposer(
                state = state,
                onDraft = onDraft,
                onSend = onSend,
                onAttach = { attachOpen = true },
                onClearAttach = onClearAttach,
                onDictate = onDictate,
                onTalk = onTalk,
                onAllow = onAllow,
                onDeny = onDeny,
            )
        }
    }
        if (attachOpen) {
            Box(
                Modifier
                    .fillMaxSize()
                    .background(Color(0xCC160D07))
                    .clickable { attachOpen = false },
            )
            Column(
                Modifier
                    .align(Alignment.BottomCenter)
                    .fillMaxWidth()
                    .padding(horizontal = Ember.screenX, vertical = 20.dp)
                    .clickable(
                        indication = null,
                        interactionSource = remember { MutableInteractionSource() },
                    ) {},
            ) {
                AttachSheet(
                    onTake = {
                        attachOpen = false
                        onAttach("take")
                    },
                    onLibrary = {
                        attachOpen = false
                        onAttach("library")
                    },
                    onFile = {
                        attachOpen = false
                        onAttach("file")
                    },
                    onDismiss = { attachOpen = false },
                )
            }
        }
    }
}

@Composable
private fun HintImeLanguage(tag: String) {
    val view = LocalView.current
    DisposableEffect(tag) {
        val locales = android.os.LocaleList.forLanguageTags(tag)
        applyImeHint(view, locales)
        onDispose { applyImeHint(view, null) }
    }
}

/** Compose's LocalView is not a TextView. SDK 34 only has the hint on TextView. */
private fun applyImeHint(view: android.view.View, locales: android.os.LocaleList?) {
    val setter = view.javaClass.methods.firstOrNull {
        it.name == "setImeHintLocales" && it.parameterCount == 1
    }
    if (setter != null) {
        runCatching { setter.invoke(view, locales) }
        return
    }
    val focused = view.findFocus()
    if (focused is android.widget.TextView) {
        focused.setImeHintLocales(locales)
    }
}

@Composable
private fun TalkTopBar(
    state: TalkUi,
    subtitle: String,
    showGemma: Boolean = true,
    onChats: () -> Unit,
    onFiles: () -> Unit,
    onSettings: () -> Unit,
    onGemmaInstall: () -> Unit,
    onGemmaWaitWifi: () -> Unit,
    onGemmaLater: () -> Unit,
    onGemmaUseData: () -> Unit,
    onGemmaShow: () -> Unit,
) {
    Column(Modifier.fillMaxWidth()) {
        BrandMark(
            subtitle = subtitle,
            mode = state.mode,
            confirm = state.allow != null,
            warmup = state.warmup,
        )
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            NavLink("chats", onChats)
            NavLink("files", onFiles)
            NavLink("settings", onSettings)
        }
    }
    if (state.error.isNotBlank()) {
        Spacer(Modifier.height(Ember.gap))
        Text(
            state.error,
            color = Campfire.danger,
            fontSize = 13.sp,
            lineHeight = 18.sp,
            modifier = Modifier
                .fillMaxWidth()
                .clip(EmberShapeTight)
                .background(Campfire.bg2)
                .padding(horizontal = 14.dp, vertical = 12.dp),
        )
    }
    if (showGemma) {
        GemmaBanner(
            state.gemma,
            onInstall = onGemmaInstall,
            onWaitWifi = onGemmaWaitWifi,
            onLater = onGemmaLater,
            onUseData = onGemmaUseData,
            onShow = onGemmaShow,
        )
    }
}

@Composable
private fun TalkComposer(
    state: TalkUi,
    onDraft: (String) -> Unit,
    onSend: () -> Unit,
    onAttach: () -> Unit,
    onClearAttach: () -> Unit,
    onDictate: () -> Unit,
    onTalk: () -> Unit,
    onAllow: () -> Unit,
    onDeny: () -> Unit,
) {
    state.allow?.let { card ->
        Spacer(Modifier.height(Ember.gap))
        GlassCard(hot = true) {
            Text("allow", color = Campfire.accent, fontSize = 11.sp, letterSpacing = 1.2.sp, fontWeight = FontWeight.Medium)
            Spacer(Modifier.height(6.dp))
            Text(card.headline, color = Campfire.text, fontWeight = FontWeight.SemiBold, fontSize = 16.sp)
            if (card.summary.isNotBlank()) {
                Spacer(Modifier.height(4.dp))
                Text(card.summary, color = Campfire.dim, fontSize = 13.sp)
            }
            Spacer(Modifier.height(12.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                EmberButton(
                    if (state.allowBusy) "…" else "allow",
                    onClick = onAllow,
                    modifier = Modifier.weight(1f),
                    enabled = !state.allowBusy,
                )
                EmberButton(
                    "deny",
                    onClick = onDeny,
                    modifier = Modifier.weight(1f),
                    accent = false,
                    danger = true,
                    enabled = !state.allowBusy,
                )
            }
        }
    }
    state.previewJpeg?.let { bytes ->
        val bmp = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
        if (bmp != null) {
            Spacer(Modifier.height(Ember.gap))
            Image(
                bitmap = bmp.asImageBitmap(),
                contentDescription = "photo",
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(max = 180.dp)
                    .clip(EmberShape)
                    .border(1.dp, Campfire.rim, EmberShape)
                    .clickable(onClick = onClearAttach),
            )
            GhostLink("remove photo", onClearAttach)
        }
    }
    if (state.attachName.isNotBlank() && state.previewJpeg == null) {
        Spacer(Modifier.height(Ember.gap))
        GlassCard {
            Text(state.attachName, color = Campfire.text, fontSize = 15.sp)
            Spacer(Modifier.height(6.dp))
            GhostLink("remove file", onClearAttach)
        }
    }
    Spacer(Modifier.height(Ember.gap))
    Row(
        Modifier
            .fillMaxWidth()
            .imePadding()
            .clip(EmberDock)
            .background(Campfire.well)
            .border(1.dp, Campfire.rim, EmberDock)
            .padding(4.dp)
            .heightIn(min = Ember.dock),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        IconLatch(
            on = state.voiceMode == "dictate",
            description = "dictate",
            onClick = onDictate,
        ) {
            MicMark(live = state.voiceMode == "dictate" && state.listening)
        }
        IconLatch(
            on = state.voiceMode == "conversation",
            description = "talk",
            onClick = onTalk,
        ) {
            TalkMark(live = state.voiceMode == "conversation" && state.listening)
        }
        IconLatch(
            on = false,
            description = "attach",
            onClick = onAttach,
        ) {
            PhotoMark()
        }
        BasicTextField(
            value = state.draft,
            onValueChange = onDraft,
            textStyle = TextStyle(color = Campfire.text, fontSize = 16.sp, lineHeight = 22.sp),
            cursorBrush = SolidColor(Campfire.accent),
            modifier = Modifier
                .weight(1f)
                .padding(horizontal = 10.dp, vertical = 10.dp),
            decorationBox = { inner ->
                Box {
                    if (state.draft.isEmpty()) {
                        Text(
                            when (state.voiceMode) {
                                "dictate" -> "speak — it lands here"
                                "conversation" -> "listening…"
                                else -> "talk to her"
                            },
                            color = Campfire.coal,
                            fontSize = 16.sp,
                        )
                    }
                    inner()
                }
            },
        )
        IconLatch(
            on = false,
            description = "send",
            onClick = onSend,
            enabled = !state.busy,
            filled = true,
        ) {
            SendMark(busy = state.busy)
        }
    }
}

@Composable
private fun GemmaBanner(
    gemma: GemmaUi,
    onInstall: () -> Unit,
    onWaitWifi: () -> Unit,
    onLater: () -> Unit,
    onUseData: () -> Unit,
    onShow: () -> Unit,
) {
    if (gemma.ready) return
    if (gemma.later && !gemma.downloading && !gemma.waitWifi && !gemma.confirmCellular) {
        Spacer(Modifier.height(Ember.gap))
        Text(
            "offline brain",
            color = Campfire.dim,
            fontSize = 12.sp,
            letterSpacing = 0.8.sp,
            modifier = Modifier.clickable(onClick = onShow).padding(4.dp),
        )
        return
    }
    Spacer(Modifier.height(Ember.gap))
    GlassCard {
        when {
            gemma.downloading -> {
                Text("offline brain", color = Campfire.accent, fontSize = 11.sp, letterSpacing = 1.2.sp, fontWeight = FontWeight.Medium)
                Spacer(Modifier.height(6.dp))
                Text(
                    gemma.progress.ifBlank { "downloading…" },
                    color = Campfire.accent2,
                    fontSize = 14.sp,
                )
            }
            gemma.confirmCellular -> {
                Text("This uses about 2.6 GB of mobile data.", color = Campfire.text, fontSize = 14.sp)
                Spacer(Modifier.height(10.dp))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    EmberButton("download now", onUseData, modifier = Modifier.weight(1f))
                    LatchChip("wait for wifi", on = false, onClick = onWaitWifi)
                }
            }
            gemma.waitWifi -> {
                Text("Waiting for Wi-Fi to install the offline brain (~2.6 GB).", color = Campfire.text, fontSize = 14.sp)
                Spacer(Modifier.height(10.dp))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    EmberButton("use mobile data", onUseData)
                    LatchChip("later", on = false, onClick = onLater)
                }
            }
            gemma.onWifi -> {
                Text("Offline brain is not on this phone (~2.6 GB). Install it so she still talks if the PC is down.", color = Campfire.text, fontSize = 14.sp, lineHeight = 20.sp)
                Spacer(Modifier.height(10.dp))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    EmberButton("install", onInstall)
                    LatchChip("later", on = false, onClick = onLater)
                }
            }
            else -> {
                Text("Install the offline brain (~2.6 GB). Wi-Fi is nicer.", color = Campfire.text, fontSize = 14.sp)
                Spacer(Modifier.height(10.dp))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    EmberButton("install now", onInstall)
                    LatchChip("wait for wifi", on = false, onClick = onWaitWifi)
                    LatchChip("later", on = false, onClick = onLater)
                }
            }
        }
    }
}

@Composable
private fun BubbleView(bubble: ChatBubble, onGlance: (GlanceCard) -> Unit) {
    val mine = bubble.role == "user"
    Column(
        modifier = Modifier.fillMaxWidth(),
        horizontalAlignment = if (mine) Alignment.End else Alignment.Start,
    ) {
        if (!mine) {
            Text(
                "arelis",
                color = Campfire.coal,
                fontSize = 10.sp,
                letterSpacing = 1.6.sp,
                fontWeight = FontWeight.Normal,
                modifier = Modifier.padding(start = 12.dp, bottom = 6.dp),
            )
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (!mine) {
                Box(
                    Modifier
                        .padding(end = 10.dp)
                        .size(width = 3.dp, height = 22.dp)
                        .clip(CircleShape)
                        .background(if (bubble.streaming) Campfire.accent2 else Campfire.accent),
                )
            }
            val bubbleMod = Modifier
                .widthIn(max = 320.dp)
                .clip(EmberShape)
                .background(if (mine) Campfire.bg2 else Campfire.bg1)
                .border(
                    1.dp,
                    if (mine) Campfire.accent.copy(alpha = 0.35f) else Campfire.rim,
                    EmberShape,
                )
                .padding(horizontal = 16.dp, vertical = 12.dp)
            val bubbleText = bubble.text.ifBlank { if (bubble.streaming) "…" else "" }
            if (bubble.streaming || bubbleText.isEmpty()) {
                Text(
                    text = bubbleText,
                    color = Campfire.text,
                    fontSize = 16.sp,
                    lineHeight = 22.sp,
                    overflow = TextOverflow.Clip,
                    modifier = bubbleMod,
                )
            } else {
                SelectionContainer {
                    Text(
                        text = bubbleText,
                        color = Campfire.text,
                        fontSize = 16.sp,
                        lineHeight = 22.sp,
                        overflow = TextOverflow.Clip,
                        modifier = bubbleMod,
                    )
                }
            }
        }
        bubble.glances.forEach { glance ->
            Text(
                glance.title,
                color = Campfire.accent2,
                fontSize = 13.sp,
                modifier = Modifier
                    .padding(top = 6.dp)
                    .clip(EmberShapeTight)
                    .background(Campfire.raised)
                    .border(1.dp, Campfire.rim, EmberShapeTight)
                    .clickable { onGlance(glance) }
                    .padding(horizontal = 12.dp, vertical = 8.dp),
            )
        }
    }
}
