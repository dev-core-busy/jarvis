#!/usr/bin/env python3
"""Gegenprobe zu test_update_commitliste.py und Abschnitt 4c von
test_update_pill_ui.js: beissen die Waechter?

Jede Probe dreht EINEN Teil der Commit-Liste zurueck, laesst den zustaendigen
Waechter laufen und erwartet Exit 1 mit mindestens einem FAIL (Exit 2 oder ein
Lauf ohne Bilanzzeile zaehlt NICHT als Biss). Vorher gruene Basislaeufe beider
Waechter, danach Byte-Gleichheit per md5. Ein Rueckstand eines abgebrochenen
Laufs wird beim naechsten Start aus der Sicherung zurueckgelegt.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)


import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UM = ROOT / "backend" / "update_manager.py"
JS = ROOT / "frontend" / "js" / "update_widget.js"
CSS = ROOT / "frontend" / "css" / "update_widget.css"
STYLE = ROOT / "frontend" / "css" / "style.css"
CHAT = ROOT / "frontend" / "css" / "chat.css"
W_PY = ROOT / "tests" / "test_update_commitliste.py"
W_JS = ROOT / "tests" / "test_update_pill_ui.js"
W_VERL = ROOT / "tests" / "test_update_verlauf_ui.js"
SICHERUNG = Path.home() / ".gegen_update_commitliste"
# Ablage nach geordnetem Ende abraeumen (tests/lib/gegen_ablage.py) - VOR jedem
# atexit.register dieses Skripts, damit es als Letztes laeuft (atexit: LIFO).
import gegen_ablage  # noqa: E402
gegen_ablage.abraeumen_bei_ende(SICHERUNG)
DATEIEN = [UM, JS, CSS, STYLE, CHAT]

PROBEN = [
    ("alte Liste: letzte N statt HEAD..origin", W_PY, UM, [
        ('    bereich = f"HEAD..origin/{branch}"\n', '    bereich = f"origin/{branch}"\n')]),
    ("Kurz-Zeile wird ignoriert", W_PY, UM, [
        ("        if z.strip().lower().startswith(_KURZ_MARKE):\n", "        if False:\n")]),
    ("Kurz-Zeile ohne Fortsetzungszeilen", W_PY, UM, [
        ("                teile.append(f)\n", "                pass\n")]),
    ("Kurz-Zeile laeuft in den Trailer", W_PY, UM, [
        ("                if not f.strip() or _TRAILER.match(f.strip()):\n",
         "                if not f.strip():\n")]),
    ("leere Kurz-Zeile zaehlt als Absatz", W_PY, UM, [
        ('            s = ""                 # leere Kurz-Zeile: ihr Absatz zaehlt nicht\n',
         "            pass\n")]),
    ("Abkuerzungen beenden den Satz", W_PY, UM, [
        ("        if len(wort) <= 1 or wort.lower() in _ABKUERZUNGEN:\n", "        if False:\n")]),
    ("Trailer-Absatz wird als Satz gezeigt", W_PY, UM, [
        ("    if not absatz or all(_TRAILER.match(a) for a in absatz):\n",
         "    if not absatz:\n")]),
    ("Aufzaehlungszeichen bleibt stehen", W_PY, UM, [
        ("        fliess = fliess[2:]\n", "        pass\n")]),
    ("kein Laengendeckel", W_PY, UM, [
        ("    if len(text) <= MAX_BESCHREIBUNG:\n", "    if True:\n")]),
    ("Rest wird nicht beziffert", W_PY, UM, [
        ('            "commits_weitere": max(0, gesamt - len(commits))}\n',
         '            "commits_weitere": 0}\n')]),
    # Anker 2026-11-19 nachgezogen: das Format steht seit dem Umbau in der
    # Konstante _LOG_FORMAT. Vorher brach der Harness hier mit Exit 2 ab, und
    # die sechs Proben danach liefen gar nicht erst.
    ("Trenner sind Leerraum (\\x1f/\\x1e)", W_PY, UM, [
        ('_LOG_FORMAT = "--format=%H%x02%s%x02%ai%x02%an%x02%b%x03"\n',
         '_LOG_FORMAT = "--format=%H%x1f%s%x1f%ai%x1f%an%x1f%b%x1e"\n'),
        ('    for satz in log_str.split("\\x03"):\n', '    for satz in log_str.split("\\x1e"):\n'),
        ('        felder = satz.lstrip("\\n").split("\\x02")\n',
         '        felder = satz.lstrip("\\n").split("\\x1f")\n')]),
    # Zwei Fundstellen seit dem Aenderungsverlauf (Popup und Verlauf), getrennt
    # ueber die Einrueckung - ein Anker, der beide trifft, bricht den Harness ab.
    ("UI: Beschreibung ohne esc() (Popup)", W_JS, JS, [
        ("\n                var desc = c.beschreibung\n                    ? '<span class=\"upd-commit-desc\">' + esc(c.beschreibung)",
         "\n                var desc = c.beschreibung\n                    ? '<span class=\"upd-commit-desc\">' + (c.beschreibung)")]),
    ("UI: Beschreibung ohne esc() (Verlauf)", W_VERL, JS, [
        ("\n            var desc = c.beschreibung\n                ? '<span class=\"upd-commit-desc\">' + esc(c.beschreibung)",
         "\n            var desc = c.beschreibung\n                ? '<span class=\"upd-commit-desc\">' + (c.beschreibung)")]),
    ("UI: leere Beschreibung erzeugt leere Zeile", W_JS, JS, [
        ("                var desc = c.beschreibung\n", "                var desc = true\n")]),
    ("UI: Rest wird nicht angezeigt", W_JS, JS, [
        ("                + (d.commits_weitere > 0\n", "                + (false\n")]),
    ("UI: Beschreibung ausserhalb der Textspalte", W_JS, JS, [
        ("                    + desc + '</span>'\n", "                    + '</span>' + desc\n")]),
    # Abschnitt 1b: eine zweite Fassung in einer SPAETER geladenen Datei. Genau
    # das war der Vorfall vom 2026-11-19 - style.css gewann auf /settings und
    # /wissen gegen update_widget.css, obwohl dort alles richtig stand.
    ("CSS: style.css traegt wieder eine Fassung von .upd-commit", W_JS, STYLE, [
        (".cpu-bar-container {", ".upd-commit { display: flex; }\n.cpu-bar-container {")]),
    ("CSS: chat.css traegt wieder .security-badge", W_JS, CHAT, [
        ("/* \u2500\u2500\u2500 Messages Container",
         ".security-badge { width: 24px; }\n/* \u2500\u2500\u2500 Messages Container")]),
    # Abschnitt 1c: der Betreff zurueck in die schmale Spalte neben dem Datum.
    ("CSS: Betreff wieder neben Hash und Datum", W_JS, CSS, [
        ("grid-column:1 / -1;grid-row:2", "grid-column:2;grid-row:1")]),
    ("CSS: Umbruch wieder mitten im Wort", W_JS, CSS, [
        ("overflow-wrap:break-word;min-width:0", "overflow-wrap:anywhere;min-width:0")]),
    ("CSS: Datum nicht mehr rechts in der Kopfzeile", W_JS, CSS, [
        ("justify-self:end;white-space:nowrap", "white-space:nowrap")]),
]


def md5(p):
    return hashlib.md5(p.read_bytes()).hexdigest()


def lauf(waechter):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    cmd = ["node", str(waechter)] if waechter.suffix == ".js" else [sys.executable, str(waechter)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=300)
    except subprocess.TimeoutExpired:
        return 124, None, "Zeitueberschreitung"
    m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout)
    return r.returncode, (int(m.group(2)) if m else None), r.stdout


def sichern():
    SICHERUNG.mkdir(mode=0o700, exist_ok=True)
    for p in DATEIEN:
        shutil.copy2(p, SICHERUNG / p.name)


def zurueck():
    for p in DATEIEN:
        s = SICHERUNG / p.name
        if s.exists() and s.read_bytes() != p.read_bytes():
            p.write_bytes(s.read_bytes())
            print("Rueckstand zurueckgelegt: " + str(p.relative_to(ROOT)))


# Rueckstand eines abgebrochenen Laufs (Laufmarke = Sicherungsverzeichnis)
if SICHERUNG.exists():
    zurueck()
    shutil.rmtree(SICHERUNG)

# Regel statt Pflege: jede Probe zielt auf eine gesicherte Datei
fremd = {str(p[2]) for p in PROBEN} - {str(d) for d in DATEIEN}
if fremd:
    print("ABBRUCH: Proben auf ungesicherte Dateien: %s" % fremd)
    sys.exit(2)

for w in (W_PY, W_JS, W_VERL):
    rc, fails, aus = lauf(w)
    if rc != 0 or fails != 0:
        print("ABBRUCH: Basislauf %s nicht gruen (rc=%s)\n%s" % (w.name, rc, aus[-600:]))
        sys.exit(2)
print("Basislaeufe gruen")

vorher = {p: md5(p) for p in DATEIEN}
sichern()
stumm = []
try:
    for name, waechter, datei, ersetzungen in PROBEN:
        text = (SICHERUNG / datei.name).read_text(encoding="utf-8")
        for alt, neu in ersetzungen:
            if text.count(alt) != 1:
                print("ABBRUCH: Probe '%s' – Anker nicht genau einmal gefunden: %r" % (name, alt[:70]))
                sys.exit(2)
            text = text.replace(alt, neu)
        datei.write_text(text, encoding="utf-8")
        rc, fails, _ = lauf(waechter)
        datei.write_bytes((SICHERUNG / datei.name).read_bytes())
        beisst = rc == 1 and bool(fails)
        print("  %s %s (rc=%s, %s FAIL)" % ("BEISST" if beisst else "STUMM ", name, rc, fails))
        if not beisst:
            stumm.append(name)
finally:
    zurueck()
    shutil.rmtree(SICHERUNG, ignore_errors=True)

abweichend = [str(p.relative_to(ROOT)) for p in DATEIEN if md5(p) != vorher[p]]
if abweichend:
    print("ABBRUCH: nach den Proben nicht byte-gleich: %s" % abweichend)
    sys.exit(2)

print("\n%d von %d Proben beissen" % (len(PROBEN) - len(stumm), len(PROBEN)))
sys.exit(1 if stumm else 0)
