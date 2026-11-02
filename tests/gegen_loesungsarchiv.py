#!/usr/bin/env python3
"""Gegenprobe zu ``tests/test_loesungsarchiv.py``: beisst der Waechter?

Jede Probe dreht EINE Zusage zurueck, laesst den Waechter laufen und zaehlt
seine FAIL. Eine Probe, die stumm bleibt, ist ein Testmangel (Register).

⚠ NICHT IN EINEN SAMMELLAUF: die Proben patchen Dateien im Arbeitsbaum.
Gesichert wird vor jeder Probe auf Platte (``.gegen_sicherung``), ein
Rueckstand eines abgebrochenen Laufs wird beim naechsten Start selbst
zurueckgenommen, und nach dem Wiederherstellen wird die Byte-Gleichheit per
md5 geprueft. Vorab muss der Basislauf gruen sein – sonst ist keine Probe
deutbar (Exit 2). Laeuft ohne Bytecode (``PYTHONDONTWRITEBYTECODE=1``).
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEST = ROOT / "tests" / "test_loesungsarchiv.py"
SICHERUNG = ROOT / "tests" / ".gegen_sicherung_loesungsarchiv"
LA = "backend/loesungsarchiv.py"
SCH = "backend/scheduler.py"
SB = "backend/sandbox.py"

PROBEN = [
    ("Schranke ignoriert den Schwellwert", LA,
     'if int(e.get("zaehler") or 0) < int(st["schwelle"]) or not st["gruppen"]:',
     'if int(e.get("zaehler") or 0) < 0 or not st["gruppen"]:'),
    ("Modellaufruf mit Werkzeugkasten", LA,
     "tools=[], reasoning_effort=\"low\")\n    return \"\".join",
     "tools=None, reasoning_effort=\"low\")\n    return \"\".join"),
    ("erfundene Kennung wird angenommen", LA,
     "return g if g in angeboten else None", "return g or None"),
    ("fehlerhaftes Ticket gilt als verarbeitet", LA,
     "                zahl[\"fehler\"] += 1\n",
     "                zahl[\"fehler\"] += 1\n                stand[\"verarbeitet\"][t[\"key\"]] = {}\n"),
    ("JQL ohne Loesungsbedingung", LA,
     "AND resolution IS NOT EMPTY ", ""),
    ("Index nach Veroeffentlichung nicht angestossen", LA,
     'if sch["veroeffentlicht"] or sch["aktualisiert"] or sch["entfernt"]:', "if False:"),
    ("Wissensgraph-Arbeiter nicht geweckt", LA,
     "            wgx.wecken()\n", ""),
    ("Startdatum in der Zukunft erlaubt", LA,
     "        if tag > date.today():\n", "        if False:\n"),
    ("Anonymisierung nicht verlangt", LA,
     '"- Allgemein formulieren: KEINE Personennamen, Firmennamen, Kundennummern, "',
     '"- Allgemein formulieren. "'),
    ("Ticket ohne Entschaerfung", LA,
     "auftrag_analyse(jira_assist._ticket_text(t, kennung))",
     "auftrag_analyse(\"Ticket: %s\\n\" % key + str(t))"),
    ("Stand-Zeile wird mitverglichen (jeder Lauf indiziert)", LA,
     "if vorher is None or ohne(vorher) != ohne(inhalt):",
     "if vorher is None or vorher != inhalt:"),
    ("Einschalten ohne Wissensgruppe erlaubt", LA,
     '("Wissensgruppe", gruppen)', '("Wissensgruppe", True)'),
    ("Gruppenbeschraenkung des Graphen nicht beachtet", LA,
     "graph_deckt = graph and (not gg or bool(set(gg) & set(st[\"gruppen\"])))",
     "graph_deckt = graph"),
    ("Art fehlt in der Scheduler-Whitelist", SCH,
     '"cve_pruefung", "loesungsarchiv") else "agent",', '"cve_pruefung") else "agent",'),
    ("Abbruch hinterlaesst keinen 'letzten Lauf'", LA,
     '        _ergebnis_merken({"ok": False, "grund": grund})\n        e.args', '        e.args'),
    ("Abbruch gibt den Fortschritt nicht weiter", LA,
     "        e.args = (grund,)\n", ""),
    ("JQL fragt nur den ersten Bereich", LA,
     "for b in bereiche_)\n", "for b in bereiche_[:1])\n"),
    ("Altbestand mit einem Bereich geht verloren", LA,
     '        st["bereiche"] = [str(d["bereich"]).strip().upper()]\n', "        pass\n"),
    ("Dateikopf nennt nur den ersten Bereich", LA,
     "{', '.join(bb) or '-'}", "{bb[0] if bb else '-'}"),
    ("privater Ordner fehlt in PRIVATE_DIRS", SB,
     '                "data/graph",\n', '                "data/graph")\n_X = (\n'),
]


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def zurueck() -> None:
    """Rueckstand eines frueheren (abgebrochenen) Laufs zuruecknehmen."""
    if not SICHERUNG.is_dir():
        return
    for f in SICHERUNG.rglob("*"):
        if f.is_file():
            ziel = ROOT / f.relative_to(SICHERUNG)
            shutil.copy2(f, ziel)
            print(f"  ↺ zurueckgenommen: {ziel.relative_to(ROOT)}")
    shutil.rmtree(SICHERUNG)


def lauf() -> tuple[int, int, int]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, str(TEST)], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=300)
    m = re.search(r"Ergebnis: (\d+)/(\d+)", r.stdout)
    if not m:
        return r.returncode, -1, -1
    ok, ges = int(m.group(1)), int(m.group(2))
    return r.returncode, ok, ges - ok


def main() -> int:
    zurueck()
    dateien = sorted({p[1] for p in PROBEN})
    rc, ok, fail = lauf()
    if rc != 0 or fail != 0:
        print(f"Basislauf nicht gruen (Exit {rc}, {fail} FAIL) – keine Probe deutbar.")
        return 2
    print(f"Basislauf gruen: {ok} Pruefungen\n")
    vorher = {d: md5(ROOT / d) for d in dateien}
    stumm = []
    for name, datei, alt, neu in PROBEN:
        p = ROOT / datei
        text = p.read_text(encoding="utf-8")
        if text.count(alt) != 1:
            print(f"  ✗ Anker nicht eindeutig ({text.count(alt)}x): {name}")
            return 2
        (SICHERUNG / datei).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, SICHERUNG / datei)
        try:
            p.write_text(text.replace(alt, neu), encoding="utf-8")
            rc, ok, fail = lauf()
        finally:
            shutil.copy2(SICHERUNG / datei, p)
            shutil.rmtree(SICHERUNG)
        biss = rc == 1 and fail > 0
        print(f"  {'✓' if biss else '✗'} {name}: Exit {rc}, {fail} FAIL")
        if not biss:
            stumm.append(name)
    nachher = {d: md5(ROOT / d) for d in dateien}
    if nachher != vorher:
        print("⚠ Arbeitsbaum nach den Proben NICHT byte-gleich:",
              [d for d in dateien if nachher[d] != vorher[d]])
        return 2
    print(f"\nGegenprobe: {len(PROBEN) - len(stumm)}/{len(PROBEN)} beissen"
          + (f" – stumm: {stumm}" if stumm else ""))
    return 0 if not stumm else 1


if __name__ == "__main__":
    sys.exit(main())
