package hilfen

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestHTTPBasis(t *testing.T) {
	faelle := []struct{ ein, aus string }{
		{"wss://jarvis.firma.local/ws", "https://jarvis.firma.local"},
		{"wss://jarvis.firma.local/ws/", "https://jarvis.firma.local"},
		{"https://jarvis.firma.local", "https://jarvis.firma.local"},
		{"jarvis.firma.local", "https://jarvis.firma.local"},
		{"jarvis.firma.local:8443/ws", "https://jarvis.firma.local:8443"},
		{"ws://192.0.2.10:8000/ws", "http://192.0.2.10:8000"},
		{"http://192.0.2.10:8000/", "http://192.0.2.10:8000"},
		{"WSS://jarvis.firma.local/WS", "https://jarvis.firma.local/WS"},
		{"wss://proxy.firma.local/jarvis/ws", "https://proxy.firma.local/jarvis"},
		{"wss://jarvis.firma.local/ws?x=1", "https://jarvis.firma.local"},
		// "ws://" mitten im Pfad darf das Schema NICHT kippen (alter ReplaceAll-Fehler)
		{"wss://jarvis.firma.local/a/ws://b/ws", "https://jarvis.firma.local/a/ws://b"},
		{"  wss://jarvis.firma.local/ws  ", "https://jarvis.firma.local"},
		{"", ""},
		{"wss://", ""},
	}
	for _, f := range faelle {
		if got := HTTPBasis(f.ein); got != f.aus {
			t.Errorf("HTTPBasis(%q) = %q, erwartet %q", f.ein, got, f.aus)
		}
	}
}

func TestPruefeDownloadURL(t *testing.T) {
	gut := []string{"https://beispiel.de/downloads/jarvis.exe", "HTTPS://beispiel.de/x.exe"}
	schlecht := []string{"http://beispiel.de/jarvis.exe", "file:///C:/x.exe", "https:///ohne-host", "", "ftp://beispiel.de/x"}
	for _, u := range gut {
		if err := PruefeDownloadURL(u); err != nil {
			t.Errorf("%q abgelehnt: %v", u, err)
		}
	}
	for _, u := range schlecht {
		if err := PruefeDownloadURL(u); err == nil {
			t.Errorf("%q angenommen", u)
		}
	}
}

func exeInhalt(n int) []byte {
	b := bytes.Repeat([]byte{0x90}, n)
	b[0], b[1] = 'M', 'Z'
	return b
}

func pruefer(daten []byte) *ExePruefer {
	p := NeuerExePruefer()
	// erst einzelne Bytes schreiben: der Kopf darf ueber Schreibgrenzen gehen
	n := 1
	if len(daten) < n {
		n = len(daten)
	}
	_, _ = p.Write(daten[:n])
	_, _ = p.Write(daten[n:])
	return p
}

func TestExePruefer(t *testing.T) {
	gut := exeInhalt(int(MinEXEGroesse) + 10)
	sum := sha256.Sum256(gut)
	soll := hex.EncodeToString(sum[:])

	// Positivkontrolle: eine gueltige EXE mit passendem Hash besteht
	if err := pruefer(gut).Pruefe(soll); err != nil {
		t.Fatalf("gueltige EXE abgelehnt: %v", err)
	}
	if err := pruefer(gut).Pruefe(strings.ToUpper(soll)); err != nil {
		t.Errorf("Hash in Grossbuchstaben abgelehnt: %v", err)
	}
	// ohne Hash: kein Abbruch, aber eigener Hinweis
	if err := pruefer(gut).Pruefe(""); !errors.Is(err, ErrKeinHash) {
		t.Errorf("ohne Hash: erwartet ErrKeinHash, erhalten %v", err)
	}
	// falscher Hash
	if err := pruefer(gut).Pruefe(strings.Repeat("0", 64)); err == nil || errors.Is(err, ErrKeinHash) {
		t.Errorf("falscher Hash nicht erkannt: %v", err)
	}
	// HTML-Fehlerseite statt EXE
	html := append([]byte("<html>"), bytes.Repeat([]byte("x"), int(MinEXEGroesse))...)
	if err := pruefer(html).Pruefe(""); err == nil || errors.Is(err, ErrKeinHash) {
		t.Errorf("HTML als EXE angenommen: %v", err)
	}
	// abgebrochener Download
	if err := pruefer(exeInhalt(4096)).Pruefe(""); err == nil || errors.Is(err, ErrKeinHash) {
		t.Errorf("zu kleine Datei angenommen: %v", err)
	}
	// leer
	if err := NeuerExePruefer().Pruefe(""); err == nil || errors.Is(err, ErrKeinHash) {
		t.Errorf("leere Datei angenommen: %v", err)
	}
	// zu gross (Groesse simuliert, nicht 512 MB schreiben)
	p := pruefer(exeInhalt(int(MinEXEGroesse)))
	p.groesse = MaxEXEGroesse + 1
	if err := p.Pruefe(""); err == nil || errors.Is(err, ErrKeinHash) {
		t.Errorf("zu grosse Datei angenommen: %v", err)
	}
}

func TestUpdaterBatch(t *testing.T) {
	b := UpdaterBatch(`C:\Tools\100%\jarvis.exe`, `C:\Tools\100%\jarvis_old.exe`,
		`C:\Tools\100%\jarvis_update.exe`, "jarvis.exe")
	if strings.Contains(b, `100%\`) {
		t.Errorf("einfaches %% im Pfad nicht maskiert:\n%s", b)
	}
	if !strings.Contains(b, `C:\Tools\100%%\jarvis.exe`) {
		t.Errorf("maskierter Pfad fehlt:\n%s", b)
	}
	// Selbstloeschung bleibt ein einfaches %~f0 (Batch-Parameter, nicht maskieren)
	if !strings.Contains(b, `del "%~f0"`) {
		t.Errorf("Selbstloeschung fehlt:\n%s", b)
	}
	zeilen := strings.Split(strings.ReplaceAll(b, "\r\n", "\n"), "\n")
	// Nach JEDEM move steht eine errorlevel-Pruefung
	moves := 0
	for i, z := range zeilen {
		if strings.HasPrefix(strings.TrimSpace(z), "move ") {
			moves++
			if i+1 >= len(zeilen) || !strings.HasPrefix(strings.TrimSpace(zeilen[i+1]), "if errorlevel 1") {
				t.Errorf("nach %q fehlt die errorlevel-Pruefung", z)
			}
		}
	}
	if moves != 3 {
		t.Errorf("erwartet 3 move-Zeilen (weg, rein, zurueck), gefunden %d", moves)
	}
	// Die alte EXE wird nur im Erfolgszweig geloescht: genau ein del auf jarvis_old,
	// und es steht VOR dem Sprungziel :zurueck (also nicht im Fehlerweg).
	altDel, zurueck := -1, -1
	anzahl := 0
	for i, z := range zeilen {
		if strings.HasPrefix(z, "del ") && strings.Contains(z, "jarvis_old.exe") {
			altDel = i
			anzahl++
		}
		if z == ":zurueck" {
			zurueck = i
		}
	}
	if anzahl != 1 || altDel < 0 || zurueck < 0 || altDel > zurueck {
		t.Errorf("alte EXE wird im Fehlerweg geloescht (del-Zeile %d, :zurueck %d, Anzahl %d)", altDel, zurueck, anzahl)
	}
}

func TestSchreibeAtomar(t *testing.T) {
	dir := t.TempDir()
	ziel := filepath.Join(dir, "messages.json")
	if err := os.WriteFile(ziel, []byte("alt"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := SchreibeAtomar(ziel, []byte("neu"), 0600); err != nil {
		t.Fatal(err)
	}
	got, _ := os.ReadFile(ziel)
	if string(got) != "neu" {
		t.Errorf("Inhalt %q", got)
	}
	eintraege, _ := os.ReadDir(dir)
	if len(eintraege) != 1 {
		t.Errorf("Temp-Datei liegen geblieben: %v", eintraege)
	}
	// Schreiben in ein nicht vorhandenes Verzeichnis meldet den Fehler
	if err := SchreibeAtomar(filepath.Join(dir, "fehlt", "x.json"), []byte("x"), 0600); err == nil {
		t.Error("Fehler verschluckt")
	}
}

func TestEntprellerFasstZusammen(t *testing.T) {
	var mu sync.Mutex
	var aufrufe []int
	var gleichzeitig, maxGleich int32
	e := NeuerEntpreller(30*time.Millisecond, func(v int) {
		n := atomic.AddInt32(&gleichzeitig, 1)
		if n > atomic.LoadInt32(&maxGleich) {
			atomic.StoreInt32(&maxGleich, n)
		}
		time.Sleep(5 * time.Millisecond)
		mu.Lock()
		aufrufe = append(aufrufe, v)
		mu.Unlock()
		atomic.AddInt32(&gleichzeitig, -1)
	})
	for i := 1; i <= 50; i++ {
		e.Setze(i)
	}
	time.Sleep(150 * time.Millisecond)
	mu.Lock()
	defer mu.Unlock()
	if len(aufrufe) != 1 || aufrufe[0] != 50 {
		t.Errorf("erwartet genau einen Aufruf mit dem letzten Stand 50, erhalten %v", aufrufe)
	}
	if maxGleich > 1 {
		t.Errorf("Arbeit lief parallel (%d)", maxGleich)
	}
}

func TestEntprellerJetztUndVerwerfen(t *testing.T) {
	var mu sync.Mutex
	var aufrufe []string
	e := NeuerEntpreller(time.Hour, func(v string) {
		mu.Lock()
		aufrufe = append(aufrufe, v)
		mu.Unlock()
	})
	e.Setze("a")
	e.Jetzt()
	e.Jetzt() // nichts mehr offen
	e.Setze("b")
	e.Verwerfen()
	e.Jetzt() // verworfen bleibt verworfen
	mu.Lock()
	defer mu.Unlock()
	if len(aufrufe) != 1 || aufrufe[0] != "a" {
		t.Errorf("erwartet [a], erhalten %v", aufrufe)
	}
}

func TestBackoff(t *testing.T) {
	if d := Backoff(1, 0); d != BackoffBasis/2 {
		t.Errorf("Versuch 1, Zufall 0: %v", d)
	}
	if d := Backoff(1, 0.999); d > BackoffBasis || d < BackoffBasis/2 {
		t.Errorf("Versuch 1 ausserhalb: %v", d)
	}
	for v := 1; v < 100; v++ {
		for _, z := range []float64{-1, 0, 0.5, 0.999, 5} {
			d := Backoff(v, z)
			if d <= 0 || d > BackoffMax {
				t.Fatalf("Backoff(%d,%v)=%v ausserhalb (0,%v]", v, z, d, BackoffMax)
			}
		}
	}
	if d := Backoff(50, 0); d != BackoffMax/2 {
		t.Errorf("Deckel: %v", d)
	}
	// Zufall wirkt: zwei Clients mit verschiedenem Zufall warten verschieden lange
	if Backoff(4, 0.1) == Backoff(4, 0.9) {
		t.Error("kein Jitter")
	}
}

func TestPSZeichenkette(t *testing.T) {
	faelle := map[string]string{
		`C:\Temp\a.wav`:              `'C:\Temp\a.wav'`,
		`C:\Users\o'brien\a.wav`:     `'C:\Users\o''brien\a.wav'`,
		"C:\\Users\\o\u2019brien\\a": "'C:\\Users\\o\u2019\u2019brien\\a'",
		`$(Remove-Item x)`:           `'$(Remove-Item x)'`,
		``:                           `''`,
	}
	for ein, aus := range faelle {
		if got := PSZeichenkette(ein); got != aus {
			t.Errorf("PSZeichenkette(%q) = %q, erwartet %q", ein, got, aus)
		}
	}
}
