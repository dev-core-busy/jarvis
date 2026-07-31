"""Anwesenheit: welche Benutzer am System angemeldet waren und sind.

Warum es das braucht: Jarvis kennt KEINE Sitzungstabelle. Tokens sind
zustandslose HMAC-Zeichenketten (``main.py::generate_token``) – der Server weiss
also von sich aus weder, wer gerade da ist, noch wer sich wann abgemeldet hat.
Dieses Modul fuehrt genau diese Buchhaltung, ohne am Token-Verfahren etwas zu
aendern.

Drei Ereignisse werden festgehalten:

* ``record_login``  – erfolgreiche Anmeldung (aus ``POST /api/login``)
* ``record_logout`` – ausdrueckliche Abmeldung (aus ``POST /api/logout``)
* ``touch``         – JEDE authentifizierte Anfrage (aus ``require_auth``)

„Online" ist daraus abgeleitet, nicht gemeldet: letzte Aktivitaet juenger als
``ONLINE_WINDOW`` UND keine Abmeldung danach. Das ist die einzige ehrliche
Definition – wer den Tab schliesst, meldet sich nicht ab, sondern verstummt.

FALLSTRICK Leistung: ``touch()`` laeuft bei JEDER authentifizierten Anfrage,
also mehrmals pro Sekunde (Portal- und Chat-Polls). Es darf deshalb NICHT bei
jedem Aufruf auf die Platte schreiben. Gehalten wird alles im Speicher; auf
Platte geht es gedrosselt (``FLUSH_INTERVAL``) sowie sofort bei An-/Abmeldung.
"""

import json
import os
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
STORE_PATH = PROJECT_ROOT / "data" / "user_sessions.json"

# Wie lange nach der letzten Anfrage jemand als "online" gilt. 120 s ist der
# Kompromiss aus den vorhandenen Abfrage-Rhythmen: das Portal fragt den
# LLM-Status alle 30 s, /chat haeufiger. Kuerzer waere flackerig, laenger
# wuerde geschlossene Tabs zu lange als anwesend zeigen.
ONLINE_WINDOW = 120

# Gedrosseltes Schreiben (siehe Fallstrick im Modul-Docstring).
FLUSH_INTERVAL = 20.0

# Obergrenze, damit die Datei nicht unbegrenzt waechst (Domaenen-Umgebungen mit
# vielen Konten). Aeltester Eintrag nach letzter Aktivitaet fliegt zuerst raus.
MAX_USERS = 500

_lock = threading.Lock()
_users: dict = {}
_loaded = False
_dirty = False
_last_flush = 0.0


# ─── Persistenz ──────────────────────────────────────────────────────────────

def _load_unlocked() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        if STORE_PATH.exists():
            data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("users"), dict):
                _users.update(data["users"])
    except Exception as e:  # noqa: BLE001 – kaputte Datei darf den Start nicht kippen
        print(f"[Sitzungen] Speicherstand nicht lesbar, starte leer: {e}", flush=True)


def _write_unlocked() -> None:
    global _dirty, _last_flush
    try:
        STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STORE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps({"users": _users}, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        # Atomar ersetzen: ein Absturz mitten im Schreiben darf keine halbe
        # Datei hinterlassen (die naechste Lesung faellt sonst auf "leer" zurueck).
        os.replace(tmp, STORE_PATH)
        _dirty = False
        _last_flush = time.time()
    except Exception as e:  # noqa: BLE001
        print(f"[Sitzungen] Speichern fehlgeschlagen: {e}", flush=True)


def _prune_unlocked() -> None:
    if len(_users) <= MAX_USERS:
        return
    ranked = sorted(_users.items(), key=lambda kv: kv[1].get("last_seen", 0), reverse=True)
    for key, _ in ranked[MAX_USERS:]:
        _users.pop(key, None)


def flush() -> None:
    """Ausstehende Aenderungen sofort schreiben (Dienst-Ende, Test)."""
    with _lock:
        _load_unlocked()
        if _dirty:
            _write_unlocked()


# ─── Schluessel ──────────────────────────────────────────────────────────────

def _key(username: str) -> str:
    """Normalisierter Schluessel. Bewusst simpel (klein, ohne Domaenenanteil),
    damit ``ANDREA.LADD`` und ``andrea.ladd@firma.local`` denselben Eintrag
    treffen – sonst erscheint dieselbe Person mehrfach in der Liste."""
    u = (username or "").strip().lower()
    if "@" in u:
        u = u.split("@", 1)[0]
    if "\\" in u:
        u = u.rsplit("\\", 1)[-1]
    return u


# ─── Ereignisse ──────────────────────────────────────────────────────────────

def _entry_unlocked(key: str, display: str) -> dict:
    e = _users.get(key)
    if e is None:
        e = {"display": display or key, "first_login": 0.0, "last_login": 0.0,
             "last_logout": 0.0, "last_seen": 0.0, "last_ip": "", "logins": 0,
             "last_action": 0.0, "last_action_label": "", "actions": 0}
        _users[key] = e
    if display:
        e["display"] = display
    return e


def record_login(username: str, ip: str = "") -> None:
    """Erfolgreiche Anmeldung festhalten (sofort auf Platte)."""
    global _dirty
    key = _key(username)
    if not key:
        return
    now = time.time()
    with _lock:
        _load_unlocked()
        e = _entry_unlocked(key, username)
        if not e["first_login"]:
            e["first_login"] = now
        e["last_login"] = now
        e["last_seen"] = now
        e["logins"] = int(e.get("logins") or 0) + 1
        if ip:
            e["last_ip"] = ip
        # Eine neue Anmeldung hebt die frueheren Abmeldung als "aktueller
        # Zustand" auf – der Zeitpunkt bleibt aber sichtbar (last_logout).
        _prune_unlocked()
        _dirty = True
        _write_unlocked()


def record_logout(username: str) -> None:
    """Ausdrueckliche Abmeldung festhalten (sofort auf Platte)."""
    global _dirty
    key = _key(username)
    if not key:
        return
    now = time.time()
    with _lock:
        _load_unlocked()
        e = _entry_unlocked(key, username)
        e["last_logout"] = now
        # last_seen NICHT hochsetzen: sonst gilt der Benutzer nach dem Abmelden
        # noch zwei Minuten als online.
        _dirty = True
        _write_unlocked()


def touch(username: str, ip: str = "") -> None:
    """Aktivitaet festhalten. Wird bei JEDER authentifizierten Anfrage gerufen –
    daher nur Speicher, Platte gedrosselt."""
    global _dirty
    key = _key(username)
    if not key:
        return
    now = time.time()
    with _lock:
        _load_unlocked()
        e = _entry_unlocked(key, username)
        e["last_seen"] = now
        if ip:
            e["last_ip"] = ip
        _dirty = True
        if now - _last_flush >= FLUSH_INTERVAL:
            _prune_unlocked()
            _write_unlocked()


def note_action(username: str, label: str = "", ip: str = "") -> None:
    """Eine echte Benutzer-HANDLUNG festhalten (nicht blosse Anwesenheit).

    Aufrufer: alle veraendernden HTTP-Anfragen (POST/PUT/PATCH/DELETE, siehe
    ``main.py::_note_activity``) und der Chat-Auftrag ueber WebSocket. Reine
    Abfragen (GET) zaehlen bewusst NICHT – sonst waere der Wert wieder nur
    "Tab offen".
    """
    global _dirty
    key = _key(username)
    if not key:
        return
    now = time.time()
    with _lock:
        _load_unlocked()
        e = _entry_unlocked(key, username)
        e["last_seen"] = now
        e["last_action"] = now
        if label:
            e["last_action_label"] = label[:60]
        e["actions"] = int(e.get("actions") or 0) + 1
        if ip:
            e["last_ip"] = ip
        _dirty = True
        # Handlungen sind selten genug, um sie sofort zu sichern – anders als
        # der Poll-getriebene touch().
        _write_unlocked()


# ─── Abfrage ─────────────────────────────────────────────────────────────────

def is_online(entry: dict, now: float = None) -> bool:
    """Online = kuerzlich aktiv UND nicht danach abgemeldet."""
    now = time.time() if now is None else now
    seen = float(entry.get("last_seen") or 0)
    if now - seen > ONLINE_WINDOW:
        return False
    return float(entry.get("last_logout") or 0) <= seen


def list_users() -> list:
    """Alle bekannten Benutzer, online zuerst, danach nach letzter Aktivitaet."""
    now = time.time()
    with _lock:
        _load_unlocked()
        snapshot = {k: dict(v) for k, v in _users.items()}
    out = []
    for key, e in snapshot.items():
        out.append({
            "username": key,
            "display": e.get("display") or key,
            "online": is_online(e, now),
            "kind": "api" if key == "api" else "user",
            "last_login": float(e.get("last_login") or 0),
            "last_logout": float(e.get("last_logout") or 0),
            "last_seen": float(e.get("last_seen") or 0),
            "last_ip": e.get("last_ip") or "",
            "logins": int(e.get("logins") or 0),
            # Echte Handlungen (siehe note_action) – NICHT identisch mit last_seen
            "last_action": float(e.get("last_action") or 0),
            "last_action_label": e.get("last_action_label") or "",
            "actions": int(e.get("actions") or 0),
            # Untaetig seit … Sekunden (nur sinnvoll, wenn ueberhaupt schon
            # einmal etwas getan wurde); None = seit Beginn der Aufzeichnung nichts.
            "idle_seconds": (int(now - float(e["last_action"]))
                             if float(e.get("last_action") or 0) else None),
        })
    out.sort(key=lambda u: (not u["online"], -u["last_seen"]))
    return out


def stats() -> dict:
    users = list_users()
    return {
        "online_window": ONLINE_WINDOW,
        "online": sum(1 for u in users if u["online"]),
        "total": len(users),
        "users": users,
    }
