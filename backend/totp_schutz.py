"""Zwei-Faktor-Code nur EINMAL annehmen (BSI N3).

Befund N3 aus dem BSI-Abgleich vom 2026-09-29: ``pyotp.TOTP.verify(code,
valid_window=1)`` nimmt denselben Code innerhalb seines Fensters (bis zu 90 s)
beliebig oft an. Wer einen Code mitliest (Schulterblick, Proxy-Protokoll,
Schadsoftware am Arbeitsplatz) und das Kennwort kennt, meldet sich damit ein
zweites Mal an, solange der Code noch gilt.

Jetzt wird je Konto UND Secret der ZEITSCHRITT (``int(t // 30)``) des zuletzt
angenommenen Codes gemerkt. Angenommen wird nur ein Code, dessen Zeitschritt JUENGER ist –
das schliesst auch den Code aus dem Vorfenster aus, wenn der aktuelle schon
benutzt wurde (RFC 6238, Abschnitt 5.2).

Ablage ``data/totp_schritte.json`` (privat, ``sandbox.PRIVATE_FILES``), damit
ein Neustart des Dienstes die Sperre nicht aufhebt. Schluessel ist der
NORMALISIERTE Name (``main._norm_login``, der Aufrufer normalisiert) plus ein
kurzer Hash des Secrets: ein Code eines ANDEREN Secrets ist keine Wiederholung
– wer die 2FA neu einrichtet, gibt den ersten Code des neuen Secrets oft in
derselben halben Minute ein wie zuletzt einen des alten (gemessen am Ablauf
in tests/test_bsi_hoch.py). Das Secret selbst steht nie in der Datei.

Pruefen und Merken passieren unter EINEM Lock: zwei gleichzeitige Anfragen mit
demselben Code duerfen nicht beide durchkommen.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import threading
import time
from pathlib import Path

STORE_PATH = Path(__file__).resolve().parent.parent / "data" / "totp_schritte.json"

FENSTER = 1          # Zeitschritte vor/nach dem aktuellen (wie bisher valid_window=1)
# Deckel gegen eine Datei voller Namen; Eintraege aelter als ein Tag sind
# ohnehin wertlos (ein Code von gestern trifft nie wieder).
HALTE_S = 86400

_lock = threading.Lock()
_schritte: dict[str, int] = {}
_geladen = False

# Ergebnisse von ``pruefen``
OK = "ok"
FALSCH = "falsch"
SCHON_BENUTZT = "schon_benutzt"


def _laden_unlocked() -> None:
    global _geladen
    if _geladen:
        return
    _geladen = True
    try:
        if STORE_PATH.exists():
            d = json.loads(STORE_PATH.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                for k, v in d.items():
                    _schritte[str(k)] = int(v)
    except Exception as e:  # noqa: BLE001 – kaputte Datei darf die Anmeldung nicht kippen
        print(f"[2FA] Speicherstand der Zeitschritte nicht lesbar, starte leer: {e}", flush=True)


def _schreiben_unlocked(jetzt: float, intervall: int) -> None:
    grenze = int(jetzt // intervall) - HALTE_S // intervall
    for k in [k for k, s in _schritte.items() if s < grenze]:
        del _schritte[k]
    try:
        STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STORE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(_schritte), encoding="utf-8")
        try:
            from backend.sandbox import privat_machen
            privat_machen(tmp)
        except Exception:  # noqa: BLE001
            pass
        os.replace(tmp, STORE_PATH)
    except Exception as e:  # noqa: BLE001
        print(f"[2FA] Speichern der Zeitschritte fehlgeschlagen: {e}", flush=True)


def _treffer(totp, code: str, jetzt: float) -> int | None:
    """Zeitschritt, zu dem ``code`` passt (juengster zuerst), sonst None."""
    intervall = int(getattr(totp, "interval", 30) or 30)
    aktuell = int(jetzt // intervall)
    for versatz in range(FENSTER, -FENSTER - 1, -1):
        schritt = aktuell + versatz
        # zeitzonenbehaftet: pyotp rechnet dann ueber timegm statt mktime –
        # sonst verschiebt die Sommerzeit-Umstellung den Schritt um eine Stunde
        zeit = datetime.datetime.fromtimestamp(schritt * intervall, tz=datetime.timezone.utc)
        if totp.verify(code, for_time=zeit):
            return schritt
    return None


def pruefen(konto: str, secret: str, code: str, jetzt: float | None = None) -> str:
    """``OK``, ``FALSCH`` oder ``SCHON_BENUTZT``. Nur ``OK`` merkt den Zeitschritt."""
    import pyotp
    jetzt = time.time() if jetzt is None else jetzt
    code = str(code or "").strip().replace(" ", "")
    if not code or not secret:
        return FALSCH
    totp = pyotp.TOTP(secret)
    intervall = int(getattr(totp, "interval", 30) or 30)
    schluessel = ("%s|%s" % (konto, hashlib.sha256(secret.encode()).hexdigest()[:12])
                  if konto else "")
    with _lock:
        _laden_unlocked()
        schritt = _treffer(totp, code, jetzt)
        if schritt is None:
            return FALSCH
        if schluessel and schritt <= _schritte.get(schluessel, -1):
            return SCHON_BENUTZT
        if schluessel:
            _schritte[schluessel] = schritt
            _schreiben_unlocked(jetzt, intervall)
    return OK


def _zuruecksetzen_fuer_test() -> None:
    global _geladen
    with _lock:
        _schritte.clear()
        _geladen = False
