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
        initialValue = 0.6f, targetValue = 1.0f,
        animationSpec = infiniteRepeatable(
            tween(700, easing = FastOutSlowInEasing), RepeatMode.Reverse,
        ),
        label = "eye",
    )

    // Äußerer Glow-Ring wenn sprechend
    val outerGlow by infiniteTransition.animateFloat(
        initialValue = 0.0f, targetValue = if (isSpeaking) 0.45f else 0.0f,
        animationSpec = infiniteRepeatable(
            tween(400, easing = FastOutSlowInEasing), RepeatMode.Reverse,
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

                    // Augenpositionen relativ zum 512×512 Quellbild
                    // Linkes Auge: ~37% x, 42% y; Rechtes Auge: ~63% x, 42% y
                    val eyeY    = h * 0.425f
                    val eyeW    = w * 0.130f
                    val eyeH    = eyeW * 0.28f
                    val leftX   = w * 0.305f
                    val rightX  = w * 0.575f

                    listOf(leftX, rightX).forEach { ex ->
                        // Weicher Außen-Glow
                        drawOval(
                            brush = Brush.radialGradient(
                                colors = listOf(
                                    Color(0xFF00EEFF).copy(alpha = eyePulse * 0.55f),
                                    Color.Transparent,
                                ),
                                center = Offset(ex + eyeW / 2f, eyeY + eyeH / 2f),
                                radius = eyeW * 0.85f,
                            ),
                            topLeft = Offset(ex - eyeW * 0.35f, eyeY - eyeH * 1.2f),
                            size = Size(eyeW * 1.7f, eyeH * 3.4f),
                        )
                        // Harter Kern-Leuchtstrich
                        drawOval(
                            color = Color(0xFF80FFFF).copy(alpha = eyePulse * 0.90f),
                            topLeft = Offset(ex, eyeY),
                            size = Size(eyeW, eyeH),
                        )
                    }

                    // Sprechender Glow – leuchtet wenn TTS aktiv
                    if (outerGlow > 0.01f) {
                        drawCircle(
                            brush = Brush.radialGradient(
                                colors = listOf(
                                    Color(0xFF00CFFF).copy(alpha = outerGlow * 0.5f),
                                    Color.Transparent,
                                ),
                                center = Offset(w / 2f, h / 2f),
                                radius = w * 0.6f,
                            ),
                        )
                    }
                },
        )
    }
}
