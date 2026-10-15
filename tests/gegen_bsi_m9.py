#!/usr/bin/env python3
"""Gegenprobe zu tests/test_bsi_m9.py: beisst der Waechter?

Jede Probe dreht EINEN Teil von M9 zurueck (Python-Ersetzung ganzer Zeilen),
laesst den Waechter laufen und erwartet mindestens einen FAIL. Vorher gruener
Basislauf, danach Byte-Gleichheit aller Dateien per md5, ohne Bytecode, mit
Laufmarke (abgeschossener Lauf wird beim naechsten Start zurueckgenommen).

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKE = ROOT / "tests" / ".gegen_bsi_m9.laufmarke"

LF = "backend/loeschfristen.py"
CL = "backend/conv_log.py"
LR = "backend/log_retention.py"
SL = "backend/sicherheits_log.py"
MA = "backend/main.py"
LE = "backend/learning.py"
AG = "backend/agent.py"
KJ = "frontend/js/knowledge.js"

PROBEN = [
    ("Umgebung schlaegt Einstellung", LF,
     "    for wert in (_einstellung(art), os.environ.get(env)):\n",
     "    for wert in (os.environ.get(env), _einstellung(art)):\n"),
    ("0 gilt als 'nicht gesetzt' (Falsyness)", LF,
     "        if n is not None:\n            return _begrenzen(art, n)\n",
     "        if n:\n            return _begrenzen(art, n)\n"),
    ("Chat-Vorgabe falsch", LF,
     '    "chats": ("JARVIS_CHAT_TAGE", 180, 1),\n', '    "chats": ("JARVIS_CHAT_TAGE", 365, 1),\n'),
    ("Sitzung ohne meta wird geloescht", LF,
     "                continue           # unlesbar: kein Altersbeweis -> stehen lassen\n",
     "                zuletzt = 1.0\n"),
    ("Nachricht ohne Zeitstempel faellt", LF,
     "            rest = [m for m in daten if (_ts_sekunden(m) or cut) >= cut]\n",
     "            rest = [m for m in daten if (_ts_sekunden(m) or 0) >= cut]\n"),
    ("ms nicht in Sekunden umgerechnet", LF,
     "    return ts / 1000.0 if ts > 1e11 else float(ts)\n", "    return float(ts)\n"),
    # "setzen ohne Grenzpruefung (n < 0)" entfaellt bewusst: eine negative Zahl
    # faengt ZUSAETZLICH die Untergrenzen-Pruefung (n < Minimum) – zwei
    # Schranken, die Probe waere ohne Wirkung (Register: Doppelschranke).
    ("Prompts: Rumpf bleibt", CL,
     "            _remove_body(e.get(\"id\"))\n            t = str(e.get(\"task\") or \"\")\n",
     "            t = str(e.get(\"task\") or \"\")\n"),
    ("Prompts: Aufgabentext nicht gekuerzt", CL,
     '            e["task"] = t if len(t) <= GEKUERZT_LAENGE else t[:GEKUERZT_LAENGE] + "…"\n', ''),
    ("Prompts: Altbestand bleibt", CL,
     "            if alt.exists() and alt.stat().st_mtime < cutoff_ts:\n", "            if False:\n"),
    ("run_all ohne Chats", LR,
     "        erg = loeschfristen.chats_bereinigen()\n", "        erg = {\"dauerhaft\": True}\n"),
    ("run_all ohne Prompts", LR,
     '            removed["volle_prompts"] = int(conv_log.prompts_entfernen(_cut_prompts) or 0)\n',
     '            removed["volle_prompts"] = 0\n'),
    ("Protokollfrist wieder nur aus Umgebung", LR,
     '    return loeschfristen.tage("protokoll")\n', '    return int(os.environ.get(_ENV_VAR) or DEFAULT_RETENTION_DAYS)\n'),
    ("Sicherheitsfrist ohne Einstellung", SL,
     '        return loeschfristen.tage("sicherheit")\n', '        raise ImportError\n'),
    ("Direktnachrichten nicht angemeldet", MA,
     "_log_retention_m9.ZUSATZ_CHATS.append(_uc_frist_anwenden)\n", "\n"),
    ("Lernnotiz: Pfad nicht auf LEARNED_DIR begrenzt", MA,
     "        ziel.relative_to(LEARNED_DIR.resolve())\n    except ValueError:\n        return JSONResponse({\"error\": \"Keine Lernnotiz\"}, status_code=403)\n",
     "        pass\n    except ValueError:\n        return JSONResponse({\"error\": \"Keine Lernnotiz\"}, status_code=403)\n"),
    ("Gedaechtnis: Sicherung behaelt den Eintrag", MA,
     "            _sh_m9.copy2(pfad, bak)\n", "            pass\n"),
    ("Gedaechtnis-Endpunkt fuer Admins", MA,
     "async def gedaechtnis_lesen(user: str = Depends(require_auth)):\n",
     "async def gedaechtnis_lesen(user: str = Depends(require_local_auth)):\n"),
    ("Herkunft nicht geschrieben", LE,
     "        f\"{HERKUNFT_ZEILE}{benutzer or 'unbekannt'}\\n\\n\"\n", "        f\"\\n\"\n"),
    ("Agent reicht Benutzer nicht durch", AG,
     '                                benutzer=getattr(self, "_current_username", "") or "",\n', ''),
    ("Loesch-Knopf wieder am alten Endpunkt", KJ,
     "            const resp = await fetch('/api/knowledge/learned', {\n                method: 'DELETE',\n",
     "            const resp = await fetch('/api/knowledge/files', {\n                method: 'DELETE',\n"),
]

DATEIEN = [LF, CL, LR, SL, MA, LE, AG, KJ, "tests/test_bsi_m9.py"]

WAECHTER = [
    (["python3", "tests/test_bsi_m9.py"], r"Ergebnis: (\d+) OK, (\d+) FAIL"),
]


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def lauf():
    """Alle Waechter; Summe der FAILs. -1 = einer konnte nicht laufen."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    summe = 0
    for cmd, muster in WAECHTER:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                               cwd=str(ROOT), env=env)
        except subprocess.TimeoutExpired:
            return -1, "timeout " + cmd[-1]
        m = re.search(muster, r.stdout)
        if r.returncode == 2 or not m:
            return -1, f"{cmd[-1]} rc={r.returncode} {r.stdout.strip()[-160:]}"
        summe += int(m.group(2))
    return summe, 0


def zuruecknehmen():
    """Rueckstand eines abgeschossenen Laufs zuruecknehmen (Laufmarke)."""
    if not MARKE.exists():
        return
    try:
        alt = json.loads(MARKE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        print("ABBRUCH: Laufmarke unlesbar – Arbeitsbaum von Hand pruefen")
        sys.exit(2)
    for d, hexinhalt in alt.items():
        (ROOT / d).write_bytes(bytes.fromhex(hexinhalt))
    MARKE.unlink()
    print("Rueckstand eines abgebrochenen Laufs zurueckgenommen.")


def main() -> int:
    zuruecknehmen()
    if {p[1] for p in PROBEN} - set(DATEIEN):
        print("ABBRUCH: Probe fasst eine nicht gesicherte Datei an")
        return 2
    sicherung = {d: (ROOT / d).read_bytes() for d in DATEIEN}
    vorher = {d: md5(d) for d in DATEIEN}

    fails, rc = lauf()
    if fails != 0:
        print("ABBRUCH: Basislauf nicht gruen (FAIL=%s, %s)" % (fails, rc))
        return 2
    print("Basislauf gruen.\n")

    MARKE.write_text(json.dumps({d: b.hex() for d, b in sicherung.items()}), encoding="utf-8")
    beissen = 0
    try:
        for name, datei, alt, neu in PROBEN:
            pfad = ROOT / datei
            text = pfad.read_text(encoding="utf-8")
            if text.count(alt) != 1:
                print("  ???  %s – Anker %dx gefunden" % (name, text.count(alt)))
                continue
            pfad.write_text(text.replace(alt, neu, 1), encoding="utf-8")
            try:
                fails, rc = lauf()
            finally:
                pfad.write_bytes(sicherung[datei])
            if fails > 0:
                beissen += 1
                print("  BISS %-62s %d FAIL" % (name, fails))
            elif fails < 0:
                print("  ABBR %-62s Waechter konnte nicht laufen (%s)" % (name, rc))
            else:
                print("  ZAHN %-62s 0 FAIL – beisst NICHT" % name)
    finally:
        for d, inhalt in sicherung.items():
            (ROOT / d).write_bytes(inhalt)
        if MARKE.exists():
            MARKE.unlink()

    nachher = {d: md5(d) for d in DATEIEN}
    if nachher != vorher:
        print("\nABBRUCH: Dateien nach der Probe nicht byte-gleich: %s"
              % [d for d in DATEIEN if nachher[d] != vorher[d]])
        return 2
    print("\n%d/%d Proben beissen (Dateien byte-gleich wiederhergestellt)"
          % (beissen, len(PROBEN)))
    return 0 if beissen == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
