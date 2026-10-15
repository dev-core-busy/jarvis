package info.jarvisai.app.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

// Jarvis Dark Theme – angelehnt an das Glassmorphism-Design des Web-Frontends
val JarvisPurple = Color(0xFF9B59B6)
val JarvisPurpleLight = Color(0xFFBB86FC)
val JarvisGreen = Color(0xFF2ECC71)
val JarvisBackground = Color(0xFF0A0A0F)
val JarvisSurface = Color(0xFF1A1A2E)
val JarvisSurfaceVariant = Color(0xFF16213E)
val JarvisOnSurface = Color(0xFFE0E0E0)
val JarvisOnBackground = Color(0xFFE8E8F0)
val JarvisError = Color(0xFFE74C3C)
val JarvisMuted = Color(0xFF888899)

private val JarvisColorScheme = darkColorScheme(
    primary = JarvisPurple,
    onPrimary = Color.White,
    primaryContainer = Color(0xFF4A1A6B),
    onPrimaryContainer = JarvisPurpleLight,
    secondary = JarvisGreen,
    onSecondary = Color.Black,
    background = JarvisBackground,
    onBackground = JarvisOnBackground,
    surface = JarvisSurface,
    onSurface = JarvisOnSurface,
    surfaceVariant = JarvisSurfaceVariant,
    onSurfaceVariant = JarvisMuted,
    error = JarvisError,
    onError = Color.White,
    outline = Color(0xFF333355),
)

@Composable
fun JarvisTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = JarvisColorScheme,
        typography = JarvisTypography,
        content = content,
    )
}
