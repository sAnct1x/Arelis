package app.arelis

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin
import kotlin.random.Random

/** Same sodium bloom as arelis/ui/stage.py — lamp in the middle, not a top wash. */
private const val BLOOM_X = 0.50f
private const val BLOOM_Y = 0.44f

private val GRAIN: List<Triple<Float, Float, Int>> = run {
    val rng = Random(7)
    List(140) { Triple(rng.nextFloat(), rng.nextFloat(), 5 + rng.nextInt(7)) }
}

fun DrawScope.paintVoid() {
    val lamp = Campfire.accent
    val room = Campfire.bg0
    val cx = size.width * BLOOM_X
    val cy = size.height * BLOOM_Y
    val center = Offset(cx, cy)
    val span = size.maxDimension
    drawRect(
        Brush.radialGradient(
            colorStops = arrayOf(
                0.00f to lamp.copy(alpha = 92f / 255f),
                0.16f to lamp.copy(alpha = 62f / 255f),
                0.42f to lamp.copy(alpha = 32f / 255f),
                0.72f to lamp.copy(alpha = 12f / 255f),
                1.00f to Color.Transparent,
            ),
            center = center,
            radius = span * 0.58f,
        ),
    )
    drawRect(
        Brush.radialGradient(
            colorStops = arrayOf(
                0.00f to lamp.copy(alpha = 40f / 255f),
                0.38f to lamp.copy(alpha = 18f / 255f),
                1.00f to Color.Transparent,
            ),
            center = center,
            radius = span * 0.88f,
        ),
    )
    for ((x, y, a) in GRAIN) {
        drawRect(
            lamp.copy(alpha = a / 255f),
            topLeft = Offset(x * size.width, y * size.height),
            size = androidx.compose.ui.geometry.Size(1f, 1f),
        )
    }
    drawRect(
        Brush.radialGradient(
            colorStops = arrayOf(
                0.00f to Color.Transparent,
                0.70f to Color.Transparent,
                1.00f to room.copy(alpha = 48f / 255f),
            ),
            center = center,
            radius = span * 0.92f,
        ),
    )
}

@Composable
fun OrbitFace(
    modifier: Modifier = Modifier,
    dim: Float = 1f,
    thinking: Boolean = false,
) {
    val live = rememberInfiniteTransition(label = "orbit")
    val angle by live.animateFloat(
        initialValue = 0f,
        targetValue = 360f,
        animationSpec = infiniteRepeatable(
            animation = tween(if (thinking) 16_000 else 14_000, easing = LinearEasing),
            repeatMode = RepeatMode.Restart,
        ),
        label = "orbit-tick",
    )
    val beat by live.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(if (thinking) 4800 else 3200, easing = LinearEasing),
            repeatMode = RepeatMode.Restart,
        ),
        label = "orbit-beat",
    )
    val d = dim.coerceIn(0.2f, 1f)
    val ring = Campfire.accent
    val hot = Campfire.accent2
    Canvas(modifier) {
        val cx = size.width * 0.5f
        val cy = size.height * 0.5f
        val box = size.minDimension
        val s = box / 220f
        val r = 68f * s
        val core = Offset(cx, cy)
        drawCircle(
            brush = Brush.radialGradient(
                colors = listOf(
                    hot.copy(alpha = (40 * d) / 255f),
                    ring.copy(alpha = (22 * d) / 255f),
                    Color.Transparent,
                ),
                center = core,
                radius = r + 52f * s,
            ),
            radius = r + 52f * s,
            center = core,
        )
        drawCircle(
            color = ring.copy(alpha = 0.19f * d),
            radius = r,
            center = core,
            style = Stroke(width = (3.2f * s).coerceAtLeast(1f)),
        )
        drawCircle(
            color = ring.copy(alpha = 0.43f * d),
            radius = r,
            center = core,
            style = Stroke(width = (1.4f * s).coerceAtLeast(1f)),
        )
        val rad = angle * (PI.toFloat() / 180f)
        val tick = Offset(cx + r * sin(rad), cy - r * cos(rad))
        val tickR = 16f * s
        drawCircle(
            brush = Brush.radialGradient(
                colors = listOf(
                    ring.copy(alpha = (190 * d) / 255f),
                    ring.copy(alpha = (70 * d) / 255f),
                    Color.Transparent,
                ),
                center = tick,
                radius = tickR,
            ),
            radius = tickR,
            center = tick,
        )
        drawCircle(hot.copy(alpha = d), radius = 2.4f * s, center = tick)
        val t = 0.5f - 0.5f * cos(beat * 2f * PI.toFloat())
        val glowR = (22f + 10f * t) * s
        drawCircle(
            brush = Brush.radialGradient(
                colors = listOf(
                    hot.copy(alpha = ((160 + 50 * t) * d) / 255f),
                    ring.copy(alpha = ((70 + 30 * t) * d) / 255f),
                    Color.Transparent,
                ),
                center = core,
                radius = glowR,
            ),
            radius = glowR,
            center = core,
        )
        drawCircle(
            hot.copy(alpha = d),
            radius = (2.4f + 1.2f * t) * s,
            center = core,
        )
    }
}

@Composable
fun IdleFace(
    title: String,
    body: String,
    thinking: Boolean = false,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier.fillMaxWidth(),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        OrbitFace(
            Modifier.size(196.dp),
            dim = if (thinking) 0.92f else 1f,
            thinking = thinking,
        )
        Spacer(Modifier.height(8.dp))
        Text(
            title,
            color = Campfire.text,
            fontSize = 20.sp,
            fontWeight = FontWeight.Medium,
            textAlign = TextAlign.Center,
        )
        if (body.isNotBlank()) {
            Spacer(Modifier.height(6.dp))
            Text(
                body,
                color = Campfire.dim,
                fontSize = 13.sp,
                textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth(),
            )
        }
    }
}
