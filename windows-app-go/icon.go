package main

import (
	_ "embed"

	"fyne.io/fyne/v2"
)

// jarvis_icon.png = das originale Android-App-Icon (J im Kreis, lila)
//
//go:embed jarvis_icon.png
var jarvisIconBytes []byte

// baseIcon gibt das eingebettete Icon als Fyne-Resource zurück.
func baseIcon() fyne.Resource {
	return &fyne.StaticResource{
		StaticName:    "jarvis.png",
		StaticContent: jarvisIconBytes,
	}
}

// newTrayIcon gibt das Tray-Icon zurück.
// Wir verwenden immer das originale Icon – der Status ist am Avatar-Fenster sichtbar.
func newTrayIcon(connected bool, dialogMode bool) fyne.Resource {
	// Das originale "J im Kreis" Icon direkt verwenden
	_ = connected
	_ = dialogMode
	return baseIcon()
}
