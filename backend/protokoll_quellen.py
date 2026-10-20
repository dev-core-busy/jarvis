"""Lesehilfen fuer die Protokoll-Ansichten unter Einstellungen -> Protokolle.

Hier steht nur das ZERLEGEN vorhandener Ablagen; Rechte und Transport stehen
in ``main.py`` (``/api/logs/*``), die Ablagen selbst gehoeren ihren Modulen.
Eigenes Modul, damit die Zerlegung ohne FastAPI und ohne Broker pruefbar ist.

Alle Funktionen lesen nur und werfen nicht: eine unlesbare Ablage ist eine
AUSKUNFT ("nicht lesbar: …"), kein 500er.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
CODE_FIXES = WURZEL / "data" / "learnings" / "code_fixes.log"
ABHAENGIGKEITEN = Path(os.environ.get("JARVIS_ABH_ZUSTAND",
                                      str(WURZEL / "data" / "logs" / "abhaengigkeiten.json")))

# ── Selbstkorrekturen des Agenten (tools/reflection.py) ─────────────────────
# Format je Eintrag (reflection.py, Abschnitt "Aenderung loggen"):
#   ## Code-Fix: <datei>
#   Datum: <YYYY-MM-DD HH:MM>
#   Grund: <text>
#   Backup: <name>
#   Deployt nach: <ziele>
_FELDER = {"Datum": "datum", "Grund": "grund", "Backup": "backup", "Deployt nach": "deployt"}


def code_fixes_zerlegen(text: str) -> list[dict]:
    """Bloecke -> Eintraege, JUENGSTE zuerst. Felder, die fehlen, bleiben leer."""
    aus: list[dict] = []
    akt: dict | None = None
    for z in (text or "").splitlines():
        if z.startswith("## Code-Fix:"):
            akt = {"datei": z[len("## Code-Fix:"):].strip(), "datum": "", "grund": "",
                   "backup": "", "deployt": ""}
            aus.append(akt)
            continue
        if akt is None or ":" not in z:
            continue
        k, _, v = z.partition(":")
        feld = _FELDER.get(k.strip())
        if feld and not akt[feld]:
            akt[feld] = v.strip()
    aus.reverse()
    return aus


def code_fixes_lesen(limit: int = 200) -> dict:
    if not CODE_FIXES.exists():
        # Kein Fehler: die Datei entsteht erst mit der ersten Korrektur
        # (auf DEV und ECHT gab es am 2026-10-20 noch keine).
        return {"ok": True, "vorhanden": False, "eintraege": [], "anzahl": 0}
    try:
        text = CODE_FIXES.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"ok": False, "error": f"nicht lesbar: {e}"}
    alle = code_fixes_zerlegen(text)
    return {"ok": True, "vorhanden": True, "anzahl": len(alle),
            "eintraege": alle[:max(1, min(int(limit or 200), 1000))]}


# ── Zustand der Abhaengigkeitspruefung (backend/abhaengigkeiten.py) ─────────
def abhaengigkeiten_lesen() -> dict:
    """Der zuletzt geschriebene Zustand samt Dateialter.

    Die Datei schreibt ``abhaengigkeiten.py`` beim Start und danach taeglich.
    ``alter_s`` sagt, wie frisch die Auskunft ist – eine Pruefung von vor drei
    Wochen ist eine andere Aussage als eine von heute frueh."""
    if not ABHAENGIGKEITEN.exists():
        return {"ok": True, "vorhanden": False}
    try:
        zustand = json.loads(ABHAENGIGKEITEN.read_text(encoding="utf-8"))
        alter = int(time.time() - ABHAENGIGKEITEN.stat().st_mtime)
    except (OSError, ValueError) as e:
        return {"ok": False, "error": f"nicht lesbar: {e}"}
    if not isinstance(zustand, dict):
        return {"ok": False, "error": "unerwartetes Format"}
    return {"ok": True, "vorhanden": True, "alter_s": alter, "zustand": zustand}


# ── Dienst-Journal (Broker-Op journal_lesen, Format short-iso) ──────────────
_JOURNAL = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:?\d\d)\s+\S+\s+([^:\[]+)(?:\[\d+\])?:\s?(.*)$")
EINHEITEN = {"jarvis": "jarvis.service", "broker": "jarvis-broker.service",
             "whatsapp": "whatsapp-bridge.service"}
STUFEN = {"": "", "warnung": "warning", "fehler": "err"}
ZEITRAEUME = {"1h": "-1h", "24h": "-24h", "7d": "-7d"}


def journal_zerlegen(text: str) -> list[dict]:
    """short-iso-Zeilen -> {zeit, prozess, text}. Fortsetzungszeilen (Tracebacks
    ohne eigenen Zeitstempel) haengen am VORIGEN Eintrag – sonst stuenden die
    Zeilen eines Tracebacks als lauter namenlose Eintraege da."""
    aus: list[dict] = []
    for z in (text or "").splitlines():
        if not z.strip() or z.startswith("-- "):
            continue                      # "-- No entries --" / "-- Boot …"
        m = _JOURNAL.match(z)
        if m:
            aus.append({"zeit": m.group(1), "prozess": m.group(2).strip(), "text": m.group(3)})
        elif aus:
            aus[-1]["text"] += "\n" + z
        else:
            aus.append({"zeit": "", "prozess": "", "text": z})
    return aus
