#!/usr/bin/env python3
"""Gegenproben zu `bild_text_ersetzen`. Jede Sabotage muss EINZELN beissen."""
import atexit, re, shutil, signal, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ABL = Path.home() / ".gegen-bildtext"
MARKE = ABL / ".laeuft"
DATEIEN = ["backend/tools/bild_text.py", "backend/agent.py",
           "backend/werkzeug_buendel.py", "tests/test_bild_text.py"]
WAECHTER = "tests/test_bild_text.py"


def sichern():
    ABL.mkdir(mode=0o700, exist_ok=True)
    for r in DATEIEN:
        shutil.copy2(ROOT / r, ABL / r.replace("/", "__"))
    MARKE.write_text("1")


def zurueck():
    for r in DATEIEN:
        z = ABL / r.replace("/", "__")
        if z.exists():
            shutil.copy2(z, ROOT / r)
    if MARKE.exists():
        MARKE.unlink()


def lauf():
    r = subprocess.run([sys.executable, str(ROOT / WAECHTER)],
                       capture_output=True, text=True, timeout=400)
    m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout + r.stderr)
    return (int(m.group(2)) if m else None), (r.stdout + r.stderr)


def patch(rel, alt, neu):
    p = ROOT / rel; s = p.read_text(encoding="utf-8")
    assert s.count(alt) >= 1, f"ANKER VERFEHLT in {rel}: {alt[:60]!r}"
    p.write_text(s.replace(alt, neu, 1), encoding="utf-8")


PROBEN = [
 ("Luecken-Trennung ausgebaut", lambda: patch("backend/tools/bild_text.py",
   "        roh.extend(_nach_luecken_trennen(ws))", "        roh.append(ws)")),
 ("Luecken-Trennung auch bei mehrzeilig", lambda: patch("backend/tools/bild_text.py",
   '    if len({w["line"] for w in ws}) != 1 or len(ws) < 2:', "    if len(ws) < 2:")),
 ("Grundfarbe geraten statt gemessen", lambda: patch("backend/tools/bild_text.py",
   "    grund = Counter(ring).most_common(1)[0][0] if ring else (255, 255, 255)",
   "    grund = (255, 255, 255)")),
 ("Schrift wird nicht verkleinert", lambda: patch("backend/tools/bild_text.py",
   "    for groesse in range(start, 6, -1):", "    for groesse in range(start, start - 1, -1):")),
 ("pfad_parameter entfernt", lambda: patch("backend/tools/bild_text.py",
   '    pfad_parameter = ("pfad",)', "    pfad_parameter = ()")),
 ("Werkzeug nicht angehaengt", lambda: patch("backend/agent.py",
   "            self._tool_instances.append(BildTextErsetzenTool())", "            pass")),
 ("nicht im Buendel 'bild'", lambda: patch("backend/werkzeug_buendel.py",
   '"screenshot", "bild_text_ersetzen",', '"screenshot",')),
 ("Flexion zurueckgedreht", lambda: patch("backend/werkzeug_buendel.py",
   r'\bbild(er|es|ern|e)?\b', r'\bbild\b')),
 # ⚠ Der Name steht ZWEIMAL in der Prompt-Regel - eine Sabotage, die nur den
 # Satzanfang trifft, laesst die zweite Stelle stehen und sieht wie ein
 # zahnloser Waechter aus. Die GANZE Regel muss weg.
 ("Prompt nennt das Werkzeug nicht", lambda: patch("backend/agent.py",
   "    - TEXT IN EINEM VORHANDENEN BILD ERSETZEN -> `bild_text_ersetzen`, NIEMALS `generate_image`. ",
   "    - Zu Bildern siehe oben. ")),
 ("Beschreibung grenzt nicht ab", lambda: patch("backend/tools/bild_text.py",
   '"NICHT generate_image dafuer verwenden - das erzeugt ein NEUES Bild aus einer "',
   '"Hinweis. "')),
]


def main():
    fehlend = {r for _, r in [(n, "backend/tools/bild_text.py") for n, _ in PROBEN]} - set(DATEIEN)
    if MARKE.exists():
        print("Rueckstand gefunden - stelle zurueck."); zurueck()
    sichern()
    atexit.register(zurueck)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: sys.exit(1))

    basis, aus = lauf()
    if basis is None:
        print("ABBRUCH: Basislauf ohne Bilanz\n" + aus[-1200:]); return 2
    if basis != 0:
        print(f"ABBRUCH: Basis nicht gruen ({basis} FAIL)"); return 2
    print("Basis gruen.\n")

    schlecht = []
    for name, tun in PROBEN:
        zurueck()
        try:
            tun()
        except AssertionError as e:
            print(f"  ✗ {name:38s} {e}"); schlecht.append(name); continue
        f, _ = lauf()
        if f is None:
            print(f"  ✗ {name:38s} kein Ergebnis (Lauf abgebrochen)"); schlecht.append(name)
        elif f == 0:
            print(f"  ✗ {name:38s} BEISST NICHT"); schlecht.append(name)
        else:
            print(f"  ✓ {name:38s} {f} FAIL")

    zurueck()
    nach, _ = lauf()
    print(f"\nnach dem Zurueckstellen: {nach} FAIL ({'ok' if nach == 0 else 'RUECKSTAND!'})")
    print(f"{len(PROBEN) - len(schlecht)}/{len(PROBEN)} beissen")
    return 1 if schlecht else 0


if __name__ == "__main__":
    sys.exit(main())
