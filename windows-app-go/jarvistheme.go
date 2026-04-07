package main

import (
	"image/color"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/theme"
)

// Jarvis-Farbpalette – identisch mit Android-Theme (Theme.kt / JarvisColorScheme)
type jarvisColors struct {
	bg             color.Color
	bgSecondary    color.Color
	surface        color.Color
	surfaceVariant color.Color
	accent         color.Color // JarvisPurple #9B59B6
	accentDark     color.Color // Gradient-Endpunkt #6A0DAD
	userBubble     color.Color // JarvisPurple @ 45% alpha
	jarvisBubble   color.Color // White @ 7% alpha
	textPrimary    color.Color
	muted          color.Color // JarvisMuted #888899
	success        color.Color // JarvisGreen #2ECC71
	danger         color.Color // JarvisError #E74C3C
}

var jc = jarvisColors{
	bg:             color.RGBA{0x0A, 0x0A, 0x0F, 0xFF}, // JarvisBackground
	bgSecondary:    color.RGBA{0x1A, 0x1A, 0x2E, 0xFF}, // JarvisSurface
	surface:        color.RGBA{0x1A, 0x1A, 0x2E, 0xFF}, // JarvisSurface
	surfaceVariant: color.RGBA{0x16, 0x21, 0x3E, 0xFF}, // JarvisSurfaceVariant
	accent:         color.RGBA{0x9B, 0x59, 0xB6, 0xFF}, // JarvisPurple
	accentDark:     color.RGBA{0x6A, 0x0D, 0xAD, 0xFF}, // Gradient-End
	userBubble:     color.RGBA{0x9B, 0x59, 0xB6, 0x73}, // JarvisPurple @ 45%
	jarvisBubble:   color.RGBA{0xFF, 0xFF, 0xFF, 0x30}, // White @ 19% (Fyne hat kein Material-Elevation wie Android)
	textPrimary:    color.RGBA{0xFF, 0xFF, 0xFF, 0xFF}, // Weiß
	muted:          color.RGBA{0x88, 0x88, 0x99, 0xFF}, // JarvisMuted
	success:        color.RGBA{0x2E, 0xCC, 0x71, 0xFF}, // JarvisGreen
	danger:         color.RGBA{0xE7, 0x4C, 0x3C, 0xFF}, // JarvisError
}

var colorTransparent = color.RGBA{0, 0, 0, 0}

// ── Custom Fyne Theme ─────────────────────────────────────────────────────────

type JarvisTheme struct{}

func (t JarvisTheme) Color(name fyne.ThemeColorName, variant fyne.ThemeVariant) color.Color {
	switch name {
	case theme.ColorNameBackground:
		return jc.bg
	case theme.ColorNameForeground:
		return jc.textPrimary
	case theme.ColorNamePrimary:
		return jc.accent
	case theme.ColorNameButton:
		return jc.surfaceVariant
	case theme.ColorNameDisabledButton:
		return color.RGBA{0x16, 0x21, 0x3E, 0xFF}
	case theme.ColorNameDisabled:
		return jc.muted
	case theme.ColorNameInputBackground:
		return color.RGBA{0xFF, 0xFF, 0xFF, 0x0F}
	case theme.ColorNameInputBorder:
		return color.RGBA{0x33, 0x33, 0x55, 0xFF} // outline #333355
	case theme.ColorNamePlaceHolder:
		return jc.muted
	case theme.ColorNameScrollBar:
		return color.RGBA{0x9B, 0x59, 0xB6, 0x66}
	case theme.ColorNameSeparator:
		return color.RGBA{0xFF, 0xFF, 0xFF, 0x14}
	// Dropdown / Popup / Menü – verhindert weißen Hintergrund
	case theme.ColorNameOverlayBackground:
		return jc.surface
	case theme.ColorNameMenuBackground:
		return jc.surface
	case theme.ColorNameHeaderBackground:
		return jc.surfaceVariant
	case theme.ColorNameHover:
		return color.RGBA{0x9B, 0x59, 0xB6, 0x30}
	case theme.ColorNameSelection:
		return color.RGBA{0x9B, 0x59, 0xB6, 0x55}
	case theme.ColorNameFocus:
		return jc.accent
	case theme.ColorNameShadow:
		return color.RGBA{0x00, 0x00, 0x00, 0x80}
	}
	return theme.DefaultTheme().Color(name, variant)
}

func (t JarvisTheme) Font(style fyne.TextStyle) fyne.Resource {
	return theme.DefaultTheme().Font(style)
}

func (t JarvisTheme) Icon(name fyne.ThemeIconName) fyne.Resource {
	return theme.DefaultTheme().Icon(name)
}

func (t JarvisTheme) Size(name fyne.ThemeSizeName) float32 {
	switch name {
	case theme.SizeNamePadding:
		return 6
	case theme.SizeNameInnerPadding:
		return 8
	case theme.SizeNameText:
		return 13
	case theme.SizeNameInputRadius:
		return 24 // wie Android OutlinedTextField (24dp)
	}
	return theme.DefaultTheme().Size(name)
}
