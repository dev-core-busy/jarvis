package info.jarvisai.app.ui.avatar

import androidx.compose.animation.core.*
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import info.jarvisai.app.R
import info.jarvisai.app.data.model.AvatarMouthState

private val GlowColor = Color(0xFF8B5CF6)   // Jarvis-Lila

@Composable
fun JarvisAvatar(
    isSpeaking: Boolean,
    mouthState: AvatarMouthState,
    modifier: Modifier = Modifier,
) {
    val infiniteTransition = rememberInfiniteTransition(label = "avatar_anim")

    val rawBob by infiniteTransition.animateFloat(
        initialValue = 0f, targetValue = 7f,
        animationSpec = infiniteRepeatable(
            tween(580, easing = FastOutSlowInEasing), RepeatMode.Reverse,
        ),
        label = "bob",
    )
    val glowPulse by infiniteTransition.animateFloat(
        initialValue = 0.0f, targetValue = 0.5f,
        animationSpec = infiniteRepeatable(
            tween(820, easing = FastOutSlowInEasing), RepeatMode.Reverse,
        ),
        label = "glow",
    )

    val speakingFactor by animateFloatAsState(
        targetValue = if (isSpeaking) 1f else 0f,
        animationSpec = tween(350), label = "speaking",
    )
    val avatarScale by animateFloatAsState(
        targetValue = if (isSpeaking) 1.05f else 1.0f,
        animationSpec = spring(
            dampingRatio = Spring.DampingRatioMediumBouncy,
            stiffness = Spring.StiffnessLow,
        ),
        label = "scale",
    )

    val glowAlpha = glowPulse * speakingFactor

    Box(
        contentAlignment = Alignment.Center,
        modifier = modifier
            .graphicsLayer {
                translationY = -rawBob * speakingFactor * 0.65f
                scaleX = avatarScale
                scaleY = avatarScale
            }
            .drawWithContent {
                drawContent()
                // Lila Glühen beim Sprechen als radialer Gradient-Overlay
                if (glowAlpha > 0.01f) {
                    drawRect(
                        brush = Brush.radialGradient(
                            colors = listOf(
                                GlowColor.copy(alpha = glowAlpha * 0.6f),
                                GlowColor.copy(alpha = glowAlpha * 0.2f),
                                Color.Transparent,
                            ),
                            radius = size.minDimension * 0.75f,
                        ),
                        blendMode = BlendMode.Screen,
                    )
                }
            },
    ) {
        Image(
            painter = painterResource(id = R.drawable.bg_jarvis),
            contentDescription = "Jarvis Ironman Avatar",
            contentScale = ContentScale.Fit,
            modifier = Modifier.fillMaxSize(),
        )
    }
}
