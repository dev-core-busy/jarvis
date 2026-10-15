#!/usr/bin/env python3
"""Gegenproben zu "Seite maximieren" (seite_breit.js): beisst jeder Waechter EINZELN?

Jede Probe dreht GENAU EINE Zusage zurueck und erwartet, dass der zugehoerige
Waechter das meldet. Beisst eine nicht, ist das ein TESTMANGEL – kein Beweis.

Waechter:
  UI   = tests/test_seite_breit_ui.js   (jsdom: Struktur, Verhalten, Merken)
  LIVE = tests/live_seite_breit_ui.py   (Chrome: die BREITE – jsdom rechnet
         sie nicht und ignoriert die Spezifitaet); fuer die Probe nur auf
         zwei Seiten (SEITEN_NUR), sonst dauert jede Probe Minuten.

⚠ SICHERUNG AUF PLATTE mit LAUFMARKE (Register: ein abgeschossener Harness
hinterlaesst den Baum gepatcht). Jede Datei, die eine Probe anfasst, muss in
DATEIEN stehen – als REGEL geprueft.
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
ABLAGE = pathlib.Path.home() / ".gegen-seite-breit"
MARKE = ABLAGE / ".laeuft"

DATEIEN = [
    "frontend/js/seite_breit.js",
    "frontend/css/theme.css",
    "frontend/feedback.html",
    "frontend/tracks.html",
    "frontend/api.html",
    "frontend/sap.html",
    "frontend/js/i18n.js",
    "frontend/js/tracks.js",
    "frontend/wissen.html",
]

UI = ["node", str(ROOT / "tests" / "test_seite_breit_ui.js")]
LIVE = ["python3", str(ROOT / "tests" / "live_seite_breit_ui.py")]
LIVE_ENV = {"SEITEN_NUR": "/wissen,/feedback,/api"}

SB = "frontend/js/seite_breit.js"
PROBEN = [
    # ── Verhalten (seite_breit.js) ──────────────────────────────────────────
    ("Klick schaltet die Breite nicht um", SB,
     "        document.body.classList.toggle('jv-breit', !!an);\n", "", UI),
    ("Zeichen wechselt nicht", SB,
     "            b.innerHTML = an ? '&#128471;' : '&#9974;';\n",
     "            b.innerHTML = '&#9974;';\n", UI),
    ("Beschriftung wechselt nicht mit dem Zustand", SB,
     "            var k = an ? 'common.minimize' : 'common.maximize';\n",
     "            var k = 'common.maximize';\n", UI),
    ("i18n-Attribute wandern nicht mit (Sprachwechsel holt alten Text)", SB,
     "            b.setAttribute('data-i18n-title', k);\n"
     "            b.setAttribute('data-i18n-aria', k);\n", "", UI),
    ("aria-pressed bleibt stehen", SB,
     "            b.setAttribute('aria-pressed', an ? 'true' : 'false');\n", "", UI),
    ("Zustand wird nicht gemerkt", SB,
     "            try { localStorage.setItem(schluessel(b), an ? '1' : '0'); } catch (e) { }\n",
     "", UI),
    ("gemerkter Zustand wird beim Laden nicht angewandt", SB,
     "        if (gemerkt === '1') setzen(true);\n", "", UI),
    ("⚠ ein Schluessel fuer ALLE Seiten (statt je Seite)", SB,
     "            || 'jarvis_breit_' + (b.getAttribute('data-seite') || 'seite');\n",
     "            || 'jarvis_breit_andere';\n", UI),
    ("⚠ data-speicher ignoriert (/wissen verliert die gemerkte Breite)", SB,
     "        return b.getAttribute('data-speicher')\n            || 'jarvis_breit_'",
     "        return 'jarvis_breit_'", UI),
    ("⚠ Speicherzugriff ohne try (gesperrter Speicher wirft)", SB,
     "        try { gemerkt = localStorage.getItem(schluessel(b)); } catch (e) { }\n",
     "        gemerkt = localStorage.getItem(schluessel(b));\n", UI),
    # KEINE Probe auf den DOMContentLoaded-Zweig: alle Seiten binden das
    # Skript am Ende von <body> ein, der Knopf steht also schon – der Zweig
    # ist Guertel, keine Zusage (Gegenprobe 2026-09-28: beisst nicht, weil es
    # nichts zu beissen gibt).

    # ── Einbindung und Lage (HTML) ─────────────────────────────────────────
    ("/sap bindet seite_breit.js nicht ein", "frontend/sap.html",
     '<script src="/static/js/seite_breit.js?v=1"></script>\n', "", UI),
    ("/sap: Knopf fehlt", "frontend/sap.html",
     'id="jv-max" data-seite="sap"', 'id="jv-max-X" data-seite="sap"', UI),
    ("/sap: Bereich nicht markiert", "frontend/sap.html",
     '<div class="sp-wrap" data-jv-breit>', '<div class="sp-wrap">', UI),
    ("/tracks: zwei Seiten teilen einen data-seite-Namen", "frontend/tracks.html",
     'data-seite="tracks"', 'data-seite="feedback"', UI),
    ("⚠ /api: Knopf in #ad-wrap (render() loescht ihn)", "frontend/api.html",
     '    <div class="ad-wrap" id="ad-wrap" data-jv-breit>\n',
     '    <div class="ad-wrap" id="ad-wrap" data-jv-breit>\n'
     '        <button type="button" class="jv-max-btn" id="jv-max-2"></button>\n', UI),
    ("⚠ /tracks: Knopf wieder IN der Karte", "frontend/tracks.html",
     '<h2 data-i18n="tracks.board_head">Ablagen</h2>',
     '<h2 data-i18n="tracks.board_head">Ablagen</h2><button type="button" class="jv-max-btn"></button>', UI),
    ("/tracks: Einzel-Vollbild kehrt zurueck", "frontend/js/tracks.js",
     "        klappInit();\n", "        klappInit();\n        maxUmschalten;\n", UI),
    ("/wissen bindet seite_breit.js nicht ein", "frontend/wissen.html",
     '    <script src="/static/js/seite_breit.js?v=1"></script>\n', "", UI),
    ("/wissen: Bereich nicht markiert (900 px bleiben)", "frontend/wissen.html",
     '<div id="wi-app" class="wi-wrap hidden" data-jv-breit>', '<div id="wi-app" class="wi-wrap hidden">', UI),
    ("i18n: EN-Text fehlt", "frontend/js/i18n.js",
     "        'common.minimize':      'Restore',\n", "", UI),

    # ── Breite (theme.css) – nur im echten Browser messbar ─────────────────
    ("⚠ die Deckelung faellt nicht weg", "frontend/css/theme.css",
     "body.jv-breit [data-jv-breit] { max-width: none; }\n", "", LIVE),
    ("⚠ zu schwache Regel (verliert gegen .xx-wrap der Seite)", "frontend/css/theme.css",
     "body.jv-breit [data-jv-breit] { max-width: none; }\n",
     "[data-jv-breit].x, [data-jv-breit] { max-width: none; }\n", LIVE),
    ("Knopf nicht rechtsbuendig", "frontend/css/theme.css",
     ".jv-max-row { display: flex; justify-content: flex-end; align-items: center;\n",
     ".jv-max-row { display: flex; justify-content: flex-start; align-items: center;\n", LIVE),
]


def md5(p):
    return hashlib.md5(p.read_bytes()).hexdigest()


def sichern():
    ABLAGE.mkdir(parents=True, exist_ok=True)
    for rel in DATEIEN:
        # ⚠ IMMER erneuern: eine alte Sicherung stellte einen veralteten Stand her.
        shutil.copy2(ROOT / rel, ABLAGE / rel.replace("/", "__"))
    MARKE.write_text("laeuft", encoding="utf-8")


def zurueck():
    for rel in DATEIEN:
        z = ABLAGE / rel.replace("/", "__")
        if z.exists():
            shutil.copy2(z, ROOT / rel)
    if MARKE.exists():
        MARKE.unlink()


def lauf(cmd):
    """(Exit, hat_bilanz, FAIL-Zahl)."""
    env = {**os.environ, "JSDOM_PATH": str(ROOT / "node_modules" / "jsdom")}
    if cmd is LIVE:
        env.update(LIVE_ENV)
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), timeout=600, env=env)
    m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout + r.stderr)
    return r.returncode, bool(m), int(m.group(2)) if m else -1


def main():
    fehlend = sorted({p[1] for p in PROBEN} - set(DATEIEN))
    if fehlend:
        print("ABBRUCH: nicht gesicherte Dateien in PROBEN: %r" % fehlend)
        sys.exit(2)
    if MARKE.exists():
        print("⚠ Rueckstand eines abgeschossenen Laufs – nehme ihn zurueck")
        zurueck()
    sichern()
    stand = {rel: md5(ROOT / rel) for rel in DATEIEN}
    atexit.register(zurueck)
    for s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(s, lambda *a: (zurueck(), sys.exit(1)))

    print("Basislauf…")
    for name, cmd in (("UI", UI), ("LIVE", LIVE)):
        rc, bil, f = lauf(cmd)
        if rc != 0 or not bil:
            print("ABBRUCH: Basislauf %s nicht gruen (exit=%s, bilanz=%s, fail=%s)" % (name, rc, bil, f))
            sys.exit(2)
        print("  Basis %s: gruen" % name)

    beissen = nicht = 0
    for name, rel, alt, neu, cmd in PROBEN:
        datei = ROOT / rel
        s = datei.read_text(encoding="utf-8")
        if s.count(alt) != 1:
            print("  \033[33m?\033[0m %-62s SABOTAGE TRIFFT NICHT (%dx)" % (name, s.count(alt)))
            nicht += 1
            continue
        datei.write_text(s.replace(alt, neu, 1), encoding="utf-8")
        rc, bil, f = lauf(cmd)
        datei.write_text(s, encoding="utf-8")
        if rc != 0 and bil and f > 0:
            print("  \033[32m✓\033[0m %-62s beisst (%d FAIL)" % (name, f))
            beissen += 1
        elif rc != 0 and not bil:
            print("  \033[33m!\033[0m %-62s BRICHT AB ohne Bilanz" % name)
            nicht += 1
        else:
            print("  \033[31m✗\033[0m %-62s BEISST NICHT" % name)
            nicht += 1

    zurueck()
    abw = [rel for rel in DATEIEN if md5(ROOT / rel) != stand[rel]]
    print("\nByte-Gleichheit nach dem Lauf:", "ja" if not abw else "NEIN: %r" % abw)
    print("=" * 78)
    print("beissen: %d von %d" % (beissen, len(PROBEN)))
    sys.exit(1 if (nicht or abw) else 0)


if __name__ == "__main__":
    main()
