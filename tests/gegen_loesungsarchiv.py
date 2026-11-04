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
     "\n                    zahl[\"fehler\"] += 1\n",
     "\n                    zahl[\"fehler\"] += 1\n                    stand[\"verarbeitet\"][t[\"key\"]] = {}\n"),
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
    ("Deckel je Lauf ignoriert die Einstellung", LA,
     'dict(stand["verarbeitet"]), _je_lauf(st))', 'dict(stand["verarbeitet"]), JE_LAUF_VORGABE)'),
    ("geaenderte Tickets werden nicht erneut ausgewertet", LA,
     "if wieder and not geaendert(verarbeitet[k], upd):", "if wieder:"),
    ("Altbestand ohne 'updated' gilt immer als geaendert", LA,
     '        try:\n            alt = float((v or {}).get("wann"))\n        except (TypeError, ValueError):\n            return False\n',
     "        return True\n"),
    ("Jiras 'updated' wird nicht gemerkt", LA,
     'merken = {"wann": jetzt, "updated": str(updated or "")}', 'merken = {"wann": jetzt}'),
    ("alte Zuordnung wird nicht geloest", LA,
     "        _ticket_loesen(stand, alt_id, key, weg)\n\n    if treffer:", "        pass\n\n    if treffer:"),
    ("alte Fassung wird als Kandidat angeboten", LA,
     "pool = {i: e for i, e in eintraege.items() if not (alt_allein and i == alt_id)}",
     "pool = dict(eintraege)"),
    ("Eintrag ohne Tickets bleibt stehen", LA,
     "    if not rest:\n        datei", "    if False:\n        datei"),
    ("entfernte Datei stoesst keinen Indexlauf an", LA,
     '    sch["entfernt"] += len(weg)\n', ""),
    ("Tickets je Lauf ohne Obergrenze", LA,
     "    if not 1 <= je_lauf <= JE_LAUF_MAX:\n", "    if not 1 <= je_lauf:\n"),
    ("Schranke laeuft nur am Ende des Laufs", LA,
     "    sch0 = await asyncio.to_thread(schranke, stand, st)\n",
     '    sch0 = {"veroeffentlicht": 0, "aktualisiert": 0, "entfernt": 0}\n'),
    ("Schranke am Ende nimmt die Schwelle vom Laufbeginn", LA,
     '        st_ende = {**st, "schwelle": jetzt["schwelle"], "gruppen": jetzt["gruppen"]}\n',
     "        st_ende = st\n"),
    ("Speichern je Ticket haelt die Sperre ueber ein await", LA,
     "\n                await asyncio.to_thread(_stand_gesperrt_speichern, stand)\n",
     "\n                with _STAND_SPERRE:\n                    await asyncio.to_thread(_stand_speichern, stand)\n"),
    ("'Lauf beenden' wird im Lauf nicht beachtet", LA,
     "                if _stopp_angefordert and not analyse_fertig.done():\n                    break\n", ""),
    ("'Lauf beenden' verwirft fertige Analysen", LA,
     "if _stopp_angefordert and not analyse_fertig.done():", "if _stopp_angefordert:"),
    ("nach 'Lauf beenden' werden neue Analysen angefangen", LA,
     "while len(vorlauf) < PARALLEL and not _stopp_angefordert:", "while len(vorlauf) < PARALLEL:"),
    ("laufende Analysen werden nicht abgebrochen", LA,
     "            for _, f in vorlauf:\n                f.cancel()\n",
     "            for _, f in vorlauf:\n                pass\n"),
    ("Analysen wieder seriell", LA, "\nPARALLEL = 4\n", "\nPARALLEL = 1\n"),
    ("Analyse-Fenster ohne Grenze", LA,
     "while len(vorlauf) < PARALLEL and not _stopp_angefordert:",
     "while len(vorlauf) < 10 ** 6 and not _stopp_angefordert:"),
    ("Denken bleibt an", LA,
     "        provider.denken_aus = True\n    return provider, modell",
     "        pass\n    return provider, modell"),
    ("Zeiten fehlen im Grund", LA,
     "    if zeile:\n        grund += \" · \" + zeile\n", "    if zeile:\n        pass\n"),
    ("Zeiten fehlen im Ergebnis", LA,
     '"zeiten": zeiten.als_dict(wanduhr, ausgewertet)}', '"zeiten": {}}'),
    ("Aehnlichkeit rechnet im Event-Loop", LA,
     "kand = await asyncio.to_thread(kandidaten, analyse, pool, vektoren)",
     "kand = kandidaten(analyse, pool, vektoren)"),
    ("'Lauf beenden' wirkt in den naechsten Lauf nach", LA,
     "        # eine Marke kann also nicht in den naechsten Lauf hinueberreichen.\n        _stopp_angefordert = False\n",
     "        # eine Marke kann also nicht in den naechsten Lauf hinueberreichen.\n        pass\n"),
    ("offene Zahl vergisst die nicht angefangenen", LA,
     "    rest = max(0, offen - ausgewertet)\n", "    rest = max(0, offen - len(neu))\n"),
    ("anhalten() ohne Lauf meldet Erfolg", LA,
     "    if not _lauf_aktiv:\n        return False\n    _stopp_angefordert = True\n",
     "    _stopp_angefordert = True\n"),
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
