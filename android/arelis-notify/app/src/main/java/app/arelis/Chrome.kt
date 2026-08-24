package app.arelis

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.material3.Text

val EmberShape = RoundedCornerShape(16.dp)
val EmberShapeTight = RoundedCornerShape(12.dp)
val EmberDock = RoundedCornerShape(28.dp)

/** One rhythm for talk, files, chats, settings. */
object Ember {
    val screenX = 20.dp
    val screenY = 16.dp
    val gap = 12.dp
    val tap = 48.dp
    val mark = 26.dp
    val orb = 40.dp
    val dock = 56.dp
}

@Composable
fun EmberScreen(
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit,
) {
    Box(
        modifier
            .fillMaxSize()
            .background(Campfire.bg0)
            .drawBehind { paintVoid() }
            .statusBarsPadding()
            .navigationBarsPadding(),
    ) {
        Column(
            Modifier
                .fillMaxSize()
                .padding(horizontal = Ember.screenX, vertical = Ember.screenY),
            content = content,
        )
    }
}

@Composable
fun BrandMark(
    subtitle: String,
    mode: HouseMode? = null,
    confirm: Boolean = false,
    warmup: Boolean = false,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        FilamentOrb(mode = mode, confirm = confirm, warmup = warmup)
        Spacer(Modifier.width(Ember.gap))
        Column(Modifier.weight(1f)) {
            Text(
                "arelis",
                color = Campfire.accent,
                fontSize = 22.sp,
                fontWeight = FontWeight.Normal,
                letterSpacing = 2.0.sp,
                maxLines = 1,
                overflow = TextOverflow.Clip,
            )
            Text(
                subtitle,
                color = Campfire.hint,
                fontSize = 13.sp,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
fun FilamentOrb(
    mode: HouseMode? = null,
    confirm: Boolean = false,
    warmup: Boolean = false,
) {
    val live = mode == HouseMode.AtTheHouse || mode == HouseMode.Connecting || warmup
    val pulse by rememberInfiniteTransition(label = "filament").animateFloat(
        initialValue = if (live) 0.45f else 0.85f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(if (live) 1100 else 2400, easing = LinearEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "filament-pulse",
    )
    val core = when {
        confirm -> Campfire.danger
        mode == HouseMode.OnThePhone -> Campfire.coal
        mode == HouseMode.Connecting -> Campfire.accent2
        mode == HouseMode.AtTheHouse -> Campfire.accent
        else -> Campfire.accent2
    }
    Box(
        Modifier
            .size(Ember.orb)
            .drawBehind {
                drawCircle(
                    color = core.copy(alpha = 0.18f * pulse),
                    radius = size.minDimension * 0.72f,
                )
            }
            .clip(CircleShape)
            .background(Campfire.bg2)
            .border(1.dp, core.copy(alpha = 0.55f * pulse), CircleShape),
        contentAlignment = Alignment.Center,
    ) {
        Box(
            Modifier
                .size(12.dp)
                .clip(CircleShape)
                .background(core.copy(alpha = pulse)),
        )
    }
}

@Composable
fun GlassCard(
    modifier: Modifier = Modifier,
    hot: Boolean = false,
    onClick: (() -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    val rim = if (hot) Campfire.accent.copy(alpha = 0.55f) else Campfire.rim
    Column(
        modifier
            .clip(EmberShape)
            .background(Campfire.bg1.copy(alpha = 0.92f))
            .border(1.dp, rim, EmberShape)
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(16.dp),
        content = content,
    )
}

@Composable
fun EmberButton(
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    accent: Boolean = true,
    enabled: Boolean = true,
    danger: Boolean = false,
) {
    val fill = when {
        !enabled -> Campfire.coal
        danger -> Campfire.bg2
        accent -> Campfire.accent
        else -> Campfire.bg2
    }
    val ink = when {
        danger -> Campfire.danger
        accent && enabled -> Campfire.bg0
        else -> Campfire.hint
    }
    Box(
        modifier
            .heightIn(min = 48.dp)
            .clip(EmberShape)
            .background(fill)
            .clickable(enabled = enabled, onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 12.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            label,
            color = ink,
            fontWeight = FontWeight.SemiBold,
            fontSize = 15.sp,
            textAlign = TextAlign.Center,
        )
    }
}

@Composable
fun GhostLink(label: String, onClick: () -> Unit, modifier: Modifier = Modifier) {
    Text(
        label,
        color = Campfire.accent,
        fontSize = 15.sp,
        fontWeight = FontWeight.Medium,
        modifier = modifier
            .clip(EmberShapeTight)
            .clickable(onClick = onClick)
            .padding(horizontal = 4.dp, vertical = 10.dp),
    )
}

@Composable
fun NavLink(label: String, onClick: () -> Unit, enabled: Boolean = true) {
    Box(
        Modifier
            .heightIn(min = Ember.tap)
            .clip(EmberShapeTight)
            .clickable(enabled = enabled, onClick = onClick)
            .padding(horizontal = 8.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            label,
            color = if (enabled) Campfire.dim else Campfire.coal,
            fontSize = 15.sp,
            fontWeight = FontWeight.Medium,
            maxLines = 1,
            softWrap = false,
            overflow = TextOverflow.Clip,
        )
    }
}

@Composable
fun LatchChip(label: String, on: Boolean, onClick: () -> Unit) {
    Text(
        label,
        color = if (on) Campfire.bg0 else Campfire.hint,
        fontSize = 14.sp,
        fontWeight = FontWeight.Medium,
        modifier = Modifier
            .heightIn(min = 40.dp)
            .clip(EmberShapeTight)
            .background(if (on) Campfire.accent else Campfire.bg2)
            .border(1.dp, if (on) Campfire.accent else Campfire.rim, EmberShapeTight)
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 10.dp),
    )
}

@Composable
fun StatusPill(text: String, hot: Boolean = false) {
    Text(
        text,
        color = if (hot) Campfire.bg0 else Campfire.hint,
        fontSize = 11.sp,
        fontWeight = FontWeight.Medium,
        letterSpacing = 0.6.sp,
        modifier = Modifier
            .clip(CircleShape)
            .background(if (hot) Campfire.accent else Campfire.bg2)
            .padding(horizontal = 10.dp, vertical = 4.dp),
    )
}

@Composable
fun ScreenTop(
    title: String,
    onBack: () -> Unit,
    backLabel: String = "← back",
    trailing: @Composable RowScope.() -> Unit = {},
) {
    Row(
        Modifier
            .fillMaxWidth()
            .heightIn(min = Ember.tap),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        GhostLink(backLabel, onBack)
        Text(title, color = Campfire.text, fontWeight = FontWeight.SemiBold, fontSize = 17.sp)
        Row(verticalAlignment = Alignment.CenterVertically, content = trailing)
    }
}

@Composable
fun EmptyHint(title: String, body: String) {
    Column(
        Modifier
            .fillMaxWidth()
            .padding(vertical = 24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        FilamentOrb(mode = HouseMode.Connecting)
        Spacer(Modifier.height(16.dp))
        Text(title, color = Campfire.text, fontSize = 18.sp, fontWeight = FontWeight.Medium)
        Spacer(Modifier.height(6.dp))
        Text(
            body,
            color = Campfire.dim,
            fontSize = 14.sp,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(horizontal = 12.dp),
        )
    }
}

@Composable
fun AttachSheet(
    onTake: () -> Unit,
    onLibrary: () -> Unit,
    onFile: () -> Unit,
    onDismiss: () -> Unit,
) {
    Column(
        Modifier
            .fillMaxWidth()
            .clip(EmberShape)
            .background(Campfire.bg1)
            .border(1.dp, Campfire.rim, EmberShape)
            .padding(18.dp),
    ) {
        Text(
            "attach",
            color = Campfire.accent,
            fontSize = 11.sp,
            letterSpacing = 1.6.sp,
            fontWeight = FontWeight.SemiBold,
        )
        Spacer(Modifier.height(8.dp))
        AttachChoice("take a photo", onTake)
        AttachChoice("photo from library", onLibrary)
        AttachChoice("a file", onFile)
        Spacer(Modifier.height(6.dp))
        GhostLink("cancel", onDismiss)
    }
}

@Composable
private fun AttachChoice(label: String, onClick: () -> Unit) {
    Text(
        label,
        color = Campfire.text,
        fontSize = 17.sp,
        modifier = Modifier
            .fillMaxWidth()
            .clip(EmberShapeTight)
            .clickable(onClick = onClick)
            .padding(vertical = 12.dp, horizontal = 4.dp),
    )
}

@Composable
fun StepRow(
    done: Boolean,
    title: String,
    body: String,
    onClick: () -> Unit,
) {
    GlassCard(
        modifier = Modifier.fillMaxWidth().padding(bottom = 10.dp),
        hot = done,
        onClick = onClick,
    ) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(title, color = Campfire.text, fontWeight = FontWeight.Medium, fontSize = 15.sp)
            StatusPill(if (done) "done" else "open", hot = done)
        }
        Text(body, color = Campfire.dim, fontSize = 13.sp)
    }
}
