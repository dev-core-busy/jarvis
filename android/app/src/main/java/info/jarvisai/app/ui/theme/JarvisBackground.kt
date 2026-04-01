package info.jarvisai.app.ui.theme

import androidx.compose.animation.core.*
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.*
import kotlin.math.*

/**
 * Jarvis HUD Background – animiertes Hexagon-Gitter + Scan-Linie + Partikel.
 * Inspiriert vom Iron-Man-JARVIS-Interface: tiefes Marineblau, Cyan-Akzente.
 */
@Composable
fun JarvisHudBackground(modifier: Modifier = Modifier) {
    val infiniteTransition = rememberInfiniteTransition(label = "hud")

    // Scan-Linie: läuft von oben nach unten, 4s Zyklus
    val scanY by infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(4000, easing = LinearEasing),
            repeatMode = RepeatMode.Restart,
        ),
        label = "scan",
    )

    // Puls-Glow: 2s Atemzug
    val pulseAlpha by infiniteTransition.animateFloat(
        initialValue = 0.15f,
        targetValue = 0.40f,
        animationSpec = infiniteRepeatable(
            animation = tween(2000, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "pulse",
    )

    // Partikel-Drift: 6s Zyklus
    val particleDrift by infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(6000, easing = LinearEasing),
            repeatMode = RepeatMode.Restart,
        ),
        label = "particles",
    )

    Box(modifier = modifier.fillMaxSize().drawBehind {
        val w = size.width
        val h = size.height

        // ── Hintergrund ─────────────────────────────────────────────
        drawRect(Color(0xFF030D1E))

        // Tiefer Glow-Kreis in der Mitte
        drawCircle(
            brush = Brush.radialGradient(
                colors = listOf(Color(0xFF0D4080).copy(alpha = 0.85f), Color.Transparent),
                center = Offset(w * 0.5f, h * 0.45f),
                radius = w * 0.9f,
            ),
        )

        // Cyan-Akzent oben
        drawRect(
            brush = Brush.radialGradient(
                colors = listOf(Color(0xFF00D4FF).copy(alpha = pulseAlpha * 0.7f), Color.Transparent),
                center = Offset(w * 0.5f, 0f),
                radius = w * 0.8f,
            ),
        )

        // ── Hexagon-Gitter ───────────────────────────────────────────
        val hexR = 38f          // Außenradius eines Hexagons
        val hexH = hexR * sqrt(3f)
        val hexW = hexR * 2f
        val cols = (w / (hexW * 0.75f)).toInt() + 2
        val rows = (h / hexH).toInt() + 2

        val hexPath = Path()
        for (row in -1..rows) {
            for (col in -1..cols) {
                val cx = col * hexW * 0.75f
                val cy = row * hexH + if (col % 2 != 0) hexH * 0.5f else 0f

                hexPath.reset()
                for (i in 0..5) {
                    val angle = Math.toRadians((60.0 * i - 30)).toFloat()
                    val px = cx + hexR * cos(angle)
                    val py = cy + hexR * sin(angle)
                    if (i == 0) hexPath.moveTo(px, py) else hexPath.lineTo(px, py)
                }
                hexPath.close()

                // Distanz zur Mitte → Helligkeit variiert
                val dist = sqrt((cx - w * 0.5f).pow(2) + (cy - h * 0.45f).pow(2))
                val maxDist = sqrt((w * 0.5f).pow(2) + (h * 0.45f).pow(2))
                val brightness = 1f - (dist / maxDist).coerceIn(0f, 1f)
                val alpha = (0.12f + brightness * 0.35f).coerceIn(0.06f, 0.50f)

                drawPath(
                    path = hexPath,
                    color = Color(0xFF00CFFF).copy(alpha = alpha),
                    style = androidx.compose.ui.graphics.drawscope.Stroke(width = 1.2f),
                )
            }
        }

        // ── Scan-Linie ───────────────────────────────────────────────
        val scanYPx = scanY * h
        drawRect(
            brush = Brush.verticalGradient(
                colors = listOf(
                    Color.Transparent,
                    Color(0xFF00EEFF).copy(alpha = 0.45f),
                    Color(0xFF00FFFF).copy(alpha = 0.85f),
                    Color(0xFF00EEFF).copy(alpha = 0.45f),
                    Color.Transparent,
                ),
                startY = scanYPx - 24f,
                endY = scanYPx + 24f,
            ),
        )

        // ── Partikel ─────────────────────────────────────────────────
        val particleCount = 28
        val rng = java.util.Random(42)
        repeat(particleCount) { i ->
            val baseX = rng.nextFloat() * w
            val baseY = rng.nextFloat() * h
            val speed = 0.3f + rng.nextFloat() * 0.7f
            val px = baseX
            val py = (baseY - particleDrift * h * speed) % h
            val size = 1.5f + rng.nextFloat() * 2.5f
            val alpha = 0.3f + rng.nextFloat() * 0.5f
            drawCircle(
                color = Color(0xFF00EEFF).copy(alpha = alpha),
                radius = size,
                center = Offset(px, if (py < 0) py + h else py),
            )
        }

        // ── Horizontale Akzent-Linien ────────────────────────────────
        listOf(0.22f, 0.55f, 0.78f).forEach { yFrac ->
            val y = h * yFrac
            drawLine(
                brush = Brush.horizontalGradient(
                    colors = listOf(
                        Color.Transparent,
                        Color(0xFF00CFFF).copy(alpha = 0.35f),
                        Color(0xFF00EEFF).copy(alpha = 0.65f),
                        Color(0xFF00CFFF).copy(alpha = 0.35f),
                        Color.Transparent,
                    ),
                ),
                start = Offset(0f, y),
                end = Offset(w, y),
                strokeWidth = 1.5f,
            )
        }

        // ── Vignette ─────────────────────────────────────────────────
        drawRect(
            brush = Brush.radialGradient(
                colors = listOf(Color.Transparent, Color(0xFF010608).copy(alpha = 0.7f)),
                center = Offset(w * 0.5f, h * 0.5f),
                radius = w * 0.85f,
            ),
        )
    })
}
