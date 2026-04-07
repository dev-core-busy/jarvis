package info.jarvisai.app.ui.avatar

import androidx.compose.animation.core.*
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.*
import androidx.compose.ui.graphics.drawscope.ContentDrawScope
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.foundation.layout.offset
import androidx.compose.ui.unit.dp
import info.jarvisai.app.R
import info.jarvisai.app.data.model.AvatarMouthState

// Augen-Positionen aus IronManComposable.kt (rekonstruiert aus APK 2026-04-03)
private const val EYE_Y   = 0.4921875f
private const val EYE_W   = 0.12890625f
private const val EYE_H_R = 0.33333334f
private const val LEFT_X  = 0.29101562f
private const val RIGHT_X = 0.56640625f

private val EyeHaloColor   = Color(0xFFFFCC44)  // Gold-Halo
private val EyeFillColor   = Color(0xFFFFEE88)  // Helles Gelb
private val AmbientGlow    = Color(0xFFFFAA00)  // Orange-Amber (Ambient-Glow im Ruhezustand)

@Composable
fun JarvisAvatar(
    isSpeaking: Boolean,
    mouthState: AvatarMouthState,
    modifier: Modifier = Modifier,
) {
    val infiniteTransition = rememberInfiniteTransition(label = "ironman_anim")

    // Langsames Bob (1800ms, 0–5dp) – Original-Werte
    val bob by infiniteTransition.animateFloat(
        initialValue = 0f, targetValue = 5f,
        animationSpec = infiniteRepeatable(
            tween(1800, easing = FastOutSlowInEasing), RepeatMode.Reverse,
        ),
        label = "bob",
    )
    // Augen-Puls (900ms, 0.55–1.0) – Original-Werte
    val eyePulse by infiniteTransition.animateFloat(
        initialValue = 0.55f, targetValue = 1.0f,
        animationSpec = infiniteRepeatable(
            tween(900, easing = FastOutSlowInEasing), RepeatMode.Reverse,
        ),
        label = "eye",
    )
    // Ambient-Glow nur im Ruhezustand (0–0.4 wenn NICHT sprechend) – Original-Werte
    val ambientGlow by infiniteTransition.animateFloat(
        initialValue = 0f, targetValue = if (!isSpeaking) 0.4f else 0f,
        animationSpec = infiniteRepeatable(
            tween(500, easing = FastOutSlowInEasing), RepeatMode.Reverse,
        ),
        label = "glow",
    )

    Box(
        modifier = modifier
            .offset(y = bob.dp)
            .drawWithContent {
                drawContent()
                drawIronManOverlay(eyePulse, ambientGlow)
            },
    ) {
        Image(
            painter = painterResource(id = R.drawable.ironman_avatar),
            contentDescription = "Iron Man",
            contentScale = ContentScale.Fit,
            modifier = Modifier.fillMaxSize(),
        )
    }
}

private fun ContentDrawScope.drawIronManOverlay(eyePulse: Float, ambientGlow: Float) {
    val W = size.width
    val letterboxOffset = (size.height - W) / 2f
    val f2 = EYE_W * W
    val f3 = EYE_H_R * f2
    val f4 = EYE_Y * W + letterboxOffset  // Augen-Top-Y

    // Augen (links + rechts)
    for (cx in listOf(LEFT_X * W, RIGHT_X * W)) {
        // Halo-Oval (Radial-Gradient)
        drawOval(
            brush = Brush.radialGradient(
                colors = listOf(
                    EyeHaloColor.copy(alpha = eyePulse * 0.55f),
                    Color.Transparent,
                ),
                center = Offset(cx + f2 / 2f, f4 + f3 / 2f),
                radius = f2,
            ),
            topLeft = Offset(cx - 0.35f * f2, f4 - 1.5f * f3),
            size = Size(1.7f * f2, 4.0f * f3),
        )
        // Kern-Oval (solides Gelb)
        drawOval(
            color = EyeFillColor.copy(alpha = eyePulse * 0.95f),
            topLeft = Offset(cx, f4),
            size = Size(f2, f3),
        )
    }

    // Ambient-Glow (nur Ruhezustand)
    if (ambientGlow > 0.01f) {
        drawCircle(
            brush = Brush.radialGradient(
                colors = listOf(
                    AmbientGlow.copy(alpha = ambientGlow * 0.45f),
                    Color.Transparent,
                ),
                center = Offset(W / 2f, letterboxOffset + 0.5f * W),
                radius = W * 0.55f,
            ),
        )
    }
}
