"""Aktivitaetsprotokoll: WER hat WANN WAS an den gemeinsamen Bestaenden geaendert.

WARUM ES DAS GIBT (2026-11-04): Auf ECHT tauchte ein Wissensordner samt
Wissensgruppe auf, und die Frage "wer hat den angelegt?" liess sich nur noch
ueber Zeitstempel und Anmeldungen ERSCHLIESSEN, nicht belegen. Kein Endpunkt
fuer Ordner, Gruppen, Dokumente, Auftraege, Skills oder Profile hielt seinen
Ausloeser fest.

ABGRENZUNG ZUM SICHERHEITSPROTOKOLL (backend/sicherheits_log.py), MIT ABSICHT:
Das Sicherheitsprotokoll ist das BSI-M2-Protokoll (Hash-Kette, syslog, SIEM)
fuer Anmeldungen, Konten und Admin-Eingriffe. "Wer hat Ordner X angelegt" ist
eine Frage zum INHALT; in der Kette waere sie Rauschen, das die wichtigen
Ereignisse verdeckt. Faustregel:
  * aendert sich, WAS ES GIBT          -> nur hier
  * aendert sich, WER WAS DARF         -> hier UND im Sicherheitsprotokoll
    (Art ``rechte_aenderung``; das entscheidet der Aufrufer mit ``rechte=True``,
    siehe ``_aktivitaet`` in main.py).

WAS HINEINGEHOERT: Ereignisse mit benanntem Gegenstand (Ordnerpfad, Gruppen-ID,
Auftragsname), geschrieben AM ENDPUNKT nach dem Erfolg. Eine Middleware kann
das nicht leisten: sie sieht nur den Pfad, nie den Anfragekoerper (dort stehen
Tokens), und damit nie den Namen, nach dem spaeter gesucht wird.

WAS NIE HINEINGEHOERT: Geheimnisse und Inhalte. ``details`` traegt Namen,
Pfade, Anzahlen und Schalterstellungen – keine Kennwoerter, Tokens, Prompts
oder Dokumenttexte. ``_kappen`` begrenzt jeden Wert, damit ein versehentlich
uebergebener Text das Protokoll nicht flutet.

Ein Fehler beim Schreiben wird GEMELDET (Journal), nie geworfen: die
Protokollierung darf die eigentliche Aenderung nicht scheitern lassen, sie
ist zu diesem Zeitpunkt ja schon geschehen.

Aufbewahrung: wie die uebrigen Protokolle (``log_retention``), keine
Stueckzahlgrenze – gesucht wird gerade nach dem alten Eintrag.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
DATEI = WURZEL / "data" / "logs" / "aktivitaet.jsonl"
WERT_MAX = 300          # Zeichen je Detailwert
LISTE_MAX = 50          # Elemente je Detailliste

_lock = threading.Lock()


def _kappen(wert):
    """Detailwerte begrenzen: Zeichenketten auf WERT_MAX, Listen auf LISTE_MAX.
    Alles andere als Zahl/Bool/None/Str/Liste wird zu Text."""
    if wert is None or isinstance(wert, (bool, int, float)):
        return wert
    if isinstance(wert, (list, tuple, set)):
        teile = [_kappen(w) for w in list(wert)[:LISTE_MAX]]
        if len(wert) > LISTE_MAX:
            teile.append(f"… und {len(wert) - LISTE_MAX} weitere")
        return teile
    s = str(wert)
    return s if len(s) <= WERT_MAX else s[:WERT_MAX] + "…"


def eintragen(benutzer: str, bereich: str, aktion: str, objekt: str = "",
              **details) -> dict:
    """Ein Ereignis anhaengen. Rueckgabe: der Eintrag (auch wenn das Schreiben
    scheiterte – dann steht der Grund im Journal)."""
    jetzt = time.time()
    e = {"ts": int(jetzt),
         "zeit": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(jetzt)),
         "benutzer": str(benutzer or ""),
         "bereich": str(bereich or ""),
         "aktion": str(aktion or ""),
         "objekt": _kappen(objekt or "")}
    # Leere Werte weglassen, aber 0/False behalten (Register: Falsyness)
    d = {k: _kappen(v) for k, v in details.items() if v is not None and v != ""}
    if d:
        e["details"] = d
    with _lock:
        try:
            DATEI.parent.mkdir(parents=True, exist_ok=True)
            with DATEI.open("a", encoding="utf-8") as f:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        except OSError as fehler:
            print(f"[Aktivitaet] nicht schreibbar: {fehler}", flush=True)
    return e


def _passt(e: dict, bereich: str, benutzer: str, suche: str) -> bool:
    if bereich and e.get("bereich") != bereich:
        return False
    if benutzer and benutzer.lower() not in str(e.get("benutzer", "")).lower():
        return False
    if suche:
        # Gesucht wird ueber Gegenstand, Aktion UND Details – ein Ordnername steht
        # beim Anlegen im Objekt, beim Zuordnen einer Datei in den Details.
        text = json.dumps({k: e.get(k) for k in ("objekt", "aktion", "details")},
                          ensure_ascii=False).lower()
        if suche.lower() not in text:
            return False
    return True


def lesen(limit: int = 200, bereich: str = "", benutzer: str = "",
          suche: str = "") -> dict:
    """Juengste Eintraege zuerst, gefiltert VOR dem Deckel. ``gesamt`` zaehlt
    alle Treffer, damit eine gekappte Liste als gekappt erkennbar ist."""
    bereich, benutzer, suche = (bereich or "").strip(), (benutzer or "").strip(), (suche or "").strip()
    aus: list[dict] = []
    gesamt = 0
    bereiche: set[str] = set()
    if DATEI.exists():
        for z in reversed(DATEI.read_text(encoding="utf-8", errors="replace").splitlines()):
            if not z.strip():
                continue
            try:
                e = json.loads(z)
            except ValueError:
                continue
            if not isinstance(e, dict):
                continue
            if e.get("bereich"):
                bereiche.add(str(e["bereich"]))
            if not _passt(e, bereich, benutzer, suche):
                continue
            gesamt += 1
            if len(aus) < limit:
                aus.append(e)
    return {"eintraege": aus, "gesamt": gesamt, "bereiche": sorted(bereiche)}


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
            except (ValueError, AttributeError):
                ts = None
            # Ohne Zeitstempel kein Altersbeweis: bleibt stehen (fail-closed)
            if isinstance(ts, (int, float)) and ts < cutoff_ts:
                weg += 1
            else:
                bleiben.append(z)
        if weg:
            tmp = DATEI.with_suffix(".jsonl.tmp")
            tmp.write_text(("\n".join(bleiben) + "\n") if bleiben else "", encoding="utf-8")
            os.replace(tmp, DATEI)
        return weg
