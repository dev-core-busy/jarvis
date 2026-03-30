package info.jarvisai.app.ui.avatar

import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.*
import androidx.compose.ui.graphics.drawscope.*
import info.jarvisai.app.data.model.AvatarMouthState

// ── Farb-Palette ──────────────────────────────────────────────────────────────

private val SkinColor     = Color(0xFFFDD9B5)
private val SkinShadow    = Color(0xFFE8B88A)
private val HairColor     = Color(0xFF1A0A02)
private val HairHighlight = Color(0xFF3D1F10)
private val IrisColor     = Color(0xFF8B5CF6)   // Jarvis-Lila
private val IrisDark      = Color(0xFF5B2D9E)
private val PupilColor    = Color(0xFF120820)
private val EyeWhite      = Color(0xFFFFFAFA)
private val LashColor     = Color(0xFF150804)
private val LipOutline    = Color(0xFFCB6060)
private val LipFill       = Color(0xFFD9534F)
private val TeethColor    = Color(0xFFFFF8F0)
private val OutlineColor  = Color(0xFF6B3010)
private val GlowPurple    = Color(0xFF8B5CF6)

// ── Haupt-Composable ──────────────────────────────────────────────────────────

@Composable
fun JarvisAvatar(
    isSpeaking: Boolean,
    mouthState: AvatarMouthState,
    modifier: Modifier = Modifier,
) {
    // Kontinuierliche Animations-Werte (laufen immer, werden gewichtet)
    val infiniteTransition = rememberInfiniteTransition(label = "avatar_anim")
    val rawBob by infiniteTransition.animateFloat(
        initialValue = 0f, targetValue = 7f,
        animationSpec = infiniteRepeatable(
            tween(580, easing = FastOutSlowInEasing), RepeatMode.Reverse,
        ),
        label = "bob",
    )
    val glowPulse by infiniteTransition.animateFloat(
        initialValue = 0.08f, targetValue = 0.32f,
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
        targetValue = if (isSpeaking) 1.04f else 1.0f,
        animationSpec = spring(
            dampingRatio = Spring.DampingRatioMediumBouncy,
            stiffness = Spring.StiffnessLow,
        ),
        label = "scale",
    )

    Canvas(modifier = modifier.graphicsLayer {
        translationY = -rawBob * speakingFactor * 0.65f
        scaleX = avatarScale
        scaleY = avatarScale
    }) {
        val W = size.width
        val H = size.height

        // ── Lila Außenglühen beim Sprechen (Compose-nativ, kein BlurMaskFilter) ──
        if (speakingFactor > 0.01f) {
            val baseAlpha = glowPulse * speakingFactor
            // Mehrere halbdurchsichtige Ovale in verschiedenen Größen → Blur-Effekt
            repeat(5) { i ->
                val scale = 1.0f + i * 0.10f
                val alpha = baseAlpha * (0.18f - i * 0.032f)
                if (alpha > 0f) {
                    drawOval(
                        color = GlowPurple.copy(alpha = alpha),
                        topLeft = Offset(W * (0.5f - 0.42f * scale), H * (0.5f - 0.47f * scale)),
                        size = Size(W * 0.84f * scale, H * 0.94f * scale),
                    )
                }
            }
        }

        // ── Haare (hintere Ebene) ──────────────────────────────────────────────
        drawHair(W, H)

        // ── Ohren ─────────────────────────────────────────────────────────────
        drawEar(W, H, isLeft = true)
        drawEar(W, H, isLeft = false)

        // ── Gesichts-Oval ─────────────────────────────────────────────────────
        // Weicher Schlagschatten (semi-transparentes dunkles Oval leicht versetzt)
        drawOval(
            color = Color.Black.copy(alpha = 0.22f),
            topLeft = Offset(W * 0.13f, H * 0.13f),
            size = Size(W * 0.78f, H * 0.84f),
        )
        // Gesichtsfläche
        drawOval(
            color = SkinColor,
            topLeft = Offset(W * 0.11f, H * 0.09f),
            size = Size(W * 0.78f, H * 0.84f),
        )
        // Seitliche Wangenschatten
        drawOval(color = SkinShadow.copy(alpha = 0.26f),
            topLeft = Offset(W*0.60f, H*0.38f), size = Size(W*0.28f, H*0.42f))
        drawOval(color = SkinShadow.copy(alpha = 0.26f),
            topLeft = Offset(W*0.12f, H*0.38f), size = Size(W*0.28f, H*0.42f))
        // Gesichts-Kontur
        drawOval(
            color = OutlineColor.copy(alpha = 0.26f),
            topLeft = Offset(W * 0.11f, H * 0.09f),
            size = Size(W * 0.78f, H * 0.84f),
            style = Stroke(width = W * 0.015f),
        )

        // ── Stirn-Pony (über Gesicht) ──────────────────────────────────────────
        drawBangs(W, H)

        // ── Rouge (Compose-nativ, kein BlurMaskFilter) ────────────────────────
        // Drei überlappende Ovale mit abnehmender Alpha simulieren weichen Blur
        repeat(3) { i ->
            val scale = 1.0f + i * 0.35f
            val alpha = 0.14f - i * 0.04f
            drawOval(Color(0xFFFF9A9A).copy(alpha = alpha),
                Offset(W*(0.26f - 0.04f*scale), H*(0.53f - 0.02f*scale)),
                Size(W*0.16f*scale, H*0.10f*scale))
            drawOval(Color(0xFFFF9A9A).copy(alpha = alpha),
                Offset(W*(0.58f - 0.04f*scale), H*(0.53f - 0.02f*scale)),
                Size(W*0.16f*scale, H*0.10f*scale))
        }

        // ── Augenbrauen ────────────────────────────────────────────────────────
        drawEyebrow(W, H, isLeft = true)
        drawEyebrow(W, H, isLeft = false)

        // ── Augen ──────────────────────────────────────────────────────────────
        drawAnimeEye(W, H, isLeft = true)
        drawAnimeEye(W, H, isLeft = false)

        // ── Nase (anime-dezent) ────────────────────────────────────────────────
        val nosePath = Path().apply {
            moveTo(W * 0.46f, H * 0.58f)
            cubicTo(W*0.45f, H*0.625f, W*0.50f, H*0.635f, W*0.54f, H*0.625f)
            cubicTo(W*0.555f, H*0.62f, W*0.555f, H*0.61f, W*0.545f, H*0.60f)
        }
        drawPath(nosePath, OutlineColor.copy(alpha = 0.30f),
            style = Stroke(W * 0.010f, cap = StrokeCap.Round))

        // ── Mund ───────────────────────────────────────────────────────────────
        drawMouth(W, H, mouthState)
    }
}

// ── Private Hilfsfunktionen ───────────────────────────────────────────────────

private fun DrawScope.drawHair(W: Float, H: Float) {
    val mainPath = Path().apply {
        moveTo(W*0.13f, H*0.56f)
        cubicTo(W*0.06f, H*0.30f, W*0.10f, H*0.04f, W*0.50f, H*0.01f)
        cubicTo(W*0.90f, H*0.04f, W*0.94f, H*0.30f, W*0.87f, H*0.56f)
        cubicTo(W*0.74f, H*0.44f, W*0.26f, H*0.44f, W*0.13f, H*0.56f)
        close()
    }
    drawPath(mainPath, HairColor)

    val shinePath = Path().apply {
        moveTo(W*0.32f, H*0.04f)
        cubicTo(W*0.40f, H*0.02f, W*0.54f, H*0.02f, W*0.58f, H*0.06f)
        cubicTo(W*0.54f, H*0.11f, W*0.40f, H*0.11f, W*0.32f, H*0.04f)
        close()
    }
    drawPath(shinePath, HairHighlight.copy(alpha = 0.55f))

    val leftStrand = Path().apply {
        moveTo(W*0.06f, H*0.40f)
        cubicTo(W*0.02f, H*0.55f, W*0.04f, H*0.72f, W*0.10f, H*0.80f)
        cubicTo(W*0.14f, H*0.74f, W*0.12f, H*0.60f, W*0.13f, H*0.56f)
        close()
    }
    drawPath(leftStrand, HairColor)

    val rightStrand = Path().apply {
        moveTo(W*0.94f, H*0.40f)
        cubicTo(W*0.98f, H*0.55f, W*0.96f, H*0.72f, W*0.90f, H*0.80f)
        cubicTo(W*0.86f, H*0.74f, W*0.88f, H*0.60f, W*0.87f, H*0.56f)
        close()
    }
    drawPath(rightStrand, HairColor)
}

private fun DrawScope.drawBangs(W: Float, H: Float) {
    val left = Path().apply {
        moveTo(W*0.12f, H*0.27f)
        cubicTo(W*0.14f, H*0.41f, W*0.23f, H*0.47f, W*0.27f, H*0.38f)
        cubicTo(W*0.23f, H*0.30f, W*0.18f, H*0.21f, W*0.12f, H*0.27f)
        close()
    }
    drawPath(left, HairColor)

    val mid = Path().apply {
        moveTo(W*0.34f, H*0.10f)
        cubicTo(W*0.36f, H*0.31f, W*0.44f, H*0.41f, W*0.50f, H*0.37f)
        cubicTo(W*0.56f, H*0.41f, W*0.64f, H*0.31f, W*0.66f, H*0.10f)
        cubicTo(W*0.58f, H*0.06f, W*0.42f, H*0.06f, W*0.34f, H*0.10f)
        close()
    }
    drawPath(mid, HairColor)

    val right = Path().apply {
        moveTo(W*0.88f, H*0.27f)
        cubicTo(W*0.82f, H*0.41f, W*0.77f, H*0.47f, W*0.73f, H*0.38f)
        cubicTo(W*0.77f, H*0.30f, W*0.82f, H*0.21f, W*0.88f, H*0.27f)
        close()
    }
    drawPath(right, HairColor)

    val ponyShine = Path().apply {
        moveTo(W*0.42f, H*0.12f)
        cubicTo(W*0.46f, H*0.10f, W*0.54f, H*0.10f, W*0.57f, H*0.13f)
        cubicTo(W*0.54f, H*0.17f, W*0.46f, H*0.17f, W*0.42f, H*0.12f)
        close()
    }
    drawPath(ponyShine, HairHighlight.copy(alpha = 0.45f))
}

private fun DrawScope.drawEar(W: Float, H: Float, isLeft: Boolean) {
    val cx = if (isLeft) W * 0.085f else W * 0.915f
    val cy = H * 0.47f
    drawOval(SkinColor,
        Offset(cx - W*0.045f, cy - H*0.07f), Size(W*0.090f, H*0.14f))
    drawOval(SkinShadow.copy(alpha = 0.32f),
        Offset(cx - W*0.027f, cy - H*0.044f), Size(W*0.054f, H*0.088f))
    drawOval(OutlineColor.copy(alpha = 0.28f),
        Offset(cx - W*0.045f, cy - H*0.07f), Size(W*0.090f, H*0.14f),
        style = Stroke(W * 0.009f))
}

private fun DrawScope.drawEyebrow(W: Float, H: Float, isLeft: Boolean) {
    val cx = if (isLeft) W * 0.32f else W * 0.68f
    val cy = H * 0.33f
    val hw = W * 0.125f
    val path = Path().apply {
        if (isLeft) {
            moveTo(cx - hw, cy + W*0.013f)
            cubicTo(cx - hw*0.2f, cy - W*0.020f, cx + hw*0.3f, cy - W*0.016f, cx + hw, cy + W*0.008f)
        } else {
            moveTo(cx - hw, cy + W*0.008f)
            cubicTo(cx - hw*0.3f, cy - W*0.016f, cx + hw*0.2f, cy - W*0.020f, cx + hw, cy + W*0.013f)
        }
    }
    drawPath(path, HairColor, style = Stroke(W * 0.025f, cap = StrokeCap.Round))
}

private fun DrawScope.drawAnimeEye(W: Float, H: Float, isLeft: Boolean) {
    val cx = if (isLeft) W * 0.32f else W * 0.68f
    val cy = H * 0.44f
    val ew = W * 0.23f
    val eh = H * 0.115f

    // 1. Augenweiß
    drawOval(EyeWhite, Offset(cx - ew/2, cy - eh/2), Size(ew, eh))

    // 2. Iris
    val irw = W * 0.155f
    val irh = H * 0.125f
    drawOval(IrisDark, Offset(cx - irw/2, cy - irh/2), Size(irw, irh))
    drawOval(IrisColor, Offset(cx - irw*0.82f/2, cy - irh*0.72f/2), Size(irw*0.82f, irh*0.72f))

    // 3. Pupille
    drawCircle(PupilColor, W * 0.052f, Offset(cx, cy + H*0.005f))

    // 4. Glanzpunkte
    drawCircle(Color.White, W * 0.030f, Offset(cx + W*0.044f, cy - H*0.036f))
    drawCircle(Color.White.copy(alpha = 0.70f), W * 0.015f, Offset(cx - W*0.030f, cy + H*0.010f))

    // 5. Oberes Augenlid (dicker Bogen)
    drawArc(LashColor, startAngle = 185f, sweepAngle = 170f, useCenter = false,
        topLeft = Offset(cx - ew/2, cy - eh/2), size = Size(ew, eh),
        style = Stroke(W * 0.030f, cap = StrokeCap.Round))

    // 6. Wimpern
    repeat(5) { i ->
        val t = (i.toFloat() / 4f) * 2f - 1f
        val lashX = cx + t * ew * 0.37f
        val topY = cy - eh * 0.50f
        drawLine(LashColor, Offset(lashX, topY),
            Offset(lashX + t * W*0.022f, topY - H*0.036f),
            W * 0.016f, cap = StrokeCap.Round)
    }

    // 7. Unteres Augenlid
    drawArc(LashColor.copy(alpha = 0.35f), startAngle = 5f, sweepAngle = 170f, useCenter = false,
        topLeft = Offset(cx - ew/2, cy - eh/2), size = Size(ew, eh),
        style = Stroke(W * 0.009f, cap = StrokeCap.Round))
}

private fun DrawScope.drawMouth(W: Float, H: Float, mouthState: AvatarMouthState) {
    val cx = W * 0.50f
    val cy = H * 0.715f

    when (mouthState) {
        AvatarMouthState.CLOSED -> {
            val path = Path().apply {
                moveTo(cx - W*0.095f, cy - H*0.005f)
                cubicTo(cx - W*0.025f, cy + H*0.024f,
                        cx + W*0.025f, cy + H*0.024f,
                        cx + W*0.095f, cy - H*0.005f)
            }
            drawPath(path, LipOutline, style = Stroke(W * 0.020f, cap = StrokeCap.Round))
        }
        AvatarMouthState.SMALL -> {
            val mw = W * 0.140f; val mh = H * 0.050f
            drawOval(LipFill.copy(alpha = 0.85f), Offset(cx - mw/2, cy - mh/2), Size(mw, mh))
            drawOval(PupilColor.copy(alpha = 0.55f),
                Offset(cx - mw*0.55f/2, cy - mh*0.55f/2), Size(mw*0.55f, mh*0.55f))
            drawOval(LipOutline, Offset(cx - mw/2, cy - mh/2), Size(mw, mh), style = Stroke(W*0.011f))
        }
        AvatarMouthState.OPEN -> {
            val mw = W * 0.220f; val mh = H * 0.090f
            drawOval(PupilColor.copy(alpha = 0.88f), Offset(cx - mw/2, cy - mh/2), Size(mw, mh))
            val toothTop = cy - mh/2 + H*0.005f
            val toothH = mh * 0.42f
            drawRect(TeethColor, Offset(cx - mw*0.40f, toothTop), Size(mw*0.80f, toothH))
            repeat(3) { i ->
                val tx = cx - mw*0.40f + (mw*0.80f / 4f) * (i + 1)
                drawLine(OutlineColor.copy(alpha = 0.22f),
                    Offset(tx, toothTop), Offset(tx, toothTop + toothH), W*0.007f)
            }
            drawOval(LipOutline, Offset(cx - mw/2, cy - mh/2), Size(mw, mh), style = Stroke(W*0.016f))
        }
    }
}
