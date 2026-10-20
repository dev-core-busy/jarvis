"""Update-Verlauf: wann wurde von welchem Code-Stand auf welchen gewechselt.

WARUM ES DAS GIBT (2026-10-20): Es gab kein Protokoll ueber Software-Updates –
die Anzeige kannte nur "gibt es etwas Neues". Wer wissen wollte, seit wann ein
Verhalten da ist, musste im Journal nach Neustarts suchen.

ZWEI EINTRAGSARTEN, MIT ABSICHT:

* ``stand_geaendert`` – beim DIENSTSTART, wenn der Code-Stand (HEAD) ein
  anderer ist als beim letzten Start. Das erfasst JEDEN Weg: den Knopf in der
  Oberflaeche, das Auto-Update (ein Agenten-Auftrag, der per Shell ``git pull``
  ausfuehrt und apply_update gar nicht beruehrt) und ein ``git pull`` von Hand.
  Ein Verlauf nur in apply_update haette genau die automatischen Updates
  verpasst.
* ``update_knopf`` – zusaetzlich beim Update ueber die Oberflaeche: WER es
  ausgeloest hat und mit welchem Ergebnis – auch bei einem Fehlschlag, bei dem
  sich der Stand gar nicht aendert und der Start-Eintrag deshalb ausbleibt.

Beim allerersten Start gibt es keinen Vorgaenger; dann steht ``erfasst`` da
(der Ausgangsstand), nicht ein erfundener Wechsel.

Auf dem Server wird nicht committet – HEAD aendert sich nur durch einen Pull
und ist hier deshalb ein brauchbares Merkmal (anders als fuer die Frage "welche
Dateien liegen dort", fuer die md5 massgeblich bleibt).

Aufbewahrung: wie die uebrigen Protokolle (``log_retention``).
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
DATEI = WURZEL / "data" / "logs" / "updates.jsonl"
STAND = WURZEL / "data" / "logs" / "update_stand.json"
COMMITS_MAX = 50
FEHLER_MAX = 400

_lock = threading.Lock()


def _git(*args: str, timeout: int = 15) -> str:
    """git im Projektverzeichnis; leere Zeichenkette bei jedem Fehler."""
    try:
        r = subprocess.run(["git", *args], cwd=str(WURZEL), capture_output=True,
                           text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def stand() -> dict:
    """Aktueller Code-Stand: Hash (kurz/voll), Commit-Datum, Titel."""
    roh = _git("log", "-1", "--format=%H%x1f%h%x1f%cI%x1f%s")
    teile = roh.split("\x1f") if roh else []
    if len(teile) != 4:
        return {"voll": "", "hash": "", "datum": "", "titel": ""}
    return {"voll": teile[0], "hash": teile[1], "datum": teile[2], "titel": teile[3][:200]}


def eintragen(art: str, **felder) -> dict:
    """Ein Ereignis anhaengen (JSON-Zeile). Fehler werden gemeldet, nicht geworfen."""
    jetzt = time.time()
    e = {"ts": int(jetzt), "zeit": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(jetzt)),
         "art": str(art)}
    e.update({k: v for k, v in felder.items() if v not in (None, "")})
    with _lock:
        try:
            DATEI.parent.mkdir(parents=True, exist_ok=True)
            with DATEI.open("a", encoding="utf-8") as f:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        except OSError as fehler:
            print(f"[Update-Verlauf] nicht schreibbar: {fehler}", flush=True)
    return e


def _commits(vorher: str, nachher: str) -> tuple[list[dict], bool]:
    """Commits zwischen zwei Staenden (juengste zuerst) und ob es ein Vorspulen war.

    Ist ``vorher`` kein Vorfahre von ``nachher`` (Historie umgeschrieben, oder
    zurueckgesetzt), gibt es keine sinnvolle Liste – dann leer und False."""
    if subprocess.run(["git", "merge-base", "--is-ancestor", vorher, nachher], cwd=str(WURZEL),
                      capture_output=True).returncode != 0:
        return [], False
    roh = _git("log", "--format=%h%x1f%cI%x1f%s", "-n", str(COMMITS_MAX + 1),
               f"{vorher}..{nachher}")
    aus = []
    for z in roh.splitlines():
        t = z.split("\x1f")
        if len(t) == 3:
            aus.append({"hash": t[0], "datum": t[1], "titel": t[2][:200]})
    return aus, True


def beim_start() -> dict | None:
    """Beim Dienststart: Stand mit dem letzten vergleichen und ggf. eintragen.

    Rueckgabe: der geschriebene Eintrag oder None (unveraendert / kein git)."""
    jetzt = stand()
    if not jetzt["voll"]:
        return None
    try:
        vorher = json.loads(STAND.read_text(encoding="utf-8")).get("voll", "")
    except (OSError, ValueError):
        vorher = ""
    if vorher == jetzt["voll"]:
        return None
    if not vorher:
        e = eintragen("erfasst", nachher=jetzt["hash"], titel=jetzt["titel"], datum=jetzt["datum"])
    else:
        commits, vorgespult = _commits(vorher, jetzt["voll"])
        e = eintragen("stand_geaendert", vorher=vorher[:9], nachher=jetzt["hash"],
                      titel=jetzt["titel"], datum=jetzt["datum"],
                      anzahl=len(commits) if vorgespult else None,
                      gekappt=len(commits) > COMMITS_MAX or None,
                      vorgespult=vorgespult, commits=commits[:COMMITS_MAX])
    try:
        STAND.parent.mkdir(parents=True, exist_ok=True)
        tmp = STAND.with_suffix(".tmp")
        tmp.write_text(json.dumps(jetzt, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, STAND)
    except OSError as fehler:
        print(f"[Update-Verlauf] Stand nicht speicherbar: {fehler}", flush=True)
    return e


def knopf(benutzer: str, vorher: dict, ergebnis: dict) -> dict:
    """Update ueber die Oberflaeche: Ausloeser und Ergebnis festhalten."""
    nach = stand()
    fehler = str(ergebnis.get("error") or "")
    return eintragen(
        "update_knopf", benutzer=benutzer, ok=bool(ergebnis.get("ok")),
        vorher=vorher.get("hash", ""), nachher=nach.get("hash", ""),
        fehler=(fehler[:FEHLER_MAX] + ("…" if len(fehler) > FEHLER_MAX else "")) or None,
        broker_neustart=bool(ergebnis.get("broker_betroffen")) or None,
        grund=next((k for k in ("signatur", "historie", "konflikt", "license")
                    if ergebnis.get(k)), None))


def lesen(limit: int = 200) -> list[dict]:
    """Juengste Eintraege zuerst."""
    if not DATEI.exists():
        return []
    aus = []
    for z in reversed(DATEI.read_text(encoding="utf-8", errors="replace").splitlines()):
        if not z.strip():
            continue
        try:
            aus.append(json.loads(z))
        except ValueError:
            continue
        if len(aus) >= limit:
            break
    return aus


def prune_older_than(cutoff_ts: float) -> int:
    """Eintraege vor ``cutoff_ts`` entfernen (Aufbewahrungsfrist). Anzahl zurueck."""
    if cutoff_ts is None or not DATEI.exists():
        return 0
    with _lock:
        zeilen = DATEI.read_text(encoding="utf-8", errors="replace").splitlines()
        bleiben, weg = [], 0
        for z in zeilen:
            if not z.strip():
                continue
            try:
                ts = json.loads(z).get("ts")
            except ValueError:
                ts = None
            # Ohne Zeitstempel kein Altersbeweis: bleibt stehen (fail-closed)
            if ts is not None and ts < cutoff_ts:
                weg += 1
            else:
                bleiben.append(z)
        if weg:
            tmp = DATEI.with_suffix(".jsonl.tmp")
            tmp.write_text(("\n".join(bleiben) + "\n") if bleiben else "", encoding="utf-8")
            os.replace(tmp, DATEI)
        return weg
