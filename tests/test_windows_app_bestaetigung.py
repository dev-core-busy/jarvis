#!/usr/bin/env python3
"""Waechter: Bestaetigungsdialog der Windows-App (BSI H9 / Pentest C1, 2026-11-08).

Seit C1 brauchen Shell-Befehl, Programmstart und Tippen eine Freigabe durch den
Menschen. Die App zeigt dafuer einen nativen Dialog und antwortet dem Server –
dasselbe Protokoll wie die Bestaetigungskarte im Browser.

  [1] ``windows-app-go/bestaetigung.go`` AUSGEFUEHRT (``go test`` in einem
      Wegwerf-Modul): Dekodieren (nur mit Kennung, kaputte Argumente einzeln
      uebersprungen, fremde Nachrichtentypen nicht), Dialogtext nennt JEDES
      Argument, Steuer-/Richtungszeichen werden sichtbar ersetzt, Laenge ist
      gedeckelt, Frist liegt vor der Serverfrist.
  [2] REGELN an der Verdrahtung: Auftraege melden ``bestaetigung`` aus
      ``KannBestaetigen()``; die Empfangsschleife faengt die Anfrage VOR dem
      Dekodieren in WSMessage ab; ohne Rueckruf wird ABGELEHNT; ausserhalb von
      Windows meldet die App keine Faehigkeit und lehnt ab; der Windows-Dialog
      hat "Nein" als Vorgabe und zaehlt nur "Ja" als Freigabe.
Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "windows-app-go"
OK = FAIL = 0


def check(name, bed, detail=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  -> " + detail) if detail else ""))


def abbruch(grund):
    print("ABBRUCH: " + grund)
    sys.exit(2)


for f in ("bestaetigung.go", "bestaetigung_windows.go", "bestaetigung_stub.go",
          "ws_client.go", "main.go"):
    if not (APP / f).exists():
        abbruch("windows-app-go/%s fehlt" % f)
GO = shutil.which("go")
if not GO:
    abbruch("Go-Werkzeug nicht gefunden – [1] nicht ausfuehrbar")


def ohne_kommentare(text: str) -> str:
    """Go-Kommentare durch Leerzeichen ersetzen (Zeichenpositionen bleiben)."""
    text = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)
    return re.sub(r"//[^\n]*", lambda m: " " * len(m.group(0)), text)


# ── [1] Logik ausfuehren ──────────────────────────────────────────────────
print("\n[1] bestaetigung.go (go test)")
GO_TEST = r'''
package main

import (
	"strings"
	"testing"
	"time"
)

func TestPositivkontrolle(t *testing.T) {
	a, ok := parseBestaetigung([]byte(`{"type":"bestaetigung_anfrage","id":"k1","werkzeug":"windows_desktop","klasse":"shell","argumente":[["action","shell_exec"],["cmd","notepad.exe"]],"frist_s":120}`))
	if !ok || a.ID != "k1" || len(a.Argumente) != 2 || a.argument("cmd") != "notepad.exe" {
		t.Fatalf("POSITIVKONTROLLE: gueltige Anfrage nicht gelesen: %+v %v", a, ok)
	}
}

func TestOhneKennung(t *testing.T) {
	if _, ok := parseBestaetigung([]byte(`{"type":"bestaetigung_anfrage","id":"  ","werkzeug":"x"}`)); ok {
		t.Fatal("Anfrage ohne Kennung angenommen")
	}
}

func TestFremderTyp(t *testing.T) {
	if _, ok := parseBestaetigung([]byte(`{"type":"status","id":"k1"}`)); ok {
		t.Fatal("fremder Nachrichtentyp als Anfrage gelesen")
	}
}

func TestKaputteArgumente(t *testing.T) {
	a, ok := parseBestaetigung([]byte(`{"type":"bestaetigung_anfrage","id":"k2","argumente":[["action","shell_exec"],42,["nur_eins"],["cmd","dir"]]}`))
	if !ok || len(a.Argumente) != 2 || a.argument("cmd") != "dir" {
		t.Fatalf("kaputte Argumente nicht einzeln uebersprungen: %+v %v", a, ok)
	}
}

func TestTextNenntAlles(t *testing.T) {
	a := Bestaetigungsanfrage{ID: "k", Werkzeug: "windows_desktop",
		Argumente: [][2]string{{"action", "shell_exec"}, {"cmd", "del /q C:\\x"}, {"cwd", "C:\\temp"}}}
	s := bestaetigungsText(a)
	for _, muss := range []string{"del /q C:\\x", "C:\\temp", "cwd", "Befehl"} {
		if !strings.Contains(s, muss) {
			t.Errorf("Dialogtext nennt %q nicht: %s", muss, s)
		}
	}
}

func TestSteuerzeichenSichtbar(t *testing.T) {
	a := Bestaetigungsanfrage{ID: "k", Werkzeug: "windows_desktop",
		Argumente: [][2]string{{"action", "shell_exec"}, {"cmd", "echo a\u202egnp.exe\x1b[2J"}}}
	s := bestaetigungsText(a)
	if strings.ContainsRune(s, '\u202e') || strings.ContainsRune(s, '\x1b') {
		t.Errorf("Richtungs-/Steuerzeichen unsichtbar im Dialog: %q", s)
	}
	if !strings.ContainsRune(s, '\uFFFD') {
		t.Errorf("ersetztes Zeichen nicht sichtbar markiert: %q", s)
	}
}

func TestLaengeGedeckelt(t *testing.T) {
	a := Bestaetigungsanfrage{ID: "k", Werkzeug: "windows_desktop",
		Argumente: [][2]string{{"action", "type_text"}, {"text", strings.Repeat("x", 50000)}}}
	s := bestaetigungsText(a)
	if n := len([]rune(s)); n > bestaetigungTextMax+1 {
		t.Errorf("Dialogtext zu lang: %d Zeichen", n)
	}
	if !strings.Contains(s, "gek") && !strings.Contains(s, "trunc") {
		t.Errorf("Kuerzung nicht benannt")
	}
}

func TestFrist(t *testing.T) {
	if d := dialogFrist(120); d >= 120*time.Second || d < 100*time.Second {
		t.Errorf("Dialog-Frist liegt nicht knapp vor der Serverfrist: %v", d)
	}
	if d := dialogFrist(0); d <= 0 {
		t.Errorf("ohne Frist kein gueltiger Wert: %v", d)
	}
	if d := dialogFrist(3); d < 10*time.Second {
		t.Errorf("Untergrenze fehlt: %v", d)
	}
}
'''
with tempfile.TemporaryDirectory(prefix="winapp_best_") as tmp:
    t = Path(tmp)
    shutil.copy(APP / "bestaetigung.go", t / "bestaetigung.go")
    shutil.copy(APP / "i18n.go", t / "i18n.go")
    (t / "go.mod").write_text("module probe\n\ngo 1.21\n", encoding="utf-8")
    (t / "probe_test.go").write_text(GO_TEST, encoding="utf-8")
    r = subprocess.run([GO, "test", "-count=1", "-v", "./..."], cwd=tmp, capture_output=True,
                       text=True, timeout=300, env={**__import__("os").environ,
                                                    "GOFLAGS": "-mod=mod", "CGO_ENABLED": "0"})
    aus = r.stdout + r.stderr
    if "TestPositivkontrolle" not in aus or "build failed" in aus or "cannot" in aus and r.returncode:
        print(aus[-1500:])
        abbruch("go test nicht lauffaehig (Modul baut nicht) – [1] nicht deutbar")
    if "--- FAIL: TestPositivkontrolle" in aus:
        print(aus[-1500:])
        abbruch("Positivkontrolle gescheitert – Folgepruefungen nicht deutbar")
    for name in ("TestOhneKennung", "TestFremderTyp", "TestKaputteArgumente", "TestTextNenntAlles",
                 "TestSteuerzeichenSichtbar", "TestLaengeGedeckelt", "TestFrist"):
        check(name, ("--- PASS: " + name) in aus, re.findall(r"probe_test\.go:\d+: [^\n]*", aus)[:2]
              and "; ".join(re.findall(r"probe_test\.go:\d+: [^\n]*", aus)[:2]) or "")

# ── [2] Verdrahtung ───────────────────────────────────────────────────────
print("\n[2] Verdrahtung")
ws = ohne_kommentare((APP / "ws_client.go").read_text(encoding="utf-8"))
mn = ohne_kommentare((APP / "main.go").read_text(encoding="utf-8"))
win = ohne_kommentare((APP / "bestaetigung_windows.go").read_text(encoding="utf-8"))
stub = ohne_kommentare((APP / "bestaetigung_stub.go").read_text(encoding="utf-8"))


def funktion(text, kopf):
    i = text.find(kopf)
    if i < 0:
        return ""
    j = text.find("\nfunc ", i + 1)
    return text[i:j if j > 0 else len(text)]


for f in ("func (c *WSClient) SendTask(", "func (c *WSClient) SendTaskWithTruncate("):
    rumpf = funktion(ws, f)
    check("%s meldet bestaetigung aus KannBestaetigen()" % f.split(")")[1].strip(" ("),
          bool(re.search(r'"bestaetigung"\s*:\s*KannBestaetigen\(\)', rumpf)), rumpf[:80])
lese = funktion(ws, "func (c *WSClient) runConn(")
if not lese:
    abbruch("Empfangsschleife runConn nicht gefunden – Reihenfolge nicht pruefbar")
i_parse = lese.find("parseBestaetigung(")
i_wsmsg = lese.find("var msg WSMessage")
check("(Positivkontrolle) Empfangsschleife dekodiert WSMessage", i_wsmsg >= 0)
check("Anfrage wird VOR WSMessage abgefangen", 0 <= i_parse < i_wsmsg, "%d/%d" % (i_parse, i_wsmsg))
block = lese[i_parse:i_wsmsg] if 0 <= i_parse < i_wsmsg else ""
check("ohne Rueckruf wird abgelehnt (SendBestaetigungAntwort(…, false))",
      bool(re.search(r"SendBestaetigungAntwort\(\s*anfrage\.ID\s*,\s*false\s*\)", block)), block[:200])
check("die Antwort traegt Typ, Kennung und erlaubt",
      all(s in funktion(ws, "func (c *WSClient) SendBestaetigungAntwort(")
          for s in ('"bestaetigung_antwort"', '"id"', '"erlaubt"', '"token"')))
check("main.go verdrahtet OnBestaetigung mit Dialog und Antwort",
      bool(re.search(r"OnBestaetigung\s*=\s*func", mn)) and "ZeigeBestaetigung(" in mn
      and "SendBestaetigungAntwort(a.ID, erlaubt)" in mn)
check("ausserhalb Windows: keine Faehigkeit gemeldet",
      bool(re.search(r"func KannBestaetigen\(\) bool\s*\{\s*return false\s*\}", stub)))
check("ausserhalb Windows: Dialog lehnt ab",
      bool(re.search(r"func ZeigeBestaetigung\([^)]*\) bool\s*\{\s*return false\s*\}", stub)))
check("Windows-Dialog: Vorgabe-Knopf ist 'Nein' (MB_DEFBUTTON2 im Stil)",
      "mbDefButton2" in win and bool(re.search(r"stil\s*:=.*mbDefButton2", win)))
check("Windows-Dialog: nur 'Ja' gilt als Freigabe", bool(re.search(r"return r == idYes", win)))
check("Windows: kein MustFindProc fuer den Dialog (fehlender Export beendet die App nicht)",
      "MustFindProc(\"MessageBox" not in win)

print("\nErgebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
