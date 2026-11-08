//go:build windows

package main

import (
	"syscall"
	"time"
	"unsafe"
)

// Nativer Bestaetigungsdialog (siehe bestaetigung.go).
//
// MessageBoxTimeoutW schliesst sich nach der Frist selbst (Rueckgabe 32000) –
// das gilt als Ablehnung. Die Funktion ist seit Windows XP in user32 exportiert,
// aber nicht dokumentiert; fehlt sie, faellt die App auf MessageBoxW ohne Frist
// zurueck (der Server wertet eine spaete Antwort dann als nicht zustellbar).
// Bewusst FindProc statt MustFindProc: ein fehlender Export darf die App nicht
// beim Start beenden.

const (
	mbYesNo         = 0x00000004
	mbIconWarning   = 0x00000030
	mbDefButton2    = 0x00000100 // Vorgabe "Nein": ein versehentliches Enter lehnt ab
	mbSetForeground = 0x00010000
	mbTopmost       = 0x00040000
	idYes           = 6
)

var (
	pMessageBoxTimeoutW, _ = user32.FindProc("MessageBoxTimeoutW")
	pMessageBoxW, _        = user32.FindProc("MessageBoxW")
)

// KannBestaetigen meldet dem Server, dass diese App Bestaetigungen anzeigt.
func KannBestaetigen() bool { return pMessageBoxTimeoutW != nil || pMessageBoxW != nil }

// ZeigeBestaetigung blockiert bis zur Entscheidung; true nur bei "Ja".
func ZeigeBestaetigung(titel, text string, frist time.Duration) bool {
	pText, err1 := syscall.UTF16PtrFromString(text)
	pTitel, err2 := syscall.UTF16PtrFromString(titel)
	if err1 != nil || err2 != nil {
		return false // Nullzeichen im Text: lieber ablehnen als etwas anderes zeigen
	}
	stil := uintptr(mbYesNo | mbIconWarning | mbDefButton2 | mbSetForeground | mbTopmost)
	var r uintptr
	switch {
	case pMessageBoxTimeoutW != nil:
		r, _, _ = pMessageBoxTimeoutW.Call(0, uintptr(unsafe.Pointer(pText)),
			uintptr(unsafe.Pointer(pTitel)), stil, 0, uintptr(frist.Milliseconds()))
	case pMessageBoxW != nil:
		r, _, _ = pMessageBoxW.Call(0, uintptr(unsafe.Pointer(pText)),
			uintptr(unsafe.Pointer(pTitel)), stil)
	default:
		return false
	}
	return r == idYes
}
