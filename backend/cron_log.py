"""Protokoll der zeitgesteuerten Auftraege (Cron) – ein Eintrag je Lauf.

WARUM ES DAS GIBT (Vorgabe 2026-09-28: "bei den Tasks -> Cron-Aufgaben fehlen
logs"): bis hierher kannte ein Auftrag nur ``last_run`` und ``last_result`` –
den LETZTEN Lauf, auf 500 Zeichen gekuerzt, und in der Liste auf 80. Ob ein
naechtlicher Auftrag gestern gescheitert ist und heute wieder lief, war nicht
mehr zu sehen: der zweite Lauf ueberschrieb den ersten.

ABLAGE: ``data/logs/cron/<job_id>.jsonl`` – EINE Datei je Auftrag. Der
Wissensabgleich laeuft alle fuenf Minuten (288 Eintraege am Tag); in einer
gemeinsamen Datei muesste jede Anzeige eines seltenen Auftrags durch
zehntausende fremde Zeilen lesen. ``data/logs`` steht in ``SENSITIVE_PATHS``
und ``PRIVATE_DIRS`` (backend/sandbox.py): die Ergebnisse von Agentenlaeufen
koennen alles enthalten, was der Auftrag gelesen hat.

AUFBEWAHRUNG: nur nach ALTER, ueber ``log_retention`` (dieselbe Frist wie die
uebrigen Diagnosespeicher) – ausdruecklich KEINE Stueckzahlgrenze. Der Lauf,
den man nach einem Fehler sucht, ist genau der, den eine Mengengrenze
verdraengt haette.

⚠ DAS PROTOKOLL DARF NIE EINEN LAUF VERHINDERN. Jeder Fehler beim Schreiben
wird gemeldet und verschluckt – ein volles Laufwerk soll den Auftrag nicht
auch noch scheitern lassen.
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

DATEI_MODUS = 0o640
# Deckel je Ergebnis: das Ergebnis eines Agentenlaufs ist ein Antworttext,
# kein Datenstrom. Die Grenze schuetzt nur vor einer entgleisten Ausgabe.
ERGEBNIS_MAX = 20_000

_SPERRE = threading.Lock()


def _ordner() -> Path:
    """Ablageort. Funktion statt Konstante – ein Test biegt ihn um."""
    return Path(__file__).resolve().parent.parent / "data" / "logs" / "cron"


def _datei(job_id: str) -> Path | None:
    """Datei eines Auftrags – oder None fuer eine unbrauchbare Kennung.

    ⚠ Die Kennung wird NICHT bereinigt, sondern abgewiesen: aus "../x" ein
    "x" zu machen, liesse zwei verschiedene Kennungen in DIESELBE Datei
    schreiben (und lesen)."""
    jid = str(job_id or "")
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,100}", jid):
        return None
    return _ordner() / f"{jid}.jsonl"


def ist_fehler(ergebnis: str) -> bool:
    """Ob ein Ergebnistext einen gescheiterten Lauf meldet.

    Die Laeufe liefern Text, keinen Status: der Scheduler selbst schreibt bei
    einer Ausnahme ``Fehler: ...``, ``reminders.deliver`` meldet Probleme
    ebenso."""
    return str(ergebnis or "").lstrip().startswith("Fehler")


def eintragen(job: dict, start: float, ende: float, ergebnis: str,
              ausloeser: str = "zeitplan", von: str = "") -> None:
    """Einen Lauf protokollieren. Wirft NIE (siehe Modulkopf)."""
    try:
        p = _datei((job or {}).get("id") or "")
        if p is None:
            print(f"[Cron-Log] unbrauchbare Kennung {(job or {}).get('id')!r} – "
                  "nicht protokolliert", flush=True)
            return
        text = str(ergebnis or "")
        e = {
            "ts": int(start),
            "ende": int(ende),
            "dauer_s": round(max(0.0, float(ende) - float(start)), 1),
            "ausloeser": ausloeser if ausloeser in ("zeitplan", "manuell") else "zeitplan",
            "von": str(von or ""),
            "label": str((job or {}).get("label") or ""),
            "kind": str((job or {}).get("kind") or "agent"),
            "ok": not ist_fehler(text),
            "ergebnis": text[:ERGEBNIS_MAX],
            "gekuerzt": len(text) > ERGEBNIS_MAX,
        }
        with _SPERRE:
            p.parent.mkdir(parents=True, exist_ok=True)
            neu = not p.exists()
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
            if neu:
                try:
                    os.chmod(p, DATEI_MODUS)
                except Exception:  # noqa: BLE001
                    pass
    except Exception as ex:  # noqa: BLE001
        print(f"[Cron-Log] Lauf nicht protokolliert: {type(ex).__name__}: {ex}", flush=True)


def lesen(job_id: str, limit: int = 50, vor: float | None = None) -> list[dict]:
    """Die Laeufe eines Auftrags, NEUESTE zuerst.

    ``vor``: nur Laeufe, die VOR diesem Zeitpunkt begannen – zum Nachladen
    aelterer Eintraege. Gelesen wird rueckwaerts vom Dateiende: beim
    Wissensabgleich waeren es sonst jedes Mal zehntausende Zeilen fuer die
    obersten fuenfzig.
    """
    p = _datei(job_id)
    if p is None or not p.is_file():
        return []
    limit = max(1, min(int(limit or 50), 500))
    raus: list[dict] = []
    with p.open("rb") as f:
        f.seek(0, os.SEEK_END)
        pos, rest = f.tell(), b""
        block = 64 * 1024
        while pos > 0 and len(raus) < limit:
            lese = min(block, pos)
            pos -= lese
            f.seek(pos)
            puffer = f.read(lese) + rest
            zeilen = puffer.split(b"\n")
            # Der erste Teil eines rueckwaerts gelesenen Blocks ist in der
            # Regel eine angeschnittene Zeile – sie wandert in den naechsten.
            rest = zeilen[0] if pos > 0 else b""
            for z in reversed(zeilen[1:] if pos > 0 else zeilen):
                if not z.strip():
                    continue
                try:
                    e = json.loads(z.decode("utf-8", "replace"))
                except Exception:  # noqa: BLE001
                    continue          # beschaedigte Zeile ueberspringen
                if not isinstance(e, dict):
                    continue
                if vor is not None and float(e.get("ts") or 0) >= float(vor):
                    continue
                raus.append(e)
                if len(raus) >= limit:
                    break
    return raus


def kuerzen(grenze_ts: float) -> int:
    """Eintraege aelter als ``grenze_ts`` aus ALLEN Auftragsprotokollen
    entfernen. Rueckgabe = Anzahl.

    Ein Eintrag OHNE Zeitstempel bleibt stehen: ein fehlendes Datum ist kein
    Altersbeweis (gleiche Regel wie in log_retention). Eine leer gewordene
    Datei wird entfernt – sonst sammelten sich Dateien geloeschter Auftraege.
    """
    ordner = _ordner()
    if not ordner.is_dir():
        return 0
    entfernt = 0
    for p in sorted(ordner.glob("*.jsonl")):
        with _SPERRE:
            behalten, weg = [], 0
            for z in p.read_text(encoding="utf-8", errors="replace").splitlines():
                if not z.strip():
                    continue
                try:
                    ts = float((json.loads(z) or {}).get("ts") or 0)
                except Exception:  # noqa: BLE001
                    behalten.append(z)
                    continue
                if ts and ts < grenze_ts:
                    weg += 1
                else:
                    behalten.append(z)
            if not weg:
                continue
            if not behalten:
                p.unlink()
            else:
                tmp = p.with_suffix(".jsonl.tmp")
                tmp.write_text("\n".join(behalten) + "\n", encoding="utf-8")
                try:
                    os.chmod(tmp, DATEI_MODUS)
                except Exception:  # noqa: BLE001
                    pass
                os.replace(tmp, p)
            entfernt += weg
    return entfernt

