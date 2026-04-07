package info.jarvisai.app.ui.avatar

import androidx.compose.animation.core.*
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.*
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import info.jarvisai.app.R
import info.jarvisai.app.data.model.AvatarMouthState

// Augen-Positionen relativ zur Bildbreite – aus IronManComposable.kt (APK 2026-04-03)
private const val EYE_Y   = 0.4921875f
private const val EYE_W   = 0.12890625f
private const val EYE_H_R = 0.33333334f
private const val LEFT_X  = 0.29101562f
private const val RIGHT_X = 0.56640625f

private val EyeHaloColor   = Color(0xFFFFCC44)  // Gold-Halo
private val EyeFillColor   = Color(0xFFFFEE88)  // Helles Gelb (Iron Man Augen)
private val OuterGlowColor = Color(0xFFFFAA00)  // Orange-Amber (Sprechen-Glow)

@Composable
fun JarvisAvatar(
    isSpeaking: Boolean,
    mouthState: AvatarMouthState,
    modifier: Modifier = Modifier,
) {
    val infiniteTransition = rememberInfiniteTransition(label = "avatar_anim")

    val eyePulse by infiniteTransition.animateFloat(
        initialValue = 0.3f, targetValue = 0.95f,
        animationSpec = infiniteRepeatable(
            tween(800, easing = FastOutSlowInEasing), RepeatMode.Reverse,
        ),
        label = "eyePulse",
    )
    val bob by infiniteTransition.animateFloat(
        initialValue = 0f, targetValue = 7f,
        animationSpec = infiniteRepeatable(
            tween(580, easing = FastOutSlowInEasing), RepeatMode.Reverse,
        ),
        label = "bob",
    )

    val speakingFactor by animateFloatAsState(
        targetValue = if (isSpeaking) 1f else 0f,
        animationSpec = tween(350), label = "speakingFactor",
    )
    val avatarScale by animateFloatAsState(
        targetValue = if (isSpeaking) 1.04f else 1.0f,
        animationSpec = spring(
            dampingRatio = Spring.DampingRatioMediumBouncy,
            stiffness = Spring.StiffnessLow,
        ),
        label = "scale",
    )

    Box(
        contentAlignment = Alignment.Center,
        modifier = modifier
            .graphicsLayer {
                translationY = -bob * speakingFactor * 0.65f
                scaleX = avatarScale
                scaleY = avatarScale
            }
            .drawWithContent {
                drawContent()

                val W = size.width
                // Letterbox-Offset: Bild wird quadratisch mit ContentScale.Fit in höherer Box zentriert
                val letterboxOffset = (size.height - W) / 2f
                val f2 = EYE_W * W          // Augenbreite
                val f3 = EYE_H_R * f2       // Augenhöhe
                val f4 = EYE_Y * W + letterboxOffset  // Augen-Top-Y

                // Augen-Glow (links + rechts)
                for (cx in listOf(LEFT_X * W, RIGHT_X * W)) {
                    // Halo: breites Radial-Gradient-Oval
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
                    // Kern: solides Augen-Oval
                    drawOval(
                        color = EyeFillColor.copy(alpha = eyePulse * 0.95f),
                        topLeft = Offset(cx, f4),
                        size = Size(f2, f3),
                    )
                }

                // Äußerer Sprechen-Glow
                if (speakingFactor > 0.01f) {
                    drawCircle(
                        brush = Brush.radialGradient(
                            colors = listOf(
                                OuterGlowColor.copy(alpha = speakingFactor * 0.45f),
                                Color.Transparent,
                            ),
                            center = Offset(W / 2f, letterboxOffset + 0.5f * W),
                            radius = W * 0.55f,
                        ),
                    )
                }
            },
    ) {
        Image(
            painter = painterResource(id = R.drawable.bg_jarvis),
            contentDescription = "Jarvis Iron Man Avatar",
            contentScale = ContentScale.Fit,
            modifier = Modifier.fillMaxSize(),
        )
    }
}
