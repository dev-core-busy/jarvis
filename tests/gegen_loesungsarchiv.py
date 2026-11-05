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
    ("Klammerzeilen fallen auch ohne Tool-Syntax weg", "backend/llm.py",
     "if rest == text and ohne_marken == text:", "if False:"),
    ("keine Reparatur ungueltiger Backslashes", LA,
     "obj = json.loads(_backslashes_reparieren(kern))", "obj = json.loads(kern)"),
    ("Reparatur zerlegt Backslash-Paare", LA,
     'return re.sub(r"\\\\(u[0-9a-fA-F]{4}|.)", ersetzen, s, flags=re.DOTALL)',
     'return re.sub(r"\\\\(?![\\"\\\\\\\\/bfnrtu])", r"\\\\\\\\", s)'),
    ("Reparatur laesst kaputtes \\u stehen", LA,
     'return re.sub(r"\\\\(u[0-9a-fA-F]{4}|.)", ersetzen, s, flags=re.DOTALL)',
     'return re.sub(r"\\\\(.)", lambda m: m.group(0) if m.group(1) in \'"\\\\/bfnrtu\' else "\\\\\\\\" + m.group(1), s, flags=re.DOTALL)'),
    ("Liste wird wieder Python-Text", LA,
     "    if isinstance(wert, list):\n        if not all(",
     "    if False:\n        if not all("),
    ("Objekt wird wieder Python-Text", LA,
     "    if isinstance(wert, dict):\n        return \"\"\n", ""),
    ("Liste mit Objekten wird Python-Text", LA,
     "        if not all(isinstance(z, (str, int, float)) for z in wert):\n            return \"\"\n", ""),
    ("vorhandene Nummern werden doppelt", LA,
     "if len(zeilen) < 2 or any(_AUFZAEHLUNG_RE.match(z) for z in zeilen):",
     "if len(zeilen) < 2:"),
    ("Fehlergrund geht verloren", LA,
     '+ "; ".join(dict.fromkeys(gruende)))', '+ "")'),
    ("Fehlergrund je Versuch wiederholt", LA,
     '"; ".join(dict.fromkeys(gruende))', '"; ".join(gruende)'),
    ("Pflichtfeld-Grund nennt die Felder nicht", LA,
     'return None, "Pflichtfeld leer: " + ", ".join(leer)', 'return None, "Pflichtfeld leer"'),
    ("Heilung: Trockenlauf schreibt", LA,
     'if anwenden and erg["geheilt"]:', 'if erg["geheilt"]:'),
    ("Heilung: ohne Sicherung", LA,
     "                shutil.copy2(quelle, sicherung)\n", ""),
    ("Heilung: Entwuerfe bleiben alt", LA,
     '                for eid in erg["geheilt"]:\n                    _entwurf_schreiben(eid, stand["eintraege"][eid])\n', ""),
    ("Heilung: Stand wird nicht gespeichert", LA,
     '                    _entwurf_schreiben(eid, stand["eintraege"][eid])\n                _stand_speichern(stand)\n',
     '                    _entwurf_schreiben(eid, stand["eintraege"][eid])\n'),
    ("Heilung: nimmt die Sperre nicht", LA,
     '        if sperre is None:\n            raise LaufAktiv("Ein Lauf ist aktiv – es wurde nichts geschrieben.")\n', ""),
    ("Heilung: gibt die Sperre nicht frei", LA,
     "        if sperre is not None:\n            _sperre_frei(sperre)\n", "        pass\n"),
    ("Heilung: kaputte Sperrdatei wird uebergangen", LA,
     '            raise ArchivFehler(f"Sperrdatei nicht nutzbar: {e}") from e\n', "            sperre = os.open(os.devnull, os.O_RDONLY)\n"),
    ("Lauf: nimmt die Sperre nicht", LA,
     "    try:\n        sperre = _sperre_nehmen()\n    except OSError as e:\n        # Fail-open",
     "    try:\n        sperre = -1\n    except OSError as e:\n        # Fail-open"),
    ("Lauf: startet trotz belegter Sperre", LA,
     '    if sperre is None:\n        # Bewusst NICHT', '    if sperre is None:\n        sperre = -1\n    if False:\n        # Bewusst NICHT'),
    ("Lauf: Abweisung steht als Erfolg im Protokoll", LA,
     '"grund": "Fehler: Der Bestand wird gerade geheilt', '"grund": "Der Bestand wird gerade geheilt'),
    ("Lauf: kaputte Sperrdatei stoppt ihn", LA,
     '        print(f"[Lösungsarchiv] Sperrdatei nicht nutzbar: {e}", flush=True)\n        sperre = -1\n',
     '        return {"ok": False, "grund": "Sperrdatei"}\n'),
    ("Lauf: gibt die Sperre nicht frei", LA,
     "        if sperre >= 0:\n            _sperre_frei(sperre)\n", ""),
    ("Sperre als Merkdatei statt flock (ueberlebt kill -9)", LA,
     "        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n", "        pass\n"),
    ("Heilung: nur das Feld Loesung", LA,
     'for feld, deckel in (("problem", MAX_PROBLEM), ("loesung", MAX_LOESUNG)):',
     'for feld, deckel in (("loesung", MAX_LOESUNG),):'),
    ("Heilung: Unlesbares wird geleert", LA,
     "            if not neu:\n                if eid not in unlesbar:\n                    unlesbar.append(eid)\n                continue\n", ""),
    ("Heilung: jede eckige Klammer gilt als Liste", LA,
     'if not alt.strip().startswith(_LISTEN_ANFANG):', 'if not alt.strip().startswith("["):'),
    ("Heilungsskript schreibt ohne Schalter", "deploy/loesungsarchiv_heilen.py",
     'arg.add_argument("--anwenden", action="store_true",', 'arg.add_argument("--anwenden", action="store_false",'),
    ("Heilungsskript: Lauf aktiv zaehlt als Erfolg", "deploy/loesungsarchiv_heilen.py",
     '    except la.LaufAktiv as e:\n        print(f"ABBRUCH: {e}")\n        return 3\n',
     '    except la.LaufAktiv as e:\n        print(f"ABBRUCH: {e}")\n        return 0\n'),
    ("Heilungsskript: Trockenlauf verschweigt den Lauf", "deploy/loesungsarchiv_heilen.py",
     '            if la.sperre_belegt():\n', '            if False:\n'),
    ("Heilungsskript stellt wieder ein Token aus", "deploy/loesungsarchiv_heilen.py",
     'def main() -> int:\n', 'def _token():\n    from backend import main as M\n    return M.generate_token("jarvis")\n\n\ndef main() -> int:\n'),
    ("Abbruch: Speichern ohne Schild", LA,
     "        await asyncio.shield(arbeit)\n", "        await arbeit\n"),
    ("Abbruch wartet nicht auf den Speicher-Thread", LA,
     "        await asyncio.gather(arbeit, return_exceptions=True)\n        raise\n", "        raise\n"),
    ("Speichern je Ticket ungeschuetzt", LA,
     "\n                await _sichern(stand)\n",
     "\n                await asyncio.to_thread(_stand_gesperrt_speichern, stand)\n"),
    ("Analyse-Fenster nur halb genutzt", LA,
     "while len(vorlauf) < PARALLEL and not _stopp_angefordert:",
     "while len(vorlauf) < 2 and not _stopp_angefordert:"),
    ("Beenden bricht den Lauf nicht ab", LA,
     "    aufgabe.cancel()\n    await asyncio.wait", "    await asyncio.wait"),
    ("Beenden wartet nicht auf die Meldung", LA,
     "    await asyncio.wait({aufgabe}, timeout=deckel)\n", ""),
    ("Beenden ohne Deckel", LA,
     "await asyncio.wait({aufgabe}, timeout=deckel)", "await asyncio.wait({aufgabe})"),
    ("Lauf merkt sich seine Aufgabe nicht", LA,
     "    _lauf_task = asyncio.current_task()\n", ""),
    ("Beenden haelt eine erledigte Aufgabe fuer laufend", LA,
     "if aufgabe is None or aufgabe.done():", "if aufgabe is None:"),
    ("Abschalt-Hook ruft das Beenden nicht", "backend/main.py",
     "        if await loesungsarchiv.beim_beenden():\n", "        if False:\n"),
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
     "\n                await _sichern(stand)\n",
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
