#!/usr/bin/env python3
"""Ist die Mechanik der GEMEINSAMEN Fragen kaputt? (Messung 2026-09-15)

Gemeldet: „warum werden mit 1.0.8 nicht mehr alle Fragen geholt – die 'für
alle' sind nicht sichtbar". Der Client-Weg ist als Ursache ausgeschlossen
(Diff leer, kein Filter auf `gemeinsam`). Bleibt die Frage, ob die
Raeum-Migration vom 10.09. jede NEU angelegte gemeinsame Frage wieder
wegnimmt – das waere der Fall, wenn der Marker `_global_geraeumt` fehlt, und
es saehe genau so aus wie gemeldet.

⚠ DIE PROBE STELLT DEN VORGEFUNDENEN BESTAND WIEDER HER. `data/ai_mouse_
fragen.json` ist echter Bestand; eine Messung, die darin etwas liegen laesst,
ist teurer als der Fehler, den sie sucht.
"""
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/jarvis")
os.environ.setdefault("HOME", "/home/jarvis")

_ok = _fail = 0


def check(text, bed, info=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  OK   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  [%s]" % info) if info else ""))


from backend import ai_mouse_fragen as amf  # noqa: E402

DATEI = Path("/opt/jarvis/data/ai_mouse_fragen.json")
SICHER = Path("/tmp/am-fragen-sicherung-%d.json" % int(time.time()))

if not DATEI.exists():
    print("ABBRUCH: %s fehlt" % DATEI)
    sys.exit(2)

shutil.copy2(DATEI, SICHER)
print("Bestand gesichert nach %s (%d Bytes)\n" % (SICHER, SICHER.stat().st_size))

vor = json.loads(DATEI.read_text(encoding="utf-8"))
neue_id = None

try:
    print("=== 1) Vorgefundener Bestand ===")
    print("  Schluessel        : %s" % sorted(vor.keys()))
    print("  _global_geraeumt  : %r" % vor.get("_global_geraeumt"))
    print("  global_ (fuer alle): %d" % len(vor.get("global_") or []))
    for f in (vor.get("global_") or []):
        print("     - %s" % f.get("titel"))
    check("der Raeum-Marker steht (sonst raeumt die Migration bei JEDEM Laden)",
          bool(vor.get("_global_geraeumt")), repr(vor.get("_global_geraeumt")))

    print("\n=== 2) Liefert liste() die gemeinsamen an einen NICHT-Admin? ===")
    # Das ist die Zusage: `darf_aendern` haengt am Admin-Status, die
    # SICHTBARKEIT nicht.
    l_admin = amf.liste("pruefer", ist_admin=True)
    l_normal = amf.liste("pruefer", ist_admin=False)
    check("beide sehen gleich viele Eintraege",
          len(l_admin) == len(l_normal), "%d gegen %d" % (len(l_admin), len(l_normal)))

    print("\n=== 3) DER KERN: eine neue gemeinsame Frage anlegen ===")
    # ⚠ SIGNATUR NACHGESEHEN, NICHT GERATEN: (user, fid, titel, prompt, …).
    # Ein geratener Aufruf haette hier eine Frage unter falschem Besitzer
    # angelegt – im Bestand des Betreibers.
    e = amf.speichern("jarvis", "", "PRUEFUNG gemeinsam", "Dies ist eine Messung.",
                      gemeinsam=True, ist_admin=True)
    neue_id = (e or {}).get("id")
    check("sie liess sich anlegen", bool(neue_id), repr(e))

    # ⚠ `liste()` liest bei JEDEM Aufruf die DATEI (kein Cache, nachgesehen) –
    # und ruft dabei `_saeen()`. Genau dort raeumt die Migration, wenn der
    # Marker fehlt. Der naechste Aufruf ist also der echte Nachweis.
    l2 = amf.liste("jarvis", ist_admin=True)
    gem = [f for f in l2 if f.get("gemeinsam")]
    check("…und sie ist nach dem Neuladen NOCH DA",
          any(f.get("id") == neue_id for f in gem),
          "gemeinsame jetzt: %d" % len(gem))

    # Und aus der Sicht eines ANDEREN Benutzers – das ist der gemeldete Fall.
    l3 = amf.liste("irgendwer.anderes", ist_admin=False)
    gem3 = [f for f in l3 if f.get("gemeinsam")]
    check("…und ein ANDERER Benutzer sieht sie auch",
          any(f.get("id") == neue_id for f in gem3),
          "er sieht %d gemeinsame von %d gesamt" % (len(gem3), len(l3)))
    check("…er darf sie aber nicht aendern",
          all(not f.get("darf_aendern") for f in gem3) if gem3 else False)

    print("\n=== 4) Was der CLIENT daraus ins Menue nimmt ===")
    # Der Client verlangt titel UND prompt – fehlt eines, faellt der Eintrag
    # still aus dem Menue.
    ohne = [f for f in l3 if not (f.get("titel") and f.get("prompt"))]
    check("jeder gelieferte Eintrag hat titel UND prompt (sonst faellt er raus)",
          not ohne, "ohne: %s" % [f.get("titel") for f in ohne])
    print("  Menue-Eintraege fuer einen fremden Benutzer: %d "
          "(davon gemeinsam: %d)" % (len(l3), len(gem3)))
finally:
    print("\n=== Aufraeumen ===")
    if neue_id:
        try:
            amf.loeschen("jarvis", neue_id, ist_admin=True)
        except Exception as e:  # noqa: BLE001
            print("  ⚠ Loeschen ueber das Modul fehlgeschlagen: %s" % e)
    # Sicherungs-Rueckspielung ist die harte Garantie – nicht das Loeschen.
    shutil.copy2(SICHER, DATEI)
    os.chmod(DATEI, 0o640)
    nach = json.loads(DATEI.read_text(encoding="utf-8"))
    check("der vorgefundene Bestand ist byte-genau wieder da",
          nach == vor, "Schluessel jetzt: %s" % sorted(nach.keys()))
    SICHER.unlink(missing_ok=True)

print("\n%d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
