#!/usr/bin/env python3
"""Gegenproben zum Umstellen der Sichtbarkeit einer Short-Tracks-Ablage.

Jede Probe dreht GENAU EINE Zusage zurueck und misst, ob der Waechter beisst.
Eine Probe, die nicht beisst, ist ein Testmangel – kein Beweis.

⚠ SICHERUNG AUF PLATTE, nicht im Speicher: wird dieser Lauf abgeschossen
(Zeitlimit), bliebe der Arbeitsbaum sonst sabotiert zurueck, und der naechste
Testlauf meldete Fehler, die der Code nicht hat. Das hat das Projekt am
2026-09-04 bezahlt. Ein Rueckstand wird beim naechsten Start selbst zurueck-
genommen; nach dem Wiederherstellen wird auf BYTE-Gleichheit geprueft.
"""
import atexit
import hashlib
import io
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ABLAGE = Path.home() / ".gegen-tracks-global"
JSDOM = os.environ.get("JSDOM_PATH") or "/home/bender/node_modules/jsdom"

DATEIEN = ["backend/short_tracks.py", "backend/main.py",
           "frontend/js/tracks.js", "frontend/js/i18n.js"]


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def sichern():
    ABLAGE.mkdir(mode=0o700, exist_ok=True)
    for rel in DATEIEN:
        ziel = ABLAGE / rel.replace("/", "__")
        # IMMER erneuern: eine alte Sicherung wuerde beim Zurueckstellen einen
        # veralteten Stand herstellen und fertige Arbeit zunichte machen.
        shutil.copy2(ROOT / rel, ziel)


def zurueck(still=False):
    fehler = []
    for rel in DATEIEN:
        q = ABLAGE / rel.replace("/", "__")
        if not q.exists():
            continue
        shutil.copy2(q, ROOT / rel)
        if _md5(q) != _md5(ROOT / rel):
            fehler.append(rel)
    if fehler and not still:
        print("⚠ WIEDERHERSTELLUNG UNVOLLSTAENDIG: %s" % ", ".join(fehler))
    return not fehler


# Rueckstand eines abgeschossenen Laufs zuerst zuruecknehmen.
if ABLAGE.exists() and any((ABLAGE / r.replace("/", "__")).exists() for r in DATEIEN):
    print("… Rueckstand eines frueheren Laufs gefunden – stelle wieder her")
    zurueck()
    shutil.rmtree(ABLAGE, ignore_errors=True)

sichern()
atexit.register(lambda: (zurueck(still=True),
                         shutil.rmtree(ABLAGE, ignore_errors=True)))
signal.signal(signal.SIGTERM, lambda *_: sys.exit(2))


def lauf(cmd, env=None):
    e = dict(os.environ)
    e.update(env or {})
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       timeout=600, env=e)
    return p.stdout + p.stderr


def bilanz(text, js=False):
    """(FAIL-Anzahl, gelaufen?) – eine fehlende Bilanzzeile ist ein Fehlschlag."""
    import re
    m = re.search(r"(\d+) OK, (\d+) FAIL", text)
    if not m:
        return (-1, False)
    return (int(m.group(2)), True)


def py():
    return bilanz(lauf([sys.executable, "tests/test_short_tracks.py"]))


def ui():
    return bilanz(lauf(["node", "tests/test_short_tracks_ui.js"],
                       {"JSDOM_PATH": JSDOM}))


def patch(rel, alt, neu, anzahl=1):
    p = ROOT / rel
    s = io.open(p, encoding="utf-8").read()
    n = s.count(alt)
    assert n == anzahl, "Sabotage verfehlt ihr Ziel in %s: %d statt %d Treffer" % (
        rel, n, anzahl)
    io.open(p, "w", encoding="utf-8").write(s.replace(alt, neu))


# ── Basislauf: ohne gruene Basis ist keine Gegenprobe deutbar ───────────────
b_py, ok1 = py()
b_ui, ok2 = ui()
if not (ok1 and ok2) or b_py or b_ui:
    print("ABBRUCH: Basis ist nicht gruen (py=%s ui=%s)" % (b_py, b_ui))
    sys.exit(2)
print("Basis gruen: 0 FAIL in beiden Waechtern\n")

PROBEN = []


def probe(name, dateien, wer):
    PROBEN.append((name, dateien, wer))


# 1) Der Parameter wird ignoriert – die Sichtbarkeit bleibt immer stehen.
probe("aendern() ignoriert global_", [(
    "backend/short_tracks.py",
    "            ist_global = war_global if global_ is None else bool(global_)",
    "            ist_global = war_global",
)], "py")

# 2) Kein Tri-State: nicht gesendet gilt als "eigen".
probe("global_ ohne Tri-State (None → False)", [(
    "backend/short_tracks.py",
    "            ist_global = war_global if global_ is None else bool(global_)",
    "            ist_global = bool(global_)",
)], "py")

# 3) Jeder darf umstellen.
probe("Admin-Pruefung beim Umstellen raus", [(
    "backend/short_tracks.py",
    """                if not ist_admin:
                    raise DumpFehler(
                        "Nur Administratoren koennen die Sichtbarkeit einer "
                        "Ablage aendern.")""",
    "                pass",
)], "py")

# 4) Der Besitzer bleibt beim Privatisieren stehen → Einbahnstrasse.
probe("Besitzer wechselt beim Privatisieren nicht", [(
    "backend/short_tracks.py",
    "                    besitzer = norm_user(user)",
    "                    pass",
)], "py")

# 5)/6) Die Deckel greifen nicht mehr.
probe("Deckel MAX_DUMPS_GLOBAL raus", [(
    "backend/short_tracks.py",
    "                    if vorhanden >= MAX_DUMPS_GLOBAL:",
    "                    if False:",
)], "py")
probe("Deckel je Benutzer raus", [(
    "backend/short_tracks.py",
    "                    if eigene >= grenze:",
    "                    if False:",
)], "py")

# 7) Der Endpunkt reicht `global` als Feld durch → AENDERBAR schlaegt zu.
probe("PUT zieht global nicht heraus", [(
    "backend/main.py",
    """    felder = dict(body or {})
    sichtbarkeit = None
    if "global" in felder:
        sichtbarkeit = bool(felder.pop("global"))""",
    """    felder = dict(body or {})
    sichtbarkeit = None""",
)], "py")

# 8) Der Haken erscheint wieder nur beim Anlegen.
probe("Haken nur beim Anlegen (Altstand)", [(
    "frontend/js/tracks.js",
    "              (_istAdmin\n                  ? '<label class=\"st-hint\"",
    "              (_istAdmin && (id === 'neu')\n                  ? '<label class=\"st-hint\"",
)], "ui")

# 9) Der Haken wird nicht vorbelegt.
probe("Haken wird nicht vorbelegt", [(
    "frontend/js/tracks.js",
    "        if (gv) gv.checked = !!d['global'];",
    "        if (gv) gv.checked = false;",
)], "ui")

# 10) DER GEFAEHRLICHE FALL: `global` geht auch ohne Haken mit.
probe("global wird auch ohne Haken gesendet", [(
    "frontend/js/tracks.js",
    "        var g = $('st-f-global');\n        if (g) daten['global'] = !!g.checked;",
    "        var g = $('st-f-global');\n        daten['global'] = !!(g && g.checked);",
)], "ui")

# 11) Der Hilfetext behauptet wieder das Gegenteil.
probe("Hilfetext sagt wieder 'nicht änderbar'", [(
    "frontend/js/i18n.js",
    "Der Haken lässt sich später umstellen: Wegnehmen macht die Ablage wieder zu "
    "deiner eigenen und entzieht sie allen anderen. Bereits erzeugte Ergebnisse "
    "bleiben ihnen erhalten.",
    "Ob eine Ablage global ist, lässt sich später nicht ändern.",
)], "ui")

# ── Ausfuehren ─────────────────────────────────────────────────────────────
zeilen = []
for name, dateien, wer in PROBEN:
    try:
        for rel, alt, neu in dateien:
            patch(rel, alt, neu)
        f, gelaufen = py() if wer == "py" else ui()
        if not gelaufen:
            zeilen.append((name, "ABBRUCH OHNE BILANZ", False))
        else:
            zeilen.append((name, "%d FAIL" % f, f > 0))
    except AssertionError as e:
        zeilen.append((name, "SABOTAGE VERFEHLT: %s" % e, False))
    finally:
        zurueck()

print("\n" + "=" * 66)
beissen = 0
for name, erg, gut in zeilen:
    print("  %s  %-42s %s" % ("✓" if gut else "✗", name, erg))
    beissen += 1 if gut else 0
print("=" * 66)
print("  %d von %d Gegenproben beissen" % (beissen, len(zeilen)))

# Kontrolllauf: der Arbeitsbaum muss wieder der Ausgangsstand sein.
n_py, _ = py()
n_ui, _ = ui()
print("  Kontrolllauf nach dem Zurueckstellen: py=%d FAIL, ui=%d FAIL" % (n_py, n_ui))
sys.exit(0 if (beissen == len(zeilen) and not n_py and not n_ui) else 1)
