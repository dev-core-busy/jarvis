#!/usr/bin/env python3
"""Gegenprobe zu ``tests/test_dienst_zugang.py``: beisst der Waechter?

Jede Probe verbiegt EINE Stelle und zaehlt die FAILs. Gearbeitet wird in einer
KOPIE von ``backend/`` und dem Waechter in einem Wegwerf-Verzeichnis – der
Arbeitsbaum wird nie angefasst. Grund (2026-11-17): eine parallele Sitzung
fuehrte zur selben Zeit eine eigene Gegenprobe auf ``backend/loesungsarchiv.py``
aus; ein Sichern-Sabotieren-Zuruecklegen im gemeinsamen Baum haette deren
Aenderungen (oder deren Sicherung) ueberschreiben koennen.

Exit 0 = alle Proben beissen, 1 = mindestens eine stumm, 2 = Basis nicht gruen.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEST = "tests/test_dienst_zugang.py"

PROBEN = [
    ("Jira-Dienstclient ignoriert das Feld", "backend/jira_accounts.py",
     '    eigen = roh.strip() if isinstance(roh, str) else ""\n    if eigen:\n        c = JiraClient(',
     '    eigen = ""\n    if eigen:\n        c = JiraClient('),
    ("Confluence-Dienstclient ignoriert das Feld", "backend/confluence_accounts.py",
     '    eigen = roh.strip() if isinstance(roh, str) else ""\n    if eigen:\n        c = ConfluenceClient(',
     '    eigen = ""\n    if eigen:\n        c = ConfluenceClient('),
    ("Jira-Dienstclient darf schreiben", "backend/jira_accounts.py",
     'c = JiraClient({"base_url": basis_url(), "api_token": eigen})',
     'c = JiraClient({"base_url": basis_url(), "api_token": eigen}, schreiben=True)'),
    ("Zustand gibt den Token heraus", "backend/dienst_zugang.py",
     '        "token_gesetzt": eigen,\n',
     '        "token_gesetzt": eigen,\n        "token": cfg.get(e["feld"]),\n'),
    ("Formpruefung des Tokens raus", "backend/dienst_zugang.py",
     '    if not _TOKEN_RE.match(tok):', '    if False:'),
    ("Speichern schreibt die ganze Config", "backend/dienst_zugang.py",
     '    sm.update_skill_config(e["skill"], {e["feld"]: tok})',
     '    sm.update_skill_config(e["skill"], {**_cfg(e["skill"]), e["feld"]: tok})'),
    ("Adresswechsel setzt leer statt None", "backend/dienst_zugang.py",
     '        body[e["feld"]] = None\n', '        body[e["feld"]] = ""\n'),
    ("Adresswechsel tut nichts", "backend/dienst_zugang.py",
     '    if not isinstance(body, dict) or "base_url" not in body:\n        return []',
     '    return []'),
    ("update_skill_config ruft den Schritt nicht", "backend/main.py",
     '        dienst_entfernt = _dz.bei_adresswechsel(name, body, gespeichert)',
     '        dienst_entfernt = []'),
    ("ticket_laden ignoriert den Client", "backend/jira_assist.py",
     '    c = client if client is not None else _client(user)', '    c = _client(user)'),
    ("Loesungsarchiv reicht den Client nicht durch", "backend/loesungsarchiv.py",
     '            return await jira_assist.ticket_laden(key, user, client=_c)',
     '            return await jira_assist.ticket_laden(key, user)'),
    ("Loesungsarchiv baut wieder selbst", "backend/loesungsarchiv.py",
     '    c = dienst_zugang.client("loesungsarchiv")',
     '    from backend.jira_client import JiraClient\n    c = JiraClient()'),
    ("Abgleich nimmt wieder den Sammelzugang", "backend/confluence_abgleich.py",
     '        client = dienst_zugang.client("confluence_einbindung")',
     '        client = dienst_zugang.client("x") if False else None'),
    ("_cfb_aktiv misst wieder den Sammelzugang", "backend/main.py",
     'bool(_dz.client("confluence_einbindung").configured))',
     'bool(_confluence_client().configured))'),
]


def zahl(ausgabe: str) -> tuple[int, int] | None:
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", ausgabe)
    return (int(m.group(1)), int(m.group(2))) if m else None


def lauf(wurzel: Path) -> tuple[int, str]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, str(wurzel / TEST)], capture_output=True, text=True,
                       timeout=300, env=env, cwd=str(wurzel))
    return r.returncode, r.stdout + r.stderr


def main() -> int:
    dateien = {p[1] for p in PROBEN}
    with tempfile.TemporaryDirectory(prefix="gegen_dzg_") as tmp:
        wurzel = Path(tmp)
        shutil.copytree(ROOT / "backend", wurzel / "backend",
                        ignore=shutil.ignore_patterns("__pycache__"))
        (wurzel / "tests").mkdir()
        shutil.copy2(ROOT / TEST, wurzel / TEST)
        rc, aus = lauf(wurzel)
        b = zahl(aus)
        if rc != 0 or not b or b[1] != 0:
            print("ABBRUCH: Basislauf nicht gruen – keine Gegenprobe deutbar")
            print(aus[-1500:])
            return 2
        print(f"Basis: {b[0]} OK, 0 FAIL")
        stumm = 0
        for name, rel, alt, neu in PROBEN:
            ziel = wurzel / rel
            orig = ziel.read_text(encoding="utf-8")
            if orig.count(alt) != 1:
                print(f"  TRIFFT NICHT  {name} ({orig.count(alt)} Treffer)")
                stumm += 1
                continue
            ziel.write_text(orig.replace(alt, neu), encoding="utf-8")
            try:
                rc, aus = lauf(wurzel)
            finally:
                ziel.write_text(orig, encoding="utf-8")
            e = zahl(aus)
            if e and e[1] > 0:
                print(f"  beisst ({e[1]} FAIL)  {name}")
            elif rc == 2 or not e:
                print(f"  BRICHT AB (Exit {rc}, keine Bilanz)  {name}")
                stumm += 1
            else:
                print(f"  STUMM  {name}")
                stumm += 1
        print(f"\n{len(PROBEN) - stumm} von {len(PROBEN)} Proben beissen")
        assert dateien  # die Kopie deckt jede Datei ab (sie umfasst ganz backend/)
        return 0 if stumm == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
