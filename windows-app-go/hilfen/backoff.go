package hilfen

import "time"

// Grenzen des Wiederverbindungs-Abstands.
const (
	BackoffBasis = 3 * time.Second
	BackoffMax   = 60 * time.Second
)

// Backoff liefert die Wartezeit vor dem naechsten Verbindungsversuch.
// versuch zaehlt ab 1 die Fehlschlaege in Folge, zufall liegt in [0,1).
//
// Code-Review 2026-10-18: vorher wuchs der Abstand ohne Zufallsanteil, d.h.
// nach einem Server-Neustart verbanden sich alle Clients im selben Takt neu
// (Lastspitze). Jetzt "full jitter" auf der oberen Haelfte: die Wartezeit
// liegt zwischen der Haelfte und dem vollen exponentiellen Wert, gedeckelt
// auf BackoffMax.
func Backoff(versuch int, zufall float64) time.Duration {
	if versuch < 1 {
		versuch = 1
	}
	if zufall < 0 {
		zufall = 0
	}
	if zufall >= 1 {
		zufall = 0.999999
	}
	d := BackoffBasis
	for i := 1; i < versuch && d < BackoffMax; i++ {
		d *= 2
	}
	if d > BackoffMax {
		d = BackoffMax
	}
	halb := d / 2
	return halb + time.Duration(float64(d-halb)*zufall)
}
