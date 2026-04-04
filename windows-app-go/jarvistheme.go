package main

import (
	"image/color"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/theme"
)

// Jarvis-Farbpalette (aus frontend/css/style.css und Android-Theme)
type jarvisColors struct {
	bg          color.Color
	bgSecondary color.Color
	surface     color.Color
	accent      color.Color
	userBubble  color.Color
	jarvisBubble color.Color
	textPrimary color.Color
	muted       color.Color
	success     color.Color
	danger      color.Color
}

var jc = jarvisColors{
	bg:           color.RGBA{0x0A, 0x0A, 0x0F, 0xFF},
	bgSecondary:  color.RGBA{0x11, 0x18, 0x27, 0xFF},
	surface:      color.RGBA{0x0F, 0x17, 0x2A, 0xC0},
	accent:       color.RGBA{0x63, 0x66, 0xF1, 0xFF},
	userBubble:   color.RGBA{0x63, 0x66, 0xF1, 0x48}, // rgba(99,102,241,0.28)
	jarvisBubble: color.RGBA{0x0F, 0x17, 0x2A, 0xCC}, // rgba(15,23,42,0.80)
	textPrimary:  color.RGBA{0xF8, 0xFA, 0xFC, 0xFF},
	muted:        color.RGBA{0x64, 0x74, 0x8B, 0xFF},
	success:      color.RGBA{0x10, 0xB9, 0x81, 0xFF},
	danger:       color.RGBA{0xEF, 0x44, 0x44, 0xFF},
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
		return jc.surface
	case theme.ColorNameInputBackground:
		return color.RGBA{0xFF, 0xFF, 0xFF, 0x0F}
	case theme.ColorNameInputBorder:
		return color.RGBA{0xFF, 0xFF, 0xFF, 0x1A}
	case theme.ColorNamePlaceHolder:
		return jc.muted
	case theme.ColorNameScrollBar:
		return color.RGBA{0x63, 0x66, 0xF1, 0x66}
	case theme.ColorNameSeparator:
		return color.RGBA{0xFF, 0xFF, 0xFF, 0x14}
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
		return 8
	}
	return theme.DefaultTheme().Size(name)
}
