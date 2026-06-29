package com.example.galaxywatch8.presentation.theme

import androidx.compose.runtime.Composable
import androidx.wear.compose.material.Colors
import androidx.wear.compose.material.MaterialTheme

// Farbpalette der App – an das dunkle Wear-OS-Design angelehnt
private val wearColorPalette: Colors = Colors(
    primary = Purple200,
    primaryVariant = Purple700,
    secondary = Teal200,
    secondaryVariant = Teal200,
    error = Red400,
    onPrimary = Black,
    onSecondary = Black,
    onError = Black
)

/**
 * Globales Theme der App. Wird um den gesamten UI-Baum gelegt, damit
 * MaterialTheme.colors / typography ueberall verfuegbar sind.
 */
@Composable
fun GalaxyWatch8AppTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colors = wearColorPalette,
        content = content
    )
}
