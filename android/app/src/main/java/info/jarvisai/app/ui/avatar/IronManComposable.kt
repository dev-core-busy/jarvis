package info.jarvisai.app.ui.avatar

import androidx.compose.animation.core.*
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.offset
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.*
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import info.jarvisai.app.R
import info.jarvisai.app.data.model.AvatarMouthState

// ─── Augenpositionen (pixel-kalibriert auf 512×512 Quellbild) ────────────────
// Rechtes Auge: cols 307–373, rows 209–248
// Linkes Auge:  cols 145–211, rows 209–248
private const val EYE_W     = 0.130f   // Breite je Auge (66/512)
private const val EYE_H_R   = 0.60f    // Höhe als Anteil von EYE_W (40/66)
private const val RIGHT_X   = 0.600f   // Linke Kante rechtes Auge (307/512)
private const val LEFT_X    = 0.283f   // Linke Kante linkes Auge  (145/512)
private const val EYE_Y     = 0.408f   // Oberkante der Augenlinie (209/512)

@Composable
fun IronManAvatar(
    isSpeaking: Boolean,
    mouthState: AvatarMouthState,
    modifier: Modifier = Modifier,
) {
    val infiniteTransition = rememberInfiniteTransition(label = "ironman_anim")

    // Langsames Schweben
    val bob by infiniteTransition.animateFloat(
        initialValue = 0f, targetValue = 5f,
        animationSpec = infiniteRepeatable(
            tween(1800, easing = FastOutSlowInEasing), RepeatMode.Reverse,
        ),
        label = "bob",
    )

    // Augenglow pulsiert
    val eyePulse by infiniteTransition.animateFloat(
        initialValue = 0.55f, targetValue = 1.0f,
        animationSpec = infiniteRepeatable(
            tween(900, easing = FastOutSlowInEasing), RepeatMode.Reverse,
        ),
        label = "eye",
    )

    // Äußerer Glow-Ring wenn sprechend
    val outerGlow by infiniteTransition.animateFloat(
        initialValue = 0.0f, targetValue = if (isSpeaking) 0.40f else 0.0f,
        animationSpec = infiniteRepeatable(
            tween(500, easing = FastOutSlowInEasing), RepeatMode.Reverse,
        ),
        label = "glow",
    )

    Box(modifier = modifier.offset(y = bob.dp)) {
        Image(
            painter = painterResource(id = R.drawable.ironman_avatar),
            contentDescription = "Iron Man",
            contentScale = ContentScale.Fit,
            modifier = Modifier
                .fillMaxSize()
                .drawWithContent {
                    drawContent()

                    val w = size.width
                    val h = size.height

                    val eyeW = w * EYE_W
                    val eyeH = eyeW * EYE_H_R
                    val eyeY = h * EYE_Y

                    // Rechtes und linkes Auge
                    listOf(w * RIGHT_X, w * LEFT_X).forEach { ex ->
                        val eyeCx = ex + eyeW / 2f
                        val eyeCy = eyeY + eyeH / 2f

                        // Weicher goldener Außen-Glow
                        drawOval(
                            brush = Brush.radialGradient(
                                colors = listOf(
                                    Color(0xFFFFCC44).copy(alpha = eyePulse * 0.50f),
                                    Color.Transparent,
                                ),
                                center = Offset(eyeCx, eyeCy),
                                radius = eyeW * 0.95f,
                            ),
                            topLeft = Offset(ex - eyeW * 0.40f, eyeY - eyeH * 1.2f),
                            size = Size(eyeW * 1.80f, eyeH * 3.4f),
                        )
                        // Harter goldener Kern
                        drawOval(
                            color = Color(0xFFFFEE88).copy(alpha = eyePulse * 0.92f),
                            topLeft = Offset(ex, eyeY),
                            size = Size(eyeW, eyeH),
                        )
                    }

                    // Sprechender Glow-Ring
                    if (outerGlow > 0.01f) {
                        drawCircle(
                            brush = Brush.radialGradient(
                                colors = listOf(
                                    Color(0xFFFFAA00).copy(alpha = outerGlow * 0.45f),
                                    Color.Transparent,
                                ),
                                center = Offset(w / 2f, h * 0.42f),
                                radius = w * 0.55f,
                            ),
                        )
                    }
                },
        )
    }
}
