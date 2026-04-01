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

// ─── Augenpositionen – pixel-kalibriert am 512×512 Quellbild ─────────────────
//
// Das Bild ist 512×512 (quadratisch). Der Composable ist 170×200dp (hochformatig).
// ContentScale.Fit skaliert das Bild auf die Breite (170dp) → Bildhöhe = 170dp,
// vertikal zentriert → Offset oben = (200-170)/2 = 15dp.
//
// Formel: eyeY = (h - w) / 2  +  w * EYE_Y_REL
//         eyeX =                  w * EYE_X_REL
//
// Gemessene Schlitzpositionen im Quellbild (weiß/teal-leuchtende Pixel):
//   Linkes Auge:  cols 149–215, rows 252–274
//   Rechtes Auge: cols 310–376, rows 252–274
private const val EYE_Y   = 252f / 512f   // = 0.4922
private const val EYE_W   = 66f  / 512f   // = 0.1289  (Breite je Auge)
private const val EYE_H_R = 22f  / 66f    // = 0.333   (Schlitz-Verhältnis)
private const val LEFT_X  = 149f / 512f   // = 0.2910
private const val RIGHT_X = 290f / 512f   // = 0.5664

@Composable
fun IronManAvatar(
    isSpeaking: Boolean,
    mouthState: AvatarMouthState,
    modifier: Modifier = Modifier,
) {
    val infiniteTransition = rememberInfiniteTransition(label = "ironman_anim")

    val bob by infiniteTransition.animateFloat(
        initialValue = 0f, targetValue = 5f,
        animationSpec = infiniteRepeatable(tween(1800, easing = FastOutSlowInEasing), RepeatMode.Reverse),
        label = "bob",
    )
    val eyePulse by infiniteTransition.animateFloat(
        initialValue = 0.55f, targetValue = 1.0f,
        animationSpec = infiniteRepeatable(tween(900, easing = FastOutSlowInEasing), RepeatMode.Reverse),
        label = "eye",
    )
    val outerGlow by infiniteTransition.animateFloat(
        initialValue = 0.0f, targetValue = if (isSpeaking) 0.40f else 0.0f,
        animationSpec = infiniteRepeatable(tween(500, easing = FastOutSlowInEasing), RepeatMode.Reverse),
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

                    // Bild ist quadratisch → ContentScale.Fit füllt die Breite.
                    // Vertikaler Offset: (h - w) / 2 (Leerraum oben/unten).
                    val imgW      = w
                    val imgOffY   = (h - imgW) / 2f

                    val eyeW  = imgW * EYE_W
                    val eyeH  = eyeW * EYE_H_R
                    val eyeY  = imgOffY + imgW * EYE_Y
                    val leftX = imgW * LEFT_X
                    val rightX= imgW * RIGHT_X

                    listOf(leftX, rightX).forEach { ex ->
                        val cx = ex + eyeW / 2f
                        val cy = eyeY + eyeH / 2f

                        // Weicher goldener Außen-Glow
                        drawOval(
                            brush = Brush.radialGradient(
                                colors = listOf(
                                    Color(0xFFFFCC44).copy(alpha = eyePulse * 0.55f),
                                    Color.Transparent,
                                ),
                                center = Offset(cx, cy),
                                radius = eyeW * 1.0f,
                            ),
                            topLeft = Offset(ex - eyeW * 0.35f, eyeY - eyeH * 1.5f),
                            size    = Size(eyeW * 1.7f, eyeH * 4.0f),
                        )
                        // Harter goldener Kern
                        drawOval(
                            color   = Color(0xFFFFEE88).copy(alpha = eyePulse * 0.95f),
                            topLeft = Offset(ex, eyeY),
                            size    = Size(eyeW, eyeH),
                        )
                    }

                    // Sprechender Glow
                    if (outerGlow > 0.01f) {
                        drawCircle(
                            brush = Brush.radialGradient(
                                colors = listOf(
                                    Color(0xFFFFAA00).copy(alpha = outerGlow * 0.45f),
                                    Color.Transparent,
                                ),
                                center = Offset(w / 2f, imgOffY + imgW * 0.50f),
                                radius = w * 0.55f,
                            ),
                        )
                    }
                },
        )
    }
}
