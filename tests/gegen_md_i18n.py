#!/usr/bin/env python3
"""Gegenproben zu Markdown-Parser + i18n (2026-09-10).

Jede Probe dreht GENAU EINEN Teil des Fixes zurueck und misst, ob der Waechter
das meldet. Eine Gegenprobe, die nicht beisst, ist ein Testmangel – kein
Beweis (Register).

⚠ GEMESSEN WIRD AM EXIT-CODE UND AN DER BILANZZEILE, nie am Zaehlen von
   FAIL-Zeilen: bricht der Lauf ab, gibt es keine Bilanz, und das ist von
   "bestanden" nicht zu unterscheiden.

⚠ JEDE ERSETZUNG HAT EINE TREFFERKONTROLLE. Ohne sie sieht eine Sabotage, die
   ihr Ziel verfehlt, wie ein zahnloser Waechter aus (mehrfach bezahlt).

Die Sicherung haengt an `atexit` UND an SIGTERM: ein abgeschossener Lauf
hinterliesse sonst den Arbeitsbaum verbogen.
"""
import atexit
import re
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "ai-mouse" / "src" / "AiMouse"

DATEIEN = {
    "tray": SRC / "TrayApplicationContext.cs",
    "regel": SRC / "Input" / "ZiehbarRegel.cs",
    "pruef": SRC / "Input" / "ZiehbarPruefer.cs",
    "sysw": SRC / "Input" / "SystemWerte.cs",
    "hook": SRC / "Input" / "MouseGestureHook.cs",
    "app": SRC / "Configuration" / "AppSettings.cs",
    "sw": SRC / "Ui" / "SettingsWindow.cs",
    "erg": SRC / "Ui" / "ResultWindow.cs",
    "md": SRC / "Ui" / "Markdown.cs",
    "texte": SRC / "Localization" / "Texte.cs",
    "prompt": SRC / "Configuration" / "PromptItem.cs",
    # ⚠ DER WAECHTER SELBST SCHREIBT DIESE DATEI (er ruft `paket_bauen`, und
    #   das setzt die Hauswerte ein). Ohne sie in der Sicherung bleibt sie nach
    #   30 Laeufen veraendert liegen – am 2026-09-10 genau so passiert, danach
    #   meldete der Waechter 2 FAIL, die kein Codefehler waren.
    "vorgaben": SRC / "Configuration" / "Vorgaben.cs",
}
ORIG = {k: p.read_text(encoding="utf-8") for k, p in DATEIEN.items()}


def zurueck():
    for k, p in DATEIEN.items():
        if p.read_text(encoding="utf-8") != ORIG[k]:
            p.write_text(ORIG[k], encoding="utf-8")


atexit.register(zurueck)
signal.signal(signal.SIGTERM, lambda *_: sys.exit(3))


def waechter():
    """(exit, hat_bilanz, fails) – die Bilanzzeile ist Teil der Aussage."""
    r = subprocess.run([sys.executable, str(ROOT / "tests" / "test_ai_mouse.py")],
                       capture_output=True, text=True, timeout=300)
    m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout)
    return r.returncode, bool(m), int(m.group(2)) if m else -1


def probe(name, schluessel, alt, neu):
    zurueck()
    p = DATEIEN[schluessel]
    s = p.read_text(encoding="utf-8")
    if alt not in s:                       # Trefferkontrolle
        print(f"  ⚠ VERFEHLT  {name}  (Anker nicht gefunden)")
        return False
    p.write_text(s.replace(alt, neu, 1), encoding="utf-8")
    rc, bilanz, fails = waechter()
    zurueck()
    gut = rc != 0 and bilanz and fails > 0
    kennz = "OK  " if gut else "ZAHNLOS"
    print(f"  {kennz}  {name}: {fails} FAIL" + ("" if bilanz else "  (OHNE BILANZ!)"))
    return gut


# ── Basis MUSS gruen sein, sonst ist keine Gegenprobe deutbar ───────────────
rc0, b0, f0 = waechter()
if rc0 != 0 or not b0 or f0 != 0:
    print(f"ABBRUCH: Basislauf nicht gruen (rc={rc0}, bilanz={b0}, fails={f0})")
    sys.exit(2)
print("Basis gruen.\n")

PROBEN = [
    # (a) die gemeldeten Menueeintraege
    ("Menueeintrag wieder hart englisch", "tray",
     "ToolStripMenuItem(Texte.BildKopieren)",
     'ToolStripMenuItem("Copy image to clipboard")'),
    ("Speichern-Eintrag wieder hart", "tray",
     "ToolStripMenuItem(Texte.BildSpeichern)",
     'ToolStripMenuItem("Save image as…")'),
    ("Dateifilter wieder hart", "tray",
     "Filter = Texte.PngFilter", 'Filter = "PNG image|*.png"'),

    # (b) die Marke
    ("Marke wieder abgeschrieben", "tray",
     "ShowBalloonTip(5000, Texte.Marke, message,",
     'ShowBalloonTip(5000, "AI Mouse", message,'),
    ("Marke im Fenstertitel wieder hart", "erg",
     'Text = $"{Texte.Marke} — {title}";', 'Text = $"AI Mouse — {title}";'),
    ("Marke kommt nicht mehr aus den Einstellungen", "texte",
     "string marke = (settings.Marke ?? string.Empty).Trim();",
     "string marke = string.Empty;"),

    # (c) Ergebnisfenster: Texte
    ("Kopieren-Knopf wieder hart", "erg",
     "Text = Texte.Kopieren,", 'Text = "&Copy",'),
    ("Wartetext wieder hart", "erg",
     "Text = Texte.WarteAufModell,", 'Text = "Waiting for the model…",'),

    # (d) der Parser
    ("Parser nicht benutzt (Text direkt gesetzt)", "erg",
     "Markdown.ZuZeilen(text)", "new List<IReadOnlyList<Lauf>>()"),
    ("Fettschrift nicht gesetzt", "erg",
     "_output.SelectionFont = lauf.Fett ? fett : normal;",
     "_output.SelectionFont = normal;"),
    ("Fehlermeldung wird doch gedeutet", "erg",
     "TextSetzen(message, markdown: false);", "TextSetzen(message, markdown: true);"),
    ("Handle wird erzwungen", "erg",
     "bool redraw = _output.IsHandleCreated;", "bool redraw = true;"),
    ("Zeichenzahl zaehlt wieder den Rohtext", "erg",
     "Texte.Zeichen(_output.TextLength)", "Texte.Zeichen(answer.Length)"),

    # (e) DRIFT: die Regel weicht vom Plugin ab
    ("Regel ohne die \\S-Waechter (Drift zum Plugin)", "md",
     r'@"\*\*(?=\S)([^\n]+?)(?<=\S)\*\*"', r'@"\*\*([^\n]+?)\*\*"'),
    ("Parser zieht WinForms herein (nicht mehr messbar)", "md",
     "namespace AiMouse.Ui;",
     "using System.Windows.Forms;\n\nnamespace AiMouse.Ui;"),

    # (f) die eingebauten Fragen
    ("Defaults wieder einmaliger Initialisierer", "prompt",
     "public static IReadOnlyList<PromptItem> Defaults =>",
     "public static IReadOnlyList<PromptItem> Defaults { get; } ="),
    ("Fragentitel wieder hart englisch", "prompt",
     "Title = Texte.FrageOcr,", 'Title = "Extract Text (OCR)",'),

    # ── Halten -> Rechtsziehen (2026-09-10) ────────────────────────────────
    ("vtable-Position von ElementFromPoint verschoben", "pruef",
     "        void ElementFromHandle();\n\n        // 5.",
     "        // 5.-VERSCHOBEN"),
    # ⚠ GEZIELT AUF DAS ATTRIBUT: die GUID steht auch im erklaerenden Kopf,
    #   und eine Ersetzung des ERSTEN Vorkommens traf nur den Kommentar – die
    #   Probe sah dadurch zahnlos aus, ohne es zu sein.
    ("falsche GUID fuer IUIAutomation", "pruef",
     '[ComImport, Guid("30cbe57d-d9d0-452a-ab13-7ac5ac4825ee"),',
     '[ComImport, Guid("30cbe57d-d9d0-452a-ab13-7ac5ac4825ef"),'),
    # ⚠ ECHTER CODE, KEIN KOMMENTAR: der Waechter arbeitet auf der
    #   kommentarfreien Fassung – ein `// ComImport` waere dort gar nicht mehr da.
    ("Entscheidung nicht mehr COM-frei", "regel",
     "internal static class ZiehbarRegel\n{",
     "internal static class ZiehbarRegel\n{\n    [System.Runtime.InteropServices.ComImport]\n    private class X { }\n"),
    # ⚠ „Custom ohne Beleg" wird NICHT hier gemessen, sondern in
    #   `tests/live_ziehbar_dev.py` – dort laeuft die Regel WIRKLICH gegen die
    #   Faelle. Eine Quelltext-Sabotage waere hier folgerichtig zahnlos; die
    #   Gegenprobe gehoert an den Ort der Messung, nicht an diesen.
    ("Fehler ergibt ZIEHBAR statt nicht", "pruef",
     "                ergebnis = false;\n            }", "                ergebnis = true;\n            }"),
    ("Abfrage ohne Zeitgrenze", "pruef",
     "return t.Join(grenze) && ergebnis;", "t.Join(); return ergebnis;"),
    ("Verweilzeit ungeprueft uebernommen", "sysw",
     "return (int)Math.Clamp(wert, VerweilMin, VerweilMax);", "return (int)wert;"),
    ("Toleranz 0 wird uebernommen", "sysw",
     "return (x > 0 ? x : 4, y > 0 ? y : 4);", "return (x, y);"),
    ("Zustand beim Ablauf NICHT erneut geprueft", "hook",
     "if (!_pressWithheld || _isDragging || _durchgereicht)", "if (false)"),
    ("erst injizieren, dann Zustand umstellen", "hook",
     "        _pressWithheld = false;\n        _durchgereicht = true;\n\n        if (InputReplay.SendRightDown() is { } fehler)",
     "        if (InputReplay.SendRightDown() is { } fehler)"),
    ("Bewegung stoppt den Halte-Timer nicht", "hook",
     "if (_halten.Enabled && SystemWerte.UeberToleranz(_start, point))", "if (false)"),
    ("gescheiterte Injektion bleibt still", "hook",
     "            Post(() => ReplayFailed?.Invoke(fehler));\n            return;", "            return;"),
    ("Timer nicht beim Aufraeumen gestoppt", "hook",
     "        _halten.Stop();\n        _halten.Dispose();", "        "),

    # ── Geste nur mit Sondertaste (2026-09-10) ─────────────────────────────
    ("Gestentaste-Vorgabe nicht mehr leer", "app",
     'GestureKey { get; set; } = string.Empty;', 'GestureKey { get; set; } = "ctrl";'),
    ("Hook prueft die Gestentaste nicht", "hook",
     "if (GesteVerlangt != GestenTaste.Keine && !TasteGehalten(GesteVerlangt))", "if (false)"),
    ("Gestentaste erst NACH der Durchreich-Taste", "hook",
     "                if (GesteVerlangt != GestenTaste.Keine && !TasteGehalten(GesteVerlangt))\n                {\n                    _pressWithheld = false;\n                    break;\n                }\n\n",
     ""),
    ("Konstruktor geht an der Aufloesung vorbei", "tray",
     "            GesteVerlangt = _g0,\n            Durchreichen = _d0,",
     "            Durchreichen = GestenTasteAus(_settings.RightDragKey),"),
    # ⚠ „Aufloesung laesst Durchreichen stehen" wird NICHT hier gemessen,
    #   sondern in `tests/gegen_tastenaus_dev.py` – dort laeuft `TastenAus`
    #   WIRKLICH. Eine Quelltext-Sabotage waere hier folgerichtig zahnlos; die
    #   Gegenprobe gehoert an den Ort der Messung, nicht an diesen.
    ("Gestentaste faellt auf Strg statt Keine", "tray",
     "GestenTasteAus(s.GestureKey, GestenTaste.Keine)", "GestenTasteAus(s.GestureKey)"),
    ("Dialog sperrt die Durchreich-Taste nicht", "sw",
     "_rightDrag.Enabled = !mitGeste;", "_rightDrag.Enabled = true;"),
    ("Sperre ohne Begruendung", "sw",
     "_rdHinweis.Text = mitGeste ? Texte.RdGesperrt : string.Empty;",
     "_rdHinweis.Text = string.Empty;"),
    ("Sperre folgt der Auswahl nicht sofort", "sw",
     "_gesteTaste.SelectedIndexChanged += (_, _) => TastenfelderAbgleichen();", ""),
    ("Gestentaste wird nicht gespeichert", "sw",
     "            GestureKey = _RD_WERTE[Math.Clamp(_gesteTaste.SelectedIndex, 0, _RD_WERTE.Length - 1)],", ""),

    # (g) ein NEUER harter Text – faengt die Regel auch den naechsten Fall?
    ("ein neu hinzugefuegter harter UI-Text", "tray",
     "var settingsItem = new ToolStripMenuItem(Texte.Einstellungen);",
     'var settingsItem = new ToolStripMenuItem("Preferences…");'),
]

gut = sum(probe(*p) for p in PROBEN)
print(f"\n{gut} von {len(PROBEN)} Gegenproben beissen einzeln.")

# Und der komplette Altstand.
zurueck()
sys.exit(0 if gut == len(PROBEN) else 1)
