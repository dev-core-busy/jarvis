package main

// Bestaetigung wirksamer Aktionen in der Windows-App (BSI H9, Pentest C1).
//
// WARUM: seit dem Pentest-Fix C1 brauchen Shell-Befehl, Programmstart und
// Tippen auf dem eigenen PC eine Freigabe durch den Menschen. Der Server kennt
// dafuer EIN Protokoll fuer alle Oberflaechen: er schickt
// ``bestaetigung_anfrage`` an den Client, von dem der Auftrag kam, und wartet
// auf ``bestaetigung_antwort`` mit derselben ``id``. Ein Client meldet mit
// ``"bestaetigung": true`` im Auftrag, dass er so einen Dialog zeigen kann –
// ohne dieses Feld weist der Server die Aktion ab ("Client ohne Dialog").
//
// Diese Datei ist bewusst frei von fyne und Win32: sie enthaelt nur das, was
// sich ohne Fenster pruefen laesst (Dekodieren, Dialogtext, Frist). Der Dialog
// selbst steht in winapi_windows.go (MessageBoxTimeoutW), der Rueckfall fuer
// andere Plattformen in winapi_stub.go – dort meldet die App gar nicht erst,
// dass sie bestaetigen kann.
//
// Waechter: tests/test_windows_app_bestaetigung.py.

import (
	"encoding/json"
	"strings"
	"time"
)

// Bestaetigungsanfrage ist eine “bestaetigung_anfrage“ des Servers.
type Bestaetigungsanfrage struct {
	ID        string
	Werkzeug  string
	Klasse    string
	Argumente [][2]string // [[name, wert], …] in Aufrufreihenfolge
	FristS    int
}

// Obergrenzen fuer den Dialogtext: ein Meldungsfenster waechst sonst ueber den
// Bildschirm hinaus, und die Knoepfe waeren nicht mehr erreichbar.
const (
	bestaetigungWertMax = 400
	bestaetigungTextMax = 1800
)

// parseBestaetigung liest eine Server-Nachricht. “ok“ ist nur wahr, wenn es
// eine Bestaetigungsanfrage MIT Kennung ist – ohne Kennung koennte keine
// Antwort zugeordnet werden. Argumente, die nicht die erwartete Form haben,
// werden einzeln uebersprungen statt die ganze Anfrage zu verwerfen: eine
// verworfene Anfrage liefe beim Server in die Frist, der Benutzer saehe nichts.
func parseBestaetigung(data []byte) (Bestaetigungsanfrage, bool) {
	var roh struct {
		Type      string            `json:"type"`
		ID        string            `json:"id"`
		Werkzeug  string            `json:"werkzeug"`
		Klasse    string            `json:"klasse"`
		Argumente []json.RawMessage `json:"argumente"`
		FristS    int               `json:"frist_s"`
	}
	if err := json.Unmarshal(data, &roh); err != nil {
		return Bestaetigungsanfrage{}, false
	}
	if roh.Type != "bestaetigung_anfrage" || strings.TrimSpace(roh.ID) == "" {
		return Bestaetigungsanfrage{}, false
	}
	a := Bestaetigungsanfrage{ID: roh.ID, Werkzeug: roh.Werkzeug, Klasse: roh.Klasse,
		FristS: roh.FristS}
	for _, r := range roh.Argumente {
		var paar []string
		if json.Unmarshal(r, &paar) != nil || len(paar) != 2 {
			continue
		}
		a.Argumente = append(a.Argumente, [2]string{paar[0], paar[1]})
	}
	return a, true
}

// argument liefert den Wert eines benannten Arguments ("" wenn nicht vorhanden).
func (a Bestaetigungsanfrage) argument(name string) string {
	for _, p := range a.Argumente {
		if p[0] == name {
			return p[1]
		}
	}
	return ""
}

// lesbar ersetzt Steuerzeichen (ausser Zeilenumbruch und Tab) und kuerzt. Ein
// Steuerzeichen im Befehl koennte sonst im Dialog unsichtbar sein – der Mensch
// gaebe etwas frei, das er nicht gesehen hat. Der Kuerzungshinweis steht VORN,
// damit ihn keine weitere Kappung abschneidet.
func lesbar(s string, max int) string {
	var b strings.Builder
	for _, r := range s {
		if r == '\n' || r == '\t' || r >= 0x20 && r != 0x7f && !(r >= 0x80 && r < 0xa0) &&
			r != 0x200b && r != 0x202e && r != 0x2066 && r != 0x2067 && r != 0x2068 && r != 0x2069 {
			b.WriteRune(r)
		} else {
			b.WriteRune('\uFFFD')
		}
	}
	out := []rune(b.String())
	if len(out) > max {
		return t("[gekürzt] ", "[truncated] ") + string(out[:max]) + "…"
	}
	return string(out)
}

// bestaetigungsTitel ist die Fensterueberschrift.
func bestaetigungsTitel() string {
	return t("Jarvis bittet um Bestätigung", "Jarvis asks for confirmation")
}

// bestaetigungsKopf nennt in einem Satz, WAS geschehen soll.
func bestaetigungsKopf(a Bestaetigungsanfrage) string {
	aktion := a.argument("action")
	switch {
	case a.Werkzeug == "windows_desktop" && aktion == "shell_exec":
		return t("Jarvis möchte auf diesem PC einen Befehl ausführen:",
			"Jarvis wants to run a command on this PC:")
	case a.Werkzeug == "windows_desktop" && aktion == "open_app":
		return t("Jarvis möchte auf diesem PC ein Programm starten:",
			"Jarvis wants to start a program on this PC:")
	case a.Werkzeug == "windows_desktop" && aktion == "type_text":
		return t("Jarvis möchte auf diesem PC Text eintippen:",
			"Jarvis wants to type text on this PC:")
	}
	return t("Jarvis möchte folgende Aktion ausführen: ",
		"Jarvis wants to perform the following action: ") + lesbar(a.Werkzeug, 80)
}

// bestaetigungsText ist der vollstaendige Dialogtext: Kopf, JEDES Argument mit
// Namen und Wert, Hinweis. Alle Argumente – nicht nur der Befehl –, damit der
// Mensch genau das sieht, was ausgefuehrt wird.
func bestaetigungsText(a Bestaetigungsanfrage) string {
	var b strings.Builder
	b.WriteString(bestaetigungsKopf(a))
	b.WriteString("\n\n")
	if len(a.Argumente) == 0 {
		b.WriteString(t("(keine Angaben)", "(no details)"))
		b.WriteString("\n")
	}
	for _, p := range a.Argumente {
		b.WriteString(lesbar(p[0], 60))
		b.WriteString(": ")
		b.WriteString(lesbar(p[1], bestaetigungWertMax))
		b.WriteString("\n")
	}
	b.WriteString("\n")
	b.WriteString(t("Nur zulassen, wenn Sie diesen Auftrag selbst gegeben haben.\n"+
		"Ja = ausführen, Nein = ablehnen.",
		"Only allow if you gave this instruction yourself.\n"+
			"Yes = run, No = decline."))
	text := []rune(b.String())
	if len(text) > bestaetigungTextMax {
		return string(text[:bestaetigungTextMax]) + "…"
	}
	return string(text)
}

// dialogFrist: der Dialog schliesst sich kurz VOR der Frist des Servers (dann
// gilt er als abgelehnt). Ein Dialog, der nach der Frist noch offen steht, waere
// eine Frage, deren Antwort niemand mehr annimmt.
func dialogFrist(fristS int) time.Duration {
	if fristS <= 0 {
		fristS = 120
	}
	d := time.Duration(fristS-5) * time.Second
	if d < 10*time.Second {
		d = 10 * time.Second
	}
	return d
}
