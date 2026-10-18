package hilfen

import (
	"os"
	"path/filepath"
	"sync"
	"time"
)

// SchreibeAtomar schreibt eine Datei ueber eine Temp-Datei im selben
// Verzeichnis und benennt sie danach um.
//
// Code-Review 2026-10-18: os.WriteFile kuerzt die Zieldatei zuerst und
// schreibt dann – ein Absturz oder ein zweiter, paralleler Schreiber dazwischen
// hinterliess eine leere oder halbe messages.json/config.json. os.Rename ersetzt
// unter Windows eine vorhandene Datei (MoveFileEx mit REPLACE_EXISTING), der
// Leser sieht also immer entweder den alten oder den neuen Stand.
func SchreibeAtomar(pfad string, daten []byte, rechte os.FileMode) error {
	f, err := os.CreateTemp(filepath.Dir(pfad), "."+filepath.Base(pfad)+".*.tmp")
	if err != nil {
		return err
	}
	tmp := f.Name()
	aufraeumen := func() { _ = os.Remove(tmp) }
	if _, err := f.Write(daten); err != nil {
		f.Close()
		aufraeumen()
		return err
	}
	if err := f.Sync(); err != nil {
		f.Close()
		aufraeumen()
		return err
	}
	if err := f.Close(); err != nil {
		aufraeumen()
		return err
	}
	if err := os.Chmod(tmp, rechte); err != nil {
		aufraeumen()
		return err
	}
	if err := os.Rename(tmp, pfad); err != nil {
		aufraeumen()
		return err
	}
	return nil
}

// Entpreller fasst schnell aufeinanderfolgende Auftraege zu EINEM zusammen:
// gespeichert wird der zuletzt uebergebene Wert, fruehestens `pause` nach dem
// letzten Aufruf von Setze. Die Arbeit laeuft immer nacheinander, nie parallel.
//
// Code-Review 2026-10-18: SaveHistory lief pro Streaming-Teil als eigene
// Goroutine – Dutzende gleichzeitige Schreiber auf dieselbe Datei, und ein
// aelterer Stand konnte einen neueren ueberholen.
type Entpreller[T any] struct {
	mu     sync.Mutex
	pause  time.Duration
	arbeit func(T)
	wert   T
	offen  bool
	timer  *time.Timer
	laeuft sync.Mutex // serialisiert die Arbeit selbst
}

// NeuerEntpreller legt einen Entpreller an.
func NeuerEntpreller[T any](pause time.Duration, arbeit func(T)) *Entpreller[T] {
	return &Entpreller[T]{pause: pause, arbeit: arbeit}
}

// Setze merkt sich v als neuesten Stand und startet die Wartezeit neu.
func (e *Entpreller[T]) Setze(v T) {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.wert = v
	e.offen = true
	if e.timer == nil {
		e.timer = time.AfterFunc(e.pause, e.feuern)
	} else {
		e.timer.Reset(e.pause)
	}
}

// feuern fuehrt den offenen Auftrag aus (vom Timer oder von Jetzt).
func (e *Entpreller[T]) feuern() {
	e.laeuft.Lock()
	defer e.laeuft.Unlock()
	e.mu.Lock()
	if !e.offen {
		e.mu.Unlock()
		return
	}
	v := e.wert
	e.offen = false
	var leer T
	e.wert = leer
	e.mu.Unlock()
	e.arbeit(v)
}

// Jetzt fuehrt einen offenen Auftrag sofort aus und wartet darauf (Beenden).
func (e *Entpreller[T]) Jetzt() {
	e.mu.Lock()
	if e.timer != nil {
		e.timer.Stop()
	}
	e.mu.Unlock()
	e.feuern()
}

// Verwerfen streicht einen offenen Auftrag. Wartet auf eine gerade laufende
// Arbeit, damit danach garantiert nichts Altes mehr geschrieben wird
// (z.B. "Verlauf loeschen" waehrend ein Speichern ansteht).
func (e *Entpreller[T]) Verwerfen() {
	e.mu.Lock()
	if e.timer != nil {
		e.timer.Stop()
	}
	e.offen = false
	var leer T
	e.wert = leer
	e.mu.Unlock()
	e.laeuft.Lock()
	//nolint:staticcheck // leerer kritischer Abschnitt: nur auf laufende Arbeit warten
	e.laeuft.Unlock()
}
