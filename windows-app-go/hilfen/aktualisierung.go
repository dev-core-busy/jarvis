package hilfen

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"hash"
	"io"
	"net/url"
	"strings"
)

// Grenzen fuer die heruntergeladene Update-EXE.
//
// Code-Review 2026-10-18: vorher wurde jede Antwort ungeprueft als EXE
// eingewechselt – auch eine HTML-Fehlerseite (404/502 eines Proxys) oder ein
// abgebrochener Download. Danach war die einzige lauffaehige Fassung weg.
const (
	// MinEXEGroesse: die echte jarvis.exe ist mehrere zehn MB gross; alles
	// unter 1 MB ist sicher keine vollstaendige Fassung.
	MinEXEGroesse int64 = 1 << 20
	// MaxEXEGroesse deckelt den Download (io.LimitReader), damit eine
	// fehlgeleitete Antwort nicht die Platte fuellt.
	MaxEXEGroesse int64 = 512 << 20
)

// PruefeDownloadURL laesst nur https:// mit Rechnernamen zu.
//
// Code-Review 2026-10-18: die Adresse kommt aus version_windows.json; ein
// http:// (oder file://) dort haette eine unsignierte EXE ueber einen
// unverschluesselten Weg eingewechselt.
func PruefeDownloadURL(adresse string) error {
	u, err := url.Parse(strings.TrimSpace(adresse))
	if err != nil {
		return fmt.Errorf("Download-Adresse ungueltig: %w", err)
	}
	if !strings.EqualFold(u.Scheme, "https") || u.Host == "" {
		return fmt.Errorf("Download-Adresse muss https:// sein: %q", adresse)
	}
	return nil
}

// ExePruefer sammelt beim Schreiben Kopf, Groesse und SHA-256 der Datei.
// Er wird per io.MultiWriter neben die Zieldatei gehaengt.
type ExePruefer struct {
	kopf    []byte
	groesse int64
	h       hash.Hash
}

// NeuerExePruefer legt einen leeren Pruefer an.
func NeuerExePruefer() *ExePruefer {
	return &ExePruefer{h: sha256.New()}
}

// Write erfuellt io.Writer.
func (p *ExePruefer) Write(b []byte) (int, error) {
	if len(p.kopf) < 2 {
		rest := 2 - len(p.kopf)
		if rest > len(b) {
			rest = len(b)
		}
		p.kopf = append(p.kopf, b[:rest]...)
	}
	p.groesse += int64(len(b))
	p.h.Write(b)
	return len(b), nil
}

var _ io.Writer = (*ExePruefer)(nil)

// Groesse liefert die bisher geschriebene Byte-Zahl.
func (p *ExePruefer) Groesse() int64 { return p.groesse }

// SHA256 liefert den Hash als Kleinbuchstaben-Hex.
func (p *ExePruefer) SHA256() string { return hex.EncodeToString(p.h.Sum(nil)) }

// ErrKeinHash meldet, dass der Server keinen Hash mitgeliefert hat. Das ist
// (noch) kein Abbruchgrund – der Aufrufer protokolliert es.
var ErrKeinHash = errors.New("version_windows.json liefert kein sha256 – Inhalt nur ueber Kopf und Groesse geprueft")

// Pruefe entscheidet, ob die geschriebene Datei eingewechselt werden darf.
// sollHash leer -> alle uebrigen Pruefungen gelten, Rueckgabe ErrKeinHash.
func (p *ExePruefer) Pruefe(sollHash string) error {
	if p.groesse > MaxEXEGroesse {
		return fmt.Errorf("Download groesser als %d Bytes – abgebrochen", MaxEXEGroesse)
	}
	if p.groesse < MinEXEGroesse {
		return fmt.Errorf("Download zu klein (%d Bytes) – keine vollstaendige EXE", p.groesse)
	}
	if string(p.kopf) != "MZ" {
		return fmt.Errorf("Download ist keine Windows-EXE (Kopf %q statt \"MZ\")", string(p.kopf))
	}
	soll := strings.ToLower(strings.TrimSpace(sollHash))
	if soll == "" {
		return ErrKeinHash
	}
	if ist := p.SHA256(); ist != soll {
		return fmt.Errorf("SHA-256 stimmt nicht: erwartet %s, erhalten %s", soll, ist)
	}
	return nil
}

// batchPfad maskiert einen Pfad fuer eine Zeile in einer .bat-Datei, die ihn
// in doppelten Anfuehrungszeichen benutzt.
//
// Code-Review 2026-10-18: in einer Batch-Datei wird "%" auch innerhalb von
// Anfuehrungszeichen als Variablenbeginn gelesen – ein Installationspfad wie
// C:\Tools\100%\jarvis.exe zerfiel sonst. "%%" ist in einer .bat-Datei ein
// woertliches "%". Andere Sonderzeichen (& | < > ^) sind innerhalb der
// Anfuehrungszeichen harmlos, "!" nur bei aktivierter verzoegerter Expansion
// (hier aus), und ein '"' kann in einem Windows-Pfad nicht vorkommen.
func batchPfad(p string) string {
	return strings.ReplaceAll(p, "%", "%%")
}

// UpdaterBatch erzeugt das Skript, das nach dem Beenden der App die EXE tauscht.
//
// Code-Review 2026-10-18: die alte Fassung pruefte keinen errorlevel und
// loeschte am Ende die alte EXE bedingungslos. Schlug das zweite "move" fehl
// (Virenscanner, Sperre), stand gar keine lauffaehige EXE mehr da. Jetzt:
//   - scheitert das Wegbenennen der alten EXE: nichts anfassen, alte starten;
//   - scheitert das Einwechseln der neuen: die alte zurueckbenennen und starten
//     (scheitert auch das, die alte unter ihrem Ausweichnamen starten und
//     nichts loeschen);
//   - die alte wird erst geloescht, wenn die neue an ihrem Platz liegt.
//
// imageName ist der Prozessname, auf dessen Ende gewartet wird.
func UpdaterBatch(exePfad, altPfad, neuPfad, imageName string) string {
	exe, alt, neu := batchPfad(exePfad), batchPfad(altPfad), batchPfad(neuPfad)
	img := batchPfad(imageName)
	return "@echo off\r\n" +
		"chcp 65001 >nul\r\n" +
		"setlocal DisableDelayedExpansion\r\n" +
		"timeout /t 2 /nobreak >nul\r\n" +
		":waitloop\r\n" +
		"tasklist /fi \"imagename eq " + img + "\" 2>nul | find /i \"" + img + "\" >nul\r\n" +
		"if not errorlevel 1 (\r\n" +
		"    timeout /t 1 /nobreak >nul\r\n" +
		"    goto waitloop\r\n" +
		")\r\n" +
		"move /y \"" + exe + "\" \"" + alt + "\" >nul\r\n" +
		"if errorlevel 1 goto alt_starten\r\n" +
		"move /y \"" + neu + "\" \"" + exe + "\" >nul\r\n" +
		"if errorlevel 1 goto zurueck\r\n" +
		"start \"\" \"" + exe + "\"\r\n" +
		"timeout /t 3 /nobreak >nul\r\n" +
		"del \"" + alt + "\" >nul 2>&1\r\n" +
		"goto ende\r\n" +
		":zurueck\r\n" +
		"move /y \"" + alt + "\" \"" + exe + "\" >nul\r\n" +
		"if errorlevel 1 (\r\n" +
		"    start \"\" \"" + alt + "\"\r\n" +
		"    goto ende\r\n" +
		")\r\n" +
		":alt_starten\r\n" +
		"del \"" + neu + "\" >nul 2>&1\r\n" +
		"start \"\" \"" + exe + "\"\r\n" +
		":ende\r\n" +
		"del \"%~f0\"\r\n"
}
