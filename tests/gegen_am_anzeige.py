#!/usr/bin/env python3
"""Gegenproben zu Abschnitt 29/30: die Versionsanzeige unter „Anwendung holen".

Gemeldet am 2026-09-14: „Du hast die Versionsanzeige unter User Kachel ->
AI-Maus -> Anwendung holen unterschlagen." Ursache war ein Riegel, der die
Auskunft „welche Version liefere ich aus" an einen ausstehenden Bau band – nach
jedem Rollout stand deshalb KEINE Version in der Kachel (auf ECHT gemessen
59 Minuten lang), waehrend der Knopf daneben ein Paket auslieferte.

Jede Probe hier stellt genau EINEN Teil des Fixes zurueck. Beisst eine nicht,
ist der Waechter an dieser Stelle zahnlos – nicht der Code in Ordnung.

⚠ SICHERUNG AUF PLATTE + atexit + SIGTERM: ein per Timeout GEKILLTER Lauf laesst
   den Arbeitsbaum sonst sabotiert zurueck, und der naechste Testlauf meldet
   einen Fehler, den es nicht gibt (Register, mehrfach bezahlt).
⚠ Gemessen wird EXIT-CODE UND BILANZZEILE, nie das Zaehlen von FAIL-Zeilen:
   ein Lauf, der abbricht, hat keine Bilanz und ist von „bestanden" sonst nicht
   zu unterscheiden.
⚠ `Vorgaben.cs` gehoert in die Sicherung, obwohl keine Probe sie anfasst: der
   GEPRUEFTE Lauf schreibt sie selbst (er ruft `paket_bauen`).
"""
import atexit
import pathlib
import re
import shutil
import signal
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SICHER = pathlib.Path.home() / ".gegen-am-anzeige"

DATEIEN = [
    "backend/ai_mouse.py",
    "backend/main.py",
    "frontend/js/ai_mouse.js",
    "ai-mouse/src/AiMouse/Configuration/Vorgaben.cs",
]


def sichern():
    SICHER.mkdir(mode=0o700, exist_ok=True)
    for rel in DATEIEN:
        shutil.copy2(ROOT / rel, SICHER / rel.replace("/", "__"))


def zurueck():
    if not SICHER.is_dir():
        return
    for rel in DATEIEN:
        q = SICHER / rel.replace("/", "__")
        if q.is_file():
            shutil.copy2(q, ROOT / rel)


MARKE = SICHER / "LAEUFT"


def abraeumen():
    """Die Sicherung wird beim GEORDNETEN Ende entfernt.

    Ohne das stellt der naechste Lauf beim Start einen veralteten Stand her und
    macht Arbeit zunichte, die zwischendurch passiert ist. Nach einem `kill -9`
    bleibt die Marke liegen – und dann soll das Zuruecknehmen greifen.
    """
    zurueck()
    if MARKE.is_file():
        MARKE.unlink()
    shutil.rmtree(SICHER, ignore_errors=True)


atexit.register(abraeumen)
signal.signal(signal.SIGTERM, lambda *_: sys.exit(2))

if MARKE.is_file():
    print("⚠ Rueckstand eines abgebrochenen Laufs gefunden – nehme ihn zurueck.")
    zurueck()
sichern()
MARKE.write_text("laeuft\n", encoding="utf-8")


def lauf():
    """(exit, hat_bilanz, fails)"""
    p = subprocess.run([sys.executable, str(ROOT / "tests" / "test_ai_mouse.py")],
                       capture_output=True, text=True, timeout=900)
    aus = p.stdout + p.stderr
    m = re.search(r"(\d+) OK, (\d+) FAIL", aus)
    return p.returncode, m is not None, (int(m.group(2)) if m else -1)


def probe(name, rel, alt, neu, nr=1):
    """`nr` = das wievielte Vorkommen getroffen wird (1-basiert).

    ⚠ Ein Anker, der mehrfach vorkommt, ist ohne diese Angabe eine Probe, die
      ihr Ziel verfehlen KANN – dieselbe Falle wie eine Sabotage, die den
      Kommentar statt des Aufrufs trifft.
    """
    d = ROOT / rel
    s = d.read_text(encoding="utf-8")
    n = s.count(alt)
    if n < nr:
        print(f"  ⚠ {name}: ANKER NICHT GEFUNDEN ({n}x, gesucht #{nr})")
        return False
    if nr == 1 and n != 1:
        print(f"  ⚠ {name}: ANKER NICHT EINDEUTIG ({n}x) – Probe verfehlt ihr Ziel")
        return False
    teile = s.split(alt)
    d.write_text(alt.join(teile[:nr]) + neu + alt.join(teile[nr:]), encoding="utf-8")
    try:
        code, bilanz, fails = lauf()
    finally:
        zurueck()
    if not bilanz:
        print(f"  ⚠ {name}: KEINE BILANZ (Abbruch) – nicht deutbar")
        return False
    ok = code != 0 and fails > 0
    print(f"  {'✓' if ok else '✗'} {name}: {fails} FAIL")
    return ok


print("Basis …", end=" ", flush=True)
c, b, f = lauf()
if not (c == 0 and b and f == 0):
    print(f"NICHT GRUEN (exit={c}, bilanz={b}, fails={f}) – ohne gruene Basis "
          f"ist keine Gegenprobe deutbar.")
    sys.exit(2)
print("gruen\n")

PROBEN = [
    # ── Der gemeldete Fehler selbst ────────────────────────────────────────
    ("der Riegel ist zurueck (die Anzeige bleibt leer)",
     "backend/ai_mouse.py",
     "    return exe_version()",
     "    if bau_noetig():\n        return ''\n    return exe_version()"),
    ("klient_version liest wieder den Quelltext (Update-Schleife)",
     "backend/ai_mouse.py",
     "    return exe_version()", "    return quelltext_version()"),

    # ── Der Parser ─────────────────────────────────────────────────────────
    # ⚠ „den ersten Treffer nehmen" ist genau der Fall der echten Anwendung:
    #   dort steht Microsofts Laufzeit-Block VOR unserem.
    ("erster Signatur-Treffer statt Ressourcen-Verzeichnis",
     "backend/ai_mouse.py",
     "            if kennung & 0x80000000 or kennung != _RT_VERSION:",
     "            if False:"),
    ("ein Fehler ergibt eine geratene Zahl statt Schweigen",
     "backend/ai_mouse.py",
     "    except (OSError, struct.error, ValueError):\n        return \"\"",
     "    except (OSError, struct.error, ValueError):\n        return \"9.9.9\""),
    ("0.0.0.0 gilt als Auskunft",
     "backend/ai_mouse.py",
     "                    if not ms and not ls:\n                        return \"\"",
     "                    if False:\n                        return \"\""),
    ("die vierte Null bleibt stehen (1.0.7.0 statt 1.0.7)",
     "backend/ai_mouse.py",
     "                    while len(teile) > 3 and teile[-1] == 0:\n"
     "                        teile.pop()",
     "                    pass"),
    ("die Sektionsgrenzen werden nicht geprueft",
     "backend/ai_mouse.py",
     "                    if start < 0 or d_gr <= 0 or start + d_gr > len(daten):\n"
     "                        return \"\"",
     "                    pass"),

    # ── Das Merken ─────────────────────────────────────────────────────────
    ("kein Merker (jeder Abruf liest die Ressourcen neu)",
     "backend/ai_mouse.py",
     "    schluessel = (str(p), st.st_mtime_ns, st.st_size)\n"
     "    if _ver_merker.get(\"schluessel\") == schluessel:\n"
     "        return _ver_merker.get(\"wert\", \"\")\n"
     "    wert = _pe_version(p)\n"
     "    _ver_merker[\"schluessel\"] = schluessel\n"
     "    _ver_merker[\"wert\"] = wert\n"
     "    return wert",
     "    return _pe_version(p)"),
    ("der Merker-Schluessel kennt den Zeitstempel nicht (ein Bau faellt nicht auf)",
     "backend/ai_mouse.py",
     "    schluessel = (str(p), st.st_mtime_ns, st.st_size)",
     "    schluessel = (str(p),)"),

    # ── Die Kette bis in die Kachel ────────────────────────────────────────
    ("health liefert das Feld nicht mehr",
     "backend/main.py",
     '        "klient_version": ai_mouse.klient_version(),\n', ""),
    ("der Renderer schreibt sie nicht in die Kachel",
     "frontend/js/ai_mouse.js",
     "vs.textContent = v ? (t('aimouse.version', 'Version') + ' ' + v) : '';",
     "vs.title = v;"),
]

gut = 0
for p in PROBEN:
    if probe(*p):
        gut += 1

print(f"\n{gut} von {len(PROBEN)} Gegenproben beissen.")
sys.exit(0 if gut == len(PROBEN) else 1)
