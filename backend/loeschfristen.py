"""Loeschkonzept: Fristen je Datenart und die Bereinigung der Chats (BSI M9).

Betreiberentscheid 2026-10-12:

  chats       180 Tage  nach letzter Aktivitaet: Chat-Sitzungen (/chat), der
                        geteilte Anzeige-Verlauf, Direktnachrichten zwischen
                        Benutzern
  prompts      30 Tage  volle Prompts und Antworten im Konversationsprotokoll
                        (die Kopfzeile bleibt, ihr Aufgabentext wird gekuerzt)
  protokoll    90 Tage  Kopfdaten des Konversationsprotokolls, Audit, Telemetrie-
                        Fehler, E-Mail-/Short-Tracks-/Cron-Protokolle, CSP-Berichte
  sicherheit  365 Tage  Sicherheitsprotokoll (Hash-Kette)

Gedaechtnis und Lernnotizen laufen NICHT ab – sie tragen Herkunft (Benutzer,
Datum) und sind einzeln einsehbar und loeschbar.

WOHER EINE FRIST KOMMT (erste Quelle gewinnt): Einstellung in der Oberflaeche
(System-Einstellungen, ``loeschfrist_<art>`` in settings.json) -> Umgebungs-
variable -> Vorgabe. ``0`` heisst dauerhaft aufbewahren, Deckel 3650 Tage
(ein Tippfehler "9000" soll nicht stillschweigend "dauerhaft" bedeuten).

Die Fristen werden bei JEDEM Aufruf neu gelesen (Funktion, keine Konstante) –
eine geaenderte Einstellung wirkt beim naechsten Tageslauf ohne Neustart.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

DATA = Path(__file__).parent.parent / "data"

# art -> (Umgebungsvariable, Vorgabe, Untergrenze ausser 0)
FRISTEN: dict[str, tuple[str, int, int]] = {
    "chats": ("JARVIS_CHAT_TAGE", 180, 1),
    "prompts": ("JARVIS_PROMPT_TAGE", 30, 1),
    "protokoll": ("JARVIS_LOG_RETENTION_DAYS", 90, 1),
    "sicherheit": ("JARVIS_SICHERHEITS_LOG_TAGE", 365, 1),
}
DECKEL = 3650


def _zahl(roh):
    """int aus Zahl/Text, sonst None (bool zaehlt NICHT als Zahl)."""
    if roh is None or isinstance(roh, bool):
        return None
    try:
        return int(float(str(roh).replace(",", ".").strip()))
    except (TypeError, ValueError):
        return None


def _begrenzen(art: str, n: int) -> int:
    if n <= 0:
        return 0
    return max(FRISTEN[art][2], min(n, DECKEL))


def _einstellung(art: str):
    """Wert aus settings.json – nur aus einem SCHON GELADENEN backend.config.

    Im Dienst ist es immer geladen. Ein Import HIER waere in jedem Test, der
    run_all()/retention_days() ohne Attrappe aufruft, der echte Import – und
    der schreibt die Live-settings.json zurueck (Register fallstricke.md)."""
    mod = sys.modules.get("backend.config")
    cfg = getattr(mod, "config", None) if mod is not None else None
    if cfg is None:
        return None
    try:
        return cfg.get_setting("loeschfrist_" + art, None)
    except Exception:  # noqa: BLE001
        return None


def tage(art: str) -> int:
    """Frist in Tagen (0 = dauerhaft)."""
    env, vorgabe, _ = FRISTEN[art]
    for wert in (_einstellung(art), os.environ.get(env)):
        n = _zahl(wert)
        if n is not None:
            return _begrenzen(art, n)
    return vorgabe


def quelle(art: str) -> str:
    """Woher die Frist stammt: 'einstellung' | 'umgebung' | 'vorgabe'."""
    if _zahl(_einstellung(art)) is not None:
        return "einstellung"
    if _zahl(os.environ.get(FRISTEN[art][0])) is not None:
        return "umgebung"
    return "vorgabe"


def schnitt(art: str, jetzt: float | None = None) -> float | None:
    """Zeitpunkt, VOR dem geloescht wird – None bei 'dauerhaft'."""
    t = tage(art)
    if t == 0:
        return None
    return (jetzt if jetzt is not None else time.time()) - t * 86400


def uebersicht() -> dict:
    return {art: {"tage": tage(art), "quelle": quelle(art), "vorgabe": FRISTEN[art][1],
                  "minimum": FRISTEN[art][2], "umgebung": FRISTEN[art][0]} for art in FRISTEN}


def setzen(werte: dict) -> dict:
    """Fristen aus der Oberflaeche speichern. ``None``/"" = Einstellung entfernen
    (dann gilt wieder Umgebungsvariable bzw. Vorgabe). Wirft ValueError."""
    from backend.config import config
    neu = {}
    for art, roh in (werte or {}).items():
        if art not in FRISTEN:
            raise ValueError("unbekannte Frist: %s" % art)
        if roh is None or (isinstance(roh, str) and roh.strip() == ""):
            neu[art] = None
            continue
        n = _zahl(roh)
        if n is None or n < 0:
            raise ValueError("Frist '%s' muss eine Zahl ab 0 sein" % art)
        if n and n < FRISTEN[art][2]:
            raise ValueError("Frist '%s': mindestens %d Tage (oder 0 = dauerhaft)"
                             % (art, FRISTEN[art][2]))
        if n > DECKEL:
            raise ValueError("Frist '%s': hoechstens %d Tage" % (art, DECKEL))
        neu[art] = n
    for art, n in neu.items():
        config.save_setting("loeschfrist_" + art, n)
    return uebersicht()


# ── Chats ───────────────────────────────────────────────────────────────────

def _sitzungen_bereinigen(cut: float, wurzel: Path) -> int:
    """/chat-Sitzungen ohne Aktivitaet seit ``cut`` entfernen (meta.updated)."""
    from backend import chat_sessions
    n = 0
    if not wurzel.is_dir():
        return 0
    with chat_sessions._LOCK:
        n = _sitzungen_unter_sperre(cut, wurzel)
    return n


def _sitzungen_unter_sperre(cut: float, wurzel: Path) -> int:
    n = 0
    for ud in wurzel.iterdir():
        if not ud.is_dir():
            continue
        for sd in ud.iterdir():
            meta = sd / "meta.json"
            if not sd.is_dir() or not meta.is_file():
                continue
            try:
                m = json.loads(meta.read_text(encoding="utf-8"))
                zuletzt = float(m.get("updated") or m.get("created") or 0)
            except Exception:  # noqa: BLE001
                continue           # unlesbar: kein Altersbeweis -> stehen lassen
            if zuletzt and zuletzt < cut:
                shutil.rmtree(sd, ignore_errors=True)
                n += 1
    return n


def _ts_sekunden(eintrag: dict):
    """Zeitstempel einer Nachricht in Sekunden (Frontend schreibt ms)."""
    ts = eintrag.get("ts") if isinstance(eintrag, dict) else None
    if isinstance(ts, bool) or not isinstance(ts, (int, float)) or ts <= 0:
        return None
    return ts / 1000.0 if ts > 1e11 else float(ts)


def _verlauf_bereinigen(cut: float, wurzel: Path) -> int:
    """Geteilter Anzeige-Verlauf: Nachrichten aelter als ``cut`` entfernen."""
    from backend import chat_history
    n = 0
    if not wurzel.is_dir():
        return 0
    with chat_history._LOCK:
        for p in wurzel.glob("*.json"):
            try:
                daten = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(daten, list):
                continue
            # ohne Zeitstempel: kein Altersbeweis -> bleibt (fail-closed)
            rest = [m for m in daten if (_ts_sekunden(m) or cut) >= cut]
            weg = len(daten) - len(rest)
            if not weg:
                continue
            n += weg
            if rest:
                p.write_text(json.dumps(rest, ensure_ascii=False), encoding="utf-8")
            else:
                p.unlink(missing_ok=True)
    return n


def direktnachrichten_bereinigen(verlauf: dict, cut: float) -> int:
    """Direktnachrichten (Userchat) im Speicher kuerzen; Aufrufer speichert."""
    n = 0
    for k in list(verlauf.keys()):
        liste = verlauf.get(k)
        if not isinstance(liste, list):
            continue
        rest = [m for m in liste if (_ts_sekunden(m) or cut) >= cut]
        n += len(liste) - len(rest)
        if rest:
            verlauf[k] = rest
        else:
            verlauf.pop(k, None)
    return n


def chats_bereinigen(jetzt: float | None = None, daten: Path | None = None) -> dict:
    """Sitzungen + Anzeige-Verlauf. Direktnachrichten liegen im Speicher von
    main.py und werden dort mit ``direktnachrichten_bereinigen`` gekuerzt."""
    cut = schnitt("chats", jetzt)
    if cut is None:
        return {"dauerhaft": True}
    d = daten or DATA
    return {"sitzungen": _sitzungen_bereinigen(cut, d / "chats"),
            "verlauf_nachrichten": _verlauf_bereinigen(cut, d / "chat_history")}
