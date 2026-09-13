#!/usr/bin/env python3
"""Gegenproben zum Ziehgriff der Verlaufsleiste.

Jede Probe dreht GENAU EINE Zusage zurueck und verlangt, dass der Waechter
das meldet. Eine Probe, die nicht beisst, ist ein TESTMANGEL – kein Beweis,
dass der Code richtig ist.

⚠ DIE SICHERUNG DECKT JEDE DATEI AB, DIE EINE PROBE ANFASST – auch die
  Testdatei selbst (Register: ein Harness, der seine eigene Sabotage nicht
  zuruecknimmt, laesst den naechsten Lauf einen Fehler melden, den es nicht
  gibt). Die Laufmarke faengt den Fall `kill -9` ab: nur DANN soll ein
  spaeterer Start zuruecknehmen, sonst macht er fertige Arbeit zunichte.

Aufruf: python3 tests/gegen_cs_resize.py
"""
import atexit
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ABLAGE = Path.home() / ".gegen-cs-resize"
MARKE = ABLAGE / "laeuft"

WAECHTER = ["node", str(ROOT / "tests" / "test_cs_resize_ui.js")]

DATEIEN = [
    "frontend/css/chat.css",
    "frontend/chat.html",
    "frontend/js/chat.js",
    "frontend/js/i18n.js",
    "tests/test_cs_resize_ui.js",
]


def sichern():
    ABLAGE.mkdir(mode=0o700, exist_ok=True)
    for rel in DATEIEN:
        ziel = ABLAGE / rel.replace("/", "__")
        shutil.copy2(ROOT / rel, ziel)
    MARKE.write_text("1", encoding="utf-8")


def zurueck():
    for rel in DATEIEN:
        q = ABLAGE / rel.replace("/", "__")
        if q.exists():
            shutil.copy2(q, ROOT / rel)


def ende():
    zurueck()
    MARKE.unlink(missing_ok=True)


# Rueckstand eines abgeschossenen Laufs zuerst zuruecknehmen.
if MARKE.exists():
    print("! Rueckstand eines abgebrochenen Laufs gefunden – nehme ihn zurueck.")
    zurueck()
    MARKE.unlink(missing_ok=True)


def lauf():
    p = subprocess.run(WAECHTER, capture_output=True, text=True, cwd=str(ROOT))
    zeilen = [z for z in p.stdout.splitlines() if z.strip().startswith("FAIL")]
    bilanz = [z for z in p.stdout.splitlines() if z.startswith("Ergebnis:")]
    return p.returncode, len(zeilen), bool(bilanz), p.stdout


def patch(rel, alt, neu, anzahl=1):
    p = ROOT / rel
    s = p.read_text(encoding="utf-8")
    # ⚠ TREFFERKONTROLLE: eine Ersetzung ohne assert ist kein Messwert – sie
    # sieht wie ein zahnloser Waechter aus, obwohl sie gar nicht gegriffen hat.
    assert s.count(alt) >= anzahl, f"Anker nicht gefunden in {rel}: {alt[:70]!r}"
    p.write_text(s.replace(alt, neu, anzahl), encoding="utf-8")


PROBEN = [
    ("Leiste liest wieder eine feste Breite (das Einklappen braeche)",
     lambda: patch("frontend/css/chat.css",
                   "    flex: 0 0 var(--cs-w);\n    width: var(--cs-w);",
                   "    flex: 0 0 240px;\n    width: 240px;")),

    ("JS schreibt inline auf die LEISTE statt auf den Screen",
     lambda: patch("frontend/js/chat.js",
                   "screen.style.setProperty('--cs-w', w + 'px');",
                   "document.getElementById('chat-sidebar').style.width = w + 'px';")),

    ("Einklapp-Regel setzt die Breite nicht mehr auf 0",
     lambda: patch("frontend/css/chat.css",
                   "    flex-basis: 0; width: 0; padding-left: 0; padding-right: 0;",
                   "    padding-left: 0; padding-right: 0;")),

    ("Griff wird Kind der Leiste (scrollte mit)",
     lambda: patch("frontend/chat.html",
                   '    </aside>\n    <!-- Ziehgriff',
                   '    XXASIDEXX\n    <!-- Ziehgriff')),

    ("touch-action fehlt (Touch scrollt statt zu ziehen)",
     lambda: patch("frontend/css/chat.css", "    touch-action: none;\n", "")),

    ("Transition bleibt beim Ziehen an (Leiste laeuft dem Zeiger nach)",
     lambda: patch("frontend/css/chat.css",
                   "body.cs-resizing .chat-sidebar { transition: none; }", "")),

    ("keine Textauswahl-Sperre",
     lambda: patch("frontend/css/chat.css",
                   "body.cs-resizing { user-select: none; cursor: col-resize; }",
                   "body.cs-resizing { cursor: col-resize; }")),

    ("Griff bleibt eingeklappt sichtbar",
     lambda: patch("frontend/css/chat.css",
                   ".chat-screen.sidebar-collapsed .cs-resize { display: none; }", "")),

    ("Obergrenze als feste Zahl statt am Fenster",
     lambda: patch("frontend/js/chat.js",
                   "Math.min(_CS_W_MAX, window.innerWidth - _CS_W_CHAT)",
                   "_CS_W_MAX")),

    ("Zuruecksetzen setzt 240 statt die Variable wegzunehmen",
     lambda: patch("frontend/js/chat.js",
                   "if (screen) screen.style.removeProperty('--cs-w');",
                   "if (screen) screen.style.setProperty('--cs-w', '240px');")),

    ("kaputter gespeicherter Wert wird uebernommen (NaN in die Breite)",
     lambda: patch("frontend/js/chat.js",
                   "        return Number.isFinite(n) && n > 0 ? n : null;   "
                   "// kaputter Wert = keine Angabe",
                   "        return n;")),

    ("pointercancel wird nicht behandelt (Leiste haengt im Zug fest)",
     lambda: patch("frontend/js/chat.js",
                   "        griff.addEventListener('pointercancel', ende);\n", "")),

    ("kein setPointerCapture (Zug reisst beim Verlassen des Griffs ab)",
     lambda: patch("frontend/js/chat.js",
                   "            try { griff.setPointerCapture(e.pointerId); } catch (err) {}",
                   "")),

    ("pointermove speichert bei JEDER Bewegung",
     lambda: patch("frontend/js/chat.js",
                   "            _csBreiteAnwenden(startW + (e.clientX - startX), false);",
                   "            _csBreiteAnwenden(startW + (e.clientX - startX), true);")),

    ("jede Maustaste zieht (auch die rechte)",
     lambda: patch("frontend/js/chat.js",
                   "            if (e.button !== undefined && e.button !== 0) return;"
                   "   // nur die linke Taste\n", "")),

    ("Media-Query setzt die Leiste wieder direkt (gewinnt gegen den Zug)",
     lambda: patch("frontend/css/chat.css",
                   "    .chat-screen { --cs-w: 168px; }",
                   "    .chat-sidebar { flex-basis: 168px; width: 168px; }")),

    ("Griff ohne role/tabindex (mit der Tastatur unerreichbar)",
     lambda: patch("frontend/chat.html",
                   ' role="separator" aria-orientation="vertical"\n         tabindex="0"',
                   "")),

    ("Doppelklick-Rueckweg entfernt",
     lambda: patch("frontend/js/chat.js",
                   "        griff.addEventListener('dblclick', (e) => "
                   "{ e.preventDefault(); _csBreiteZuruecksetzen(); });\n", "")),

    ("Fenster-Nachzieher entfernt (gezogene Breite bleibt im engen Fenster)",
     lambda: patch("frontend/js/chat.js",
                   "        window.addEventListener('resize', () => {\n"
                   "            const w = _csGespeicherteBreite();\n"
                   "            if (w !== null) _csBreiteAnwenden(w, false);\n"
                   "        });\n", "")),

    ("i18n nur deutsch",
     lambda: patch("frontend/js/i18n.js",
                   "        'chat.sidebar_resize': 'Resize the history sidebar – "
                   "drag, arrow keys, double-click to reset',\n", "")),

    ("i18n-Text in beiden Sprachen gleich (nicht uebersetzt)",
     lambda: patch("frontend/js/i18n.js",
                   "        'chat.sidebar_resize': 'Resize the history sidebar – "
                   "drag, arrow keys, double-click to reset',",
                   "        'chat.sidebar_resize': 'Breite der Verlaufsleiste ändern – "
                   "ziehen, Pfeiltasten, Doppelklick für die Vorgabe',")),

    ("Waechter prueft wieder ein Muster statt den Handler (Selbstkontrolle)",
     lambda: patch("tests/test_cs_resize_ui.js",
                   "    const bewegen = handler(init, 'pointermove');",
                   "    const bewegen = 'nichts';")),
]

sichern()
atexit.register(ende)
signal.signal(signal.SIGTERM, lambda *_: (ende(), sys.exit(143)))

print("=" * 74)
print("Gegenproben: Ziehgriff der Verlaufsleiste")
print("=" * 74)

rc, fails, bilanz, aus = lauf()
if rc != 0 or fails or not bilanz:
    print(f"ABBRUCH: Basis ist nicht gruen (rc={rc}, {fails} FAIL, Bilanz={bilanz}).")
    print("Ohne gruene Basis ist keine Gegenprobe deutbar.")
    print(aus[-1500:])
    sys.exit(2)
print(f"Basis gruen.\n")

beisst = stumm = 0
for name, tun in PROBEN:
    zurueck()
    try:
        tun()
    except AssertionError as e:
        print(f"  ⚠  SABOTAGE VERFEHLT  {name}\n       {e}")
        stumm += 1
        continue
    rc, fails, bilanz, aus = lauf()
    # ⚠ GEMESSEN WIRD EXIT-CODE UND BILANZZEILE, nicht nur die Zahl der FAIL:
    # ein Lauf, der ABBRICHT, hat keine Bilanz und ist von "bestanden" sonst
    # nicht zu unterscheiden.
    if not bilanz:
        print(f"  ⚠  OHNE BILANZ (abgebrochen)  {name}")
        stumm += 1
    elif fails > 0:
        print(f"  ✓  beisst ({fails} FAIL)  {name}")
        beisst += 1
    else:
        print(f"  ✗  STUMM                 {name}")
        stumm += 1

zurueck()
rc, fails, bilanz, aus = lauf()
print(f"\nNach dem Zuruecknehmen: rc={rc}, {fails} FAIL  "
      f"({'wiederhergestellt' if rc == 0 and not fails else 'ACHTUNG: Rueckstand!'})")
print("=" * 74)
print(f"Ergebnis: {beisst} von {len(PROBEN)} Gegenproben beissen, {stumm} stumm")
print("=" * 74)
sys.exit(0 if stumm == 0 and rc == 0 else 1)
