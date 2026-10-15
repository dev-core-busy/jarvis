"""Schutz der Anmeldung gegen Durchprobieren: je IP UND je Konto, dauerhaft (BSI M3).

Befund M3 aus dem BSI-Abgleich vom 2026-09-29: Fehlversuche wurden nur JE IP
und nur IM SPEICHER gezaehlt (5 in 5 Minuten, ``main._login_attempts``). Wer
seine Adresse wechselt (Botnetz, IPv6-Praefix), probiert ein Konto beliebig
lange durch; ein Neustart des Dienstes setzte jeden Zaehler auf null.

Jetzt zwei Zaehler nebeneinander, beide in ``data/anmelde_schutz.json`` (privat,
``sandbox.PRIVATE_FILES``):

* **je IP** – unveraendert 5 Fehlversuche in 5 Minuten, danach wartet die IP,
  bis der aelteste Versuch aus dem Fenster faellt.
* **je Konto** – 5 Fehlversuche in 15 Minuten sperren das Konto fuer 15 Minuten
  fuer die Jarvis-Anmeldung (Entscheidung des Betreibers 2026-10-04: Zeitsperre,
  laeuft von selbst ab, Admin kann vorzeitig aufheben). Gezaehlt wird fuer
  JEDEN Namen, auch fuer einen, den es nicht gibt – sonst verriete die Sperre,
  welche Konten existieren.

Die Konto-Sperre wird VOR der Kennwortpruefung geprueft: waehrend sie gilt,
geht kein Kennwort mehr an PAM oder den Domain-Controller. Das schont nebenbei
das AD-Konto (die Domaene sperrt selbst schon nach 3 Fehlversuchen, auch fuer
Windows – siehe Gedaechtnis "ad-login-sperre").

Schluessel des Kontos ist der NORMALISIERTE Name (``main._norm_login``) – sonst
zaehlte ``firma\\x.y`` getrennt von ``x.y``. Der Aufrufer normalisiert.

Eine erfolgreiche Anmeldung setzt den Konto-Zaehler zurueck, den IP-Zaehler
nicht (eine IP hinter NAT ist kein Benutzer).
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

STORE_PATH = Path(__file__).resolve().parent.parent / "data" / "anmelde_schutz.json"

IP_MAX = 5
IP_FENSTER_S = 300
KONTO_MAX = 5
KONTO_FENSTER_S = 900
KONTO_SPERRE_S = 900
# Deckel gegen eine Datei, die ein Angreifer mit erfundenen Namen fuellt.
# Bei Ueberlauf fliegen die aeltesten Eintraege – nie eine laufende Sperre.
MAX_EINTRAEGE = 20000

_lock = threading.Lock()
_ip: dict[str, list[float]] = {}
_konto: dict[str, list[float]] = {}
_gesperrt: dict[str, float] = {}      # Konto -> gesperrt bis (epoch)
_geladen = False


def _laden_unlocked() -> None:
    global _geladen
    if _geladen:
        return
    _geladen = True
    try:
        if STORE_PATH.exists():
            d = json.loads(STORE_PATH.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                for quelle, ziel in (("ip", _ip), ("konto", _konto)):
                    for k, v in (d.get(quelle) or {}).items():
                        if isinstance(v, list):
                            ziel[str(k)] = [float(x) for x in v]
                for k, v in (d.get("gesperrt") or {}).items():
                    _gesperrt[str(k)] = float(v)
    except Exception as e:  # noqa: BLE001 – kaputte Datei darf die Anmeldung nicht kippen
        print(f"[Anmeldeschutz] Speicherstand nicht lesbar, starte leer: {e}", flush=True)


def _aufraeumen_unlocked(jetzt: float) -> None:
    for d, fenster in ((_ip, IP_FENSTER_S), (_konto, KONTO_FENSTER_S)):
        for k in list(d):
            d[k] = [t for t in d[k] if jetzt - t < fenster]
            if not d[k]:
                del d[k]
    for k in [k for k, bis in _gesperrt.items() if bis <= jetzt]:
        del _gesperrt[k]
    for d in (_ip, _konto):
        if len(d) > MAX_EINTRAEGE:
            for k in sorted(d, key=lambda k: max(d[k]))[:len(d) - MAX_EINTRAEGE]:
                del d[k]


def _schreiben_unlocked() -> None:
    try:
        STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STORE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps({"ip": _ip, "konto": _konto, "gesperrt": _gesperrt}),
                       encoding="utf-8")
        try:
            from backend.sandbox import privat_machen
            privat_machen(tmp)
        except Exception:  # noqa: BLE001
            pass
        os.replace(tmp, STORE_PATH)
    except Exception as e:  # noqa: BLE001
        print(f"[Anmeldeschutz] Speichern fehlgeschlagen: {e}", flush=True)


def ip_wartezeit(ip: str, jetzt: float | None = None) -> int:
    """Sekunden, die diese IP noch warten muss; 0 = darf."""
    jetzt = time.time() if jetzt is None else jetzt
    with _lock:
        _laden_unlocked()
        v = [t for t in _ip.get(ip, []) if jetzt - t < IP_FENSTER_S]
        if len(v) < IP_MAX:
            return 0
        # Wartet, bis so viele Versuche aus dem Fenster gefallen sind, dass
        # wieder einer frei ist.
        return max(1, int(sorted(v)[len(v) - IP_MAX] + IP_FENSTER_S - jetzt) + 1)


def konto_wartezeit(konto: str, jetzt: float | None = None) -> int:
    """Sekunden, die das Konto noch gesperrt ist; 0 = nicht gesperrt."""
    jetzt = time.time() if jetzt is None else jetzt
    if not konto:
        return 0
    with _lock:
        _laden_unlocked()
        bis = _gesperrt.get(konto, 0.0)
        return max(1, int(bis - jetzt) + 1) if bis > jetzt else 0


def fehlversuch(ip: str, konto: str, jetzt: float | None = None) -> bool:
    """Einen Fehlversuch buchen. True, wenn das Konto DADURCH gesperrt wurde."""
    jetzt = time.time() if jetzt is None else jetzt
    neu_gesperrt = False
    with _lock:
        _laden_unlocked()
        _aufraeumen_unlocked(jetzt)
        if ip:
            _ip.setdefault(ip, []).append(jetzt)
        if konto:
            liste = _konto.setdefault(konto, [])
            liste.append(jetzt)
            if len(liste) >= KONTO_MAX and _gesperrt.get(konto, 0.0) <= jetzt:
                _gesperrt[konto] = jetzt + KONTO_SPERRE_S
                _konto.pop(konto, None)
                neu_gesperrt = True
        _schreiben_unlocked()
    if neu_gesperrt:
        print(f"[Anmeldeschutz] Konto '{konto}' nach {KONTO_MAX} Fehlversuchen fuer "
              f"{KONTO_SPERRE_S // 60} min gesperrt (letzte IP {ip})", flush=True)
    return neu_gesperrt


def erfolg(konto: str) -> None:
    """Erfolgreiche Anmeldung: Konto-Zaehler zurueck (IP-Zaehler bleibt)."""
    if not konto:
        return
    with _lock:
        _laden_unlocked()
        if _konto.pop(konto, None) is not None:
            _schreiben_unlocked()


def gesperrte_konten(jetzt: float | None = None) -> list[dict]:
    """Laufende Konto-Sperren fuer die Admin-Ansicht: [{konto, bis}]."""
    jetzt = time.time() if jetzt is None else jetzt
    with _lock:
        _laden_unlocked()
        return sorted(({"konto": k, "bis": int(b)} for k, b in _gesperrt.items() if b > jetzt),
                      key=lambda e: e["konto"])


def aufheben(konto: str) -> bool:
    """Sperre und Zaehler eines Kontos vorzeitig loeschen (Admin). True = es gab eine."""
    with _lock:
        _laden_unlocked()
        hatte = _gesperrt.pop(konto, None) is not None
        _konto.pop(konto, None)
        _schreiben_unlocked()
    return hatte


def _zuruecksetzen_fuer_test() -> None:
    global _geladen
    with _lock:
        _ip.clear()
        _konto.clear()
        _gesperrt.clear()
        _geladen = False
