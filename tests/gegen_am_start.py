#!/usr/bin/env python3
"""Gegenproben zu Abschnitt 25 (Start per Tastenkombination + Autostart).

Eine Gegenprobe, die NICHT beisst, ist ein Testmangel – kein Beweis. Jede Probe
dreht GENAU EINE Zusage zurueck und muss den Waechter rot machen.

⚠ GEMESSEN WIRD AM EXIT-CODE UND AN DER BILANZZEILE, nie am Zaehlen von
FAIL-Zeilen: bricht der Waechter ab, gibt es keine Bilanz – und das ist von
„nicht gelaufen" nicht zu unterscheiden.

⚠ JEDE ERSETZUNG HAT EINE TREFFERKONTROLLE. Eine Sabotage, die ihr Ziel
verfehlt, sieht aus wie ein zahnloser Waechter (im Projekt mehrfach passiert).

⚠ DER HARNESS SICHERT JEDE DATEI, DIE EINE PROBE ANFASST – auch die Testdatei
selbst, falls sie einmal saboriert wird. Die Liste wird als REGEL geprueft, nicht
gepflegt: was in PROBEN steht und nicht in DATEIEN, bricht mit Exit 2 ab.
"""
import atexit
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "ai-mouse/src/AiMouse"
WAECHTER = ROOT / "tests/test_ai_mouse.py"
SICHER = Path.home() / ".gegen-am-start"
MARKE = SICHER / "laeuft"

DATEIEN = [
    SRC / "Start/Verknuepfung.cs",
    SRC / "Start/Zweitstart.cs",
    SRC / "Start/Startwege.cs",
    SRC / "Start/HotkeyWort.cs",
    SRC / "Program.cs",
    SRC / "TrayApplicationContext.cs",
    SRC / "Configuration/ConfigStore.cs",
    SRC / "Ui/SettingsWindow.cs",
    SRC / "Localization/Texte.cs",
    SRC / "AiMouse.csproj",
    WAECHTER,
]

# (Beschreibung, Datei, alt, neu)
PROBEN = [
    ("SetHotkey an falscher vtable-Position", SRC / "Start/Verknuepfung.cs",
     "        void GetHotkey();        // 10.\n\n        // 11.\n        void SetHotkey(ushort wHotkey);",
     "        void SetHotkey(ushort wHotkey);\n\n        // 11.\n        void GetHotkey();"),

    ("SetPath nicht an 18. Stelle", SRC / "Start/Verknuepfung.cs",
     "        void Resolve();          // 17.",
     "        void Resolve();          // 17.\n        void Zusatz();           // 17b."),

    ("IPersistFile.Save an falscher Stelle", SRC / "Start/Zweitstart.cs",
     "PLATZHALTER-OHNE-TREFFER", "x"),  # wird unten ersetzt

    ("Verknuepfung landet nicht im Startmenue", SRC / "Start/Verknuepfung.cs",
     "Environment.SpecialFolder.Programs",
     "Environment.SpecialFolder.MyDocuments"),

    ("ohne Hotkey bleibt die alte Verknuepfung liegen", SRC / "Start/Startwege.cs",
     "            return Verknuepfung.Entfernen(pfad);\n        }\n\n        return Verknuepfung.Schreiben(pfad, exe, wort, Beschreibung(marke));",
     "            return null;\n        }\n\n        return Verknuepfung.Schreiben(pfad, exe, wort, Beschreibung(marke));"),

    ("abgeschalteter Autostart wird nicht entfernt", SRC / "Start/Startwege.cs",
     "            : Verknuepfung.Entfernen(pfad);",
     "            : null;"),

    ("die Autostart-Verknuepfung traegt einen Hotkey", SRC / "Start/Startwege.cs",
     "? Verknuepfung.Schreiben(pfad, exe, HotkeyWort.Keiner, Beschreibung(marke))",
     "? Verknuepfung.Schreiben(pfad, exe, (ushort)1601, Beschreibung(marke))"),

    ("nur die erste Fehlermeldung bleibt", SRC / "Start/Startwege.cs",
     'if (f1 is not null && f2 is not null) { return f1 + " / " + f2; }',
     "if (f1 is not null && f2 is not null) { return f1; }"),

    ("der modale Dialog kommt wieder zuerst", SRC / "Program.cs",
     "            if (!Zweitstart.LaufendeInstanzWecken())\n            {",
     "            if (true)\n            {"),

    ("die erste Instanz legt kein Signal an", SRC / "Program.cs",
     "        Zweitstart.AlsErsteInstanz();",
     "        // (kein Signal)"),

    # ⚠ MIT EINRUECKUNG UND KLAMMER: `executeOnlyOnce: false` steht auch im
    #   Docstring, der es begruendet – ein `replace(..., 1)` traf den KOMMENTAR
    #   und liess den Code unberuehrt. Die Probe sah dadurch wie ein zahnloser
    #   Waechter aus, war aber eine verfehlte Sabotage.
    ("der Hotkey wirkt nur einmal", SRC / "Start/Zweitstart.cs",
     "                executeOnlyOnce: false);",
     "                executeOnlyOnce: true);"),

    ("die Reaktion laeuft ohne Marshalling im Pool-Thread",
     SRC / "TrayApplicationContext.cs",
     "Zweitstart.Beobachten(() => BeginInvokeOnOwner(() =>\n            _trayIcon.ShowBalloonTip(4000, Texte.Marke, Texte.LaeuftBereitsBlase,\n                                     ToolTipIcon.Info)));",
     "Zweitstart.Beobachten(() =>\n            _trayIcon.ShowBalloonTip(4000, Texte.Marke, Texte.LaeuftBereitsBlase,\n                                     ToolTipIcon.Info));"),

    ("die Startwege werden beim Speichern nicht nachgezogen",
     SRC / "TrayApplicationContext.cs",
     "        if (Startwege.Anwenden(settings) is { } startFehler)",
     "        if (false && Startwege.Anwenden(settings) is { } startFehler)"),

    ("ein Fehlschlag der Startwege wird verschluckt",
     SRC / "TrayApplicationContext.cs",
     "            ShowTrayError(Texte.StartwegeFehler + startFehler);",
     "            _ = startFehler;"),

    ("StartHotkey wird geschrieben, aber nie gelesen",
     SRC / "Configuration/ConfigStore.cs",
     '            s.StartHotkey = Lies(k, "StartHotkey");',
     "            s.StartHotkey = string.Empty;"),

    ("das Hotkey-Feld wird zum Freitextfeld", SRC / "Ui/SettingsWindow.cs",
     "        ReadOnly = true,\n        TextAlign = HorizontalAlignment.Center,",
     "        TextAlign = HorizontalAlignment.Center,"),

    ("der Tastendruck wird nicht abgefangen (Alt+S loest Speichern aus)",
     SRC / "Ui/SettingsWindow.cs",
     "        e.SuppressKeyPress = true;", "        // (nicht abgefangen)"),

    ("die aufgenommene Kombination wird nicht uebernommen",
     SRC / "Ui/SettingsWindow.cs",
     "            StartHotkey = HotkeyWort.AlsText(_hkModifier, _hkVk),",
     "            StartHotkey = _ausgang.StartHotkey,"),

    ("der Autostart-Schalter wird nicht uebernommen", SRC / "Ui/SettingsWindow.cs",
     "            MitWindowsStarten = _mitWindows.Checked,",
     "            MitWindowsStarten = _ausgang.MitWindowsStarten,"),

    ("die Version wurde nicht hochgezaehlt", SRC / "AiMouse.csproj",
     "<Version>1.0.3</Version>", "<Version>1.0.2</Version>"),

    ("ein i18n-Schluessel fehlt", SRC / "Localization/Texte.cs",
     "    public static string MitWindowsStarten => T(\"Mit Windows starten\",\n                                                \"Start with Windows\");",
     "    public static string MitWindowsStarten => \"Mit Windows starten\";"),
]

# Probe 3 zielt wirklich auf Verknuepfung.cs – oben nur als Platzhalter, damit
# die Reihenfolge der Liste lesbar bleibt.
PROBEN[2] = ("IPersistFile.Save an falscher Stelle", SRC / "Start/Verknuepfung.cs",
             "        void Load();         // 3.",
             "        void Load();         // 3.\n        void Extra();        // 3b.")


def _sichern():
    SICHER.mkdir(parents=True, exist_ok=True)
    for p in DATEIEN:
        (SICHER / p.name).write_bytes(p.read_bytes())
    MARKE.write_text("laeuft", encoding="utf-8")


def _zurueck():
    for p in DATEIEN:
        q = SICHER / p.name
        if q.exists():
            p.write_bytes(q.read_bytes())


def _aufraeumen():
    _zurueck()
    if MARKE.exists():
        MARKE.unlink()


def _lauf():
    r = subprocess.run([sys.executable, str(WAECHTER)],
                       capture_output=True, text=True, timeout=300)
    bilanz = [z for z in r.stdout.split("\n") if " OK, " in z and "FAIL" in z]
    return r.returncode, (bilanz[-1] if bilanz else None)


def main():
    # ⚠ REGEL STATT PFLEGE: jede Datei, die eine Probe anfasst, MUSS gesichert
    #   werden. Ohne diese Schranke bleibt eine Sabotage liegen, und der
    #   naechste Lauf meldet einen Fehler, den es im Code nicht gibt.
    fehlt = {p[1] for p in PROBEN} - set(DATEIEN)
    if fehlt:
        print("ABBRUCH: nicht gesichert: %s" % ", ".join(str(f) for f in fehlt))
        return 2

    # Rueckstand eines abgeschossenen Laufs zuerst zuruecknehmen.
    if MARKE.exists():
        print("⚠ Rueckstand eines frueheren Laufs gefunden – nehme ihn zurueck.")
        _zurueck()
        MARKE.unlink()

    _sichern()
    atexit.register(_aufraeumen)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(1))

    rc, bilanz = _lauf()
    print("Basis: rc=%s  %s" % (rc, bilanz))
    if rc != 0:
        print("ABBRUCH: ohne gruene Basis ist keine Gegenprobe deutbar.")
        return 2

    gut = schlecht = 0
    for name, datei, alt, neu in PROBEN:
        roh = datei.read_text(encoding="utf-8")
        if alt not in roh:
            print("  ⚠ VERFEHLT  %s  (Anker nicht gefunden in %s)" % (name, datei.name))
            schlecht += 1
            continue
        datei.write_text(roh.replace(alt, neu, 1), encoding="utf-8")

        rc, bilanz = _lauf()
        _zurueck()

        if bilanz is None:
            print("  ⚠ OHNE BILANZ  %s  (Waechter abgebrochen, rc=%s)" % (name, rc))
            schlecht += 1
        elif rc != 0:
            print("  beisst      %s  → %s" % (name, bilanz))
            gut += 1
        else:
            print("  ZAHNLOS     %s  → %s" % (name, bilanz))
            schlecht += 1

    print("\n%d von %d Gegenproben beissen." % (gut, len(PROBEN)))
    return 0 if schlecht == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
