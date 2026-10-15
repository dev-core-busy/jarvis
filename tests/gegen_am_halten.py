#!/usr/bin/env python3
"""Gegenproben zu Verweiltimer und Bild-Knopf (2026-09-10).

Ein Waechter, der nicht beisst, ist ein Testmangel - kein Beweis. Gemessen wird
am Exit-Code UND an der Bilanzzeile: ein Lauf ohne Bilanz ist von "nicht
gelaufen" nicht zu unterscheiden.

⚠ Gesichert wird auf PLATTE und ueber atexit/SIGTERM zurueckgestellt - ein per
Timeout abgeschossener Lauf hinterliess sonst den Arbeitsbaum sabotiert
(Register, mehrfach bezahlt).

    python3 tests/gegen_am_halten.py
"""
import atexit
import hashlib
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ABLAGE = pathlib.Path.home() / ".gegen-am-halten"
SRC = "ai-mouse/src/AiMouse"
DATEIEN = [
    f"{SRC}/Input/MouseGestureHook.cs",
    f"{SRC}/Ui/ResultWindow.cs",
    f"{SRC}/Ui/Zwischenablage.cs",
    f"{SRC}/TrayApplicationContext.cs",
    f"{SRC}/Localization/Texte.cs",
]


def md5(p: pathlib.Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def sichern() -> None:
    ABLAGE.mkdir(mode=0o700, exist_ok=True)
    for rel in DATEIEN:
        shutil.copy2(ROOT / rel, ABLAGE / rel.replace("/", "__"))


def zurueck() -> None:
    for rel in DATEIEN:
        q = ABLAGE / rel.replace("/", "__")
        if q.exists():
            shutil.copy2(q, ROOT / rel)


def rueckstand() -> None:
    if not ABLAGE.exists():
        return
    for rel in DATEIEN:
        q = ABLAGE / rel.replace("/", "__")
        if q.exists() and md5(q) != md5(ROOT / rel):
            print(f"  (Rueckstand in {rel} zurueckgenommen)")
            shutil.copy2(q, ROOT / rel)


def lauf(skript: str) -> tuple[int, int, bool]:
    p = subprocess.run([sys.executable, skript], cwd=ROOT, capture_output=True,
                       text=True, timeout=400)
    m = re.search(r"(\d+) OK, (\d+) FAIL", p.stdout)
    if not m:
        return (0, 0, False)
    return (int(m.group(1)), int(m.group(2)), True)


def probe(name: str, rel: str, alt: str, neu: str, skript: str) -> None:
    pfad = ROOT / rel
    txt = pfad.read_text(encoding="utf-8")
    assert alt in txt, f"SABOTAGE VERFEHLT ihr Ziel in {rel}: {alt[:70]!r}"
    pfad.write_text(txt.replace(alt, neu, 1), encoding="utf-8")
    try:
        ok, fail, bilanz = lauf(skript)
        if not bilanz:
            print(f"  ⚠ {name}: ABGEBROCHEN ohne Bilanz")
        else:
            print(f"  {'beisst' if fail else '⚠ BEISST NICHT':14s} {name}: "
                  f"{fail} FAIL ({ok} OK)")
    finally:
        zurueck()


W = "tests/test_ai_mouse.py"
L = "tests/live_gestentaste_dev.py"


def main() -> int:
    rueckstand()
    sichern()
    atexit.register(zurueck)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(1))

    for skript in (W, L):
        ok, fail, bilanz = lauf(skript)
        if not bilanz or fail:
            print(f"BASIS NICHT GRUEN in {skript} ({ok} OK, {fail} FAIL)")
            return 2
        print(f"Basis gruen: {skript} -> {ok} OK")
    print()

    hook = f"{SRC}/Input/MouseGestureHook.cs"

    # ── (1) DER GEMELDETE FEHLER: Abbruch statt Zuruecksetzen ───────────────
    alt_bew = """                        if (_halten.Enabled && SystemWerte.UeberToleranz(_haltenAnker, point))
                        {
                            _haltenAnker = point;
                            _halten.Stop();
                            _halten.Start();
                        }

                        break;"""
    probe("Timer wird abgebrochen statt zurueckgesetzt (der gemeldete Stand)",
          hook, alt_bew,
          """                        if (_halten.Enabled && SystemWerte.UeberToleranz(_start, point))
                        {
                            _halten.Stop();
                        }

                        break;""", W)
    probe("  dasselbe, live gemessen", hook, alt_bew,
          """                        if (_halten.Enabled && SystemWerte.UeberToleranz(_start, point))
                        {
                            _halten.Stop();
                        }

                        break;""", L)

    probe("Anker wird nicht nachgezogen (Uhr laeuft ab der ERSTEN Position)",
          hook, "                            _haltenAnker = point;\n", "", L)
    probe("Anker fehlt beim Druecken", hook,
          "                _start = point;\n                _haltenAnker = point;",
          "                _start = point;", W)
    # ⚠ Die erste Fassung dieser Probe fuegte nur einen Kommentar ein und
    #   liess `_halten.Stop()` stehen - sie hat ihr Ziel verfehlt und sah
    #   dadurch wie ein zahnloser Waechter aus (Register).
    probe("das Lasso beendet das Halten NICHT mehr", hook,
          "                    _isDragging = true;\n\n"
          "                    // ⚠ HIER gehoert der Abbruch hin, und nur hier: ab jetzt ist\n"
          "                    //    es nachweislich ein Rahmen und kein Objektziehen mehr.\n"
          "                    _halten.Stop();\n",
          "                    _isDragging = true;\n", L)
    probe("Ziehbar-Pruefung fragt wieder den Druckpunkt", hook,
          "!pruefer(_haltenAnker)", "!pruefer(_start)", W)

    # ── (2) DER BILD-KNOPF ──────────────────────────────────────────────────
    rw = f"{SRC}/Ui/ResultWindow.cs"
    probe("das Bild wird beim Schliessen nicht freigegeben (Leck)",
          rw, "        _bild?.Dispose();\n        _bild = null;\n", "", W)
    probe("kein Schutz gegen ein schon geschlossenes Fenster",
          rw, "        if (IsDisposed)\n        {\n            bild.Dispose();\n"
              "            return;\n        }\n", "", W)
    probe("ein Fehlschlag beim Kopieren bleibt still",
          rw, "            _header.Text = fehler;\n"
              "            _header.ForeColor = Color.Firebrick;",
          "            _ = fehler;", W)
    probe("der Erfolg wird nicht gemeldet",
          rw, "_header.Text = Texte.BildInZwischenablage;", "_ = _bild;", W)
    probe("der Aufrufer gibt das Bitmap wieder selbst frei",
          f"{SRC}/TrayApplicationContext.cs",
          "            window.BildUebernehmen(capture);\n"
          "            string dataUri = ScreenCapture.ToDataUri(capture);",
          "            string dataUri;\n            using (capture)\n            {\n"
          "                dataUri = ScreenCapture.ToDataUri(capture);\n            }", W)
    probe("zweite SetImage-Fassung im Menue",
          f"{SRC}/TrayApplicationContext.cs",
          "        if (Zwischenablage.BildSetzen(capture) is { } fehler)\n        {\n"
          "            ShowTrayError(fehler);\n        }",
          "        try { Clipboard.SetImage(capture); }\n"
          "        catch (Exception ex) { ShowTrayError(ex.Message); }", W)
    probe("der Textknopf heisst wieder blosss 'Kopieren'",
          f"{SRC}/Localization/Texte.cs",
          'T("Text kopieren", "Copy text")', 'T("Kopieren", "Copy")', W)

    zurueck()
    fehlt = [r for r in DATEIEN if md5(ROOT / r) != md5(ABLAGE / r.replace("/", "__"))]
    print("\nWiederhergestellt: " + ("byte-gleich" if not fehlt
                                     else "⚠ ABWEICHUNG " + str(fehlt)))
    return 1 if fehlt else 0


if __name__ == "__main__":
    sys.exit(main())
