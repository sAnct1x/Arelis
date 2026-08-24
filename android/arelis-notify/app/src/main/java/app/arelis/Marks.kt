package app.arelis

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** Desktop icons.py, drawn in the same sodium line language. */

@Composable
fun IconLatch(
    on: Boolean,
    description: String,
    onClick: () -> Unit,
    enabled: Boolean = true,
    filled: Boolean = false,
    mark: @Composable () -> Unit,
) {
    Box(
        Modifier
            .size(Ember.tap)
            .clip(CircleShape)
            .background(
                when {
                    on -> Campfire.accent.copy(alpha = 0.22f)
                    filled -> Campfire.bg2
                    else -> Color.Transparent
                },
            )
            .then(
                if (filled) {
                    Modifier.border(1.dp, Campfire.rim, CircleShape)
                } else {
                    Modifier
                },
            )
            .clickable(enabled = enabled, onClick = onClick)
            .semantics { contentDescription = description },
        contentAlignment = Alignment.Center,
    ) {
        mark()
    }
}

private fun hair(s: Float) = Stroke(width = (s * 0.078f).coerceIn(2.4f, 3.4f), cap = StrokeCap.Round)

@Composable
fun MicMark(live: Boolean, modifier: Modifier = Modifier) {
    val tint = if (live) Campfire.accent else Campfire.accent.copy(alpha = 0.88f)
    Canvas(modifier.size(Ember.mark)) {
        val s = size.minDimension
        drawCircle(tint.copy(alpha = if (live) 0.16f else 0.08f), radius = s * 0.48f)
        drawRoundRect(
            tint,
            topLeft = Offset(s * 0.38f, s * 0.18f),
            size = Size(s * 0.24f, s * 0.42f),
            cornerRadius = CornerRadius(s * 0.12f, s * 0.12f),
        )
        drawArc(
            tint,
            startAngle = 0f,
            sweepAngle = 180f,
            useCenter = false,
            topLeft = Offset(s * 0.28f, s * 0.32f),
            size = Size(s * 0.44f, s * 0.40f),
            style = hair(s),
        )
        drawLine(
            tint,
            Offset(s * 0.50f, s * 0.72f),
            Offset(s * 0.50f, s * 0.84f),
            strokeWidth = hair(s).width,
            cap = StrokeCap.Round,
        )
    }
}

@Composable
fun TalkMark(live: Boolean, modifier: Modifier = Modifier) {
    val tint = if (live) Campfire.accent else Campfire.accent.copy(alpha = 0.88f)
    Canvas(modifier.size(Ember.mark)) {
        val s = size.minDimension
        drawCircle(tint.copy(alpha = if (live) 0.16f else 0.08f), radius = s * 0.48f)
        drawArc(
            tint,
            startAngle = -110f,
            sweepAngle = -220f,
            useCenter = false,
            topLeft = Offset(s * 0.14f, s * 0.20f),
            size = Size(s * 0.42f, s * 0.48f),
            style = hair(s),
        )
        drawArc(
            tint.copy(alpha = 0.78f),
            startAngle = 70f,
            sweepAngle = -220f,
            useCenter = false,
            topLeft = Offset(s * 0.44f, s * 0.30f),
            size = Size(s * 0.42f, s * 0.48f),
            style = hair(s),
        )
        drawCircle(Color(0xFFFAE8DC), radius = s * 0.055f, center = Offset(s * 0.50f, s * 0.50f))
    }
}

@Composable
fun PhotoMark(modifier: Modifier = Modifier) {
    val tint = Campfire.accent.copy(alpha = 0.88f)
    Canvas(modifier.size(Ember.mark)) {
        val s = size.minDimension
        drawCircle(tint.copy(alpha = 0.08f), radius = s * 0.48f)
        drawRoundRect(
            tint,
            topLeft = Offset(s * 0.20f, s * 0.32f),
            size = Size(s * 0.60f, s * 0.44f),
            cornerRadius = CornerRadius(s * 0.10f, s * 0.10f),
            style = hair(s),
        )
        drawRoundRect(
            tint,
            topLeft = Offset(s * 0.34f, s * 0.24f),
            size = Size(s * 0.22f, s * 0.12f),
            cornerRadius = CornerRadius(s * 0.06f, s * 0.06f),
            style = hair(s),
        )
        drawCircle(
            tint,
            radius = s * 0.11f,
            center = Offset(s * 0.50f, s * 0.54f),
            style = hair(s),
        )
    }
}

@Composable
fun SendMark(busy: Boolean, modifier: Modifier = Modifier) {
    if (busy) {
        Text("…", color = Campfire.accent, fontSize = 20.sp, fontWeight = FontWeight.Bold)
        return
    }
    Canvas(modifier.size(Ember.mark)) {
        val s = size.minDimension
        val tint = Campfire.accent
        drawCircle(tint.copy(alpha = 0.10f), radius = s * 0.48f)
        val stars = listOf(
            Offset(s * 0.26f, s * 0.64f) to s * 0.055f,
            Offset(s * 0.48f, s * 0.48f) to s * 0.070f,
            Offset(s * 0.70f, s * 0.30f) to s * 0.050f,
        )
        for ((pt, r) in stars) {
            drawCircle(tint, radius = r, center = pt)
        }
        drawLine(
            Campfire.accent2,
            Offset(s * 0.28f, s * 0.68f),
            Offset(s * 0.76f, s * 0.26f),
            strokeWidth = hair(s).width,
            cap = StrokeCap.Round,
        )
        drawCircle(Color(0xFFFAE8DC), radius = s * 0.055f, center = Offset(s * 0.78f, s * 0.24f))
    }
}
