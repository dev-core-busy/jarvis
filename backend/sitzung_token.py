"""Sitzungs-Tokens: Laufzeit, Leerlauf und Widerruf je Token (BSI H3).

Befund H3 aus dem BSI-Abgleich vom 2026-09-29 (APP.3.1.A7): das Sitzungstoken
galt fest 30 Tage, kannte keinen Leerlauf, und weder Abmelden noch
Kennwortwechsel machten es ungueltig – ein einmal abgegriffenes Token blieb
einen Monat lang eine Vollmacht.

Das Token-FORMAT bleibt unveraendert (``user:ts:sig``, zustandslos, HMAC –
``main.generate_token``). Web, Android, Windows und die Add-ins reichen es nur
durch; ein neues Format haette jeden Client mitgerissen. Neu ist eine kleine
Buchhaltung JE TOKEN daneben:

* **Laufzeit** – ``sitzung_max_stunden`` (Vorgabe 12, Entscheidung des
  Betreibers 2026-09-30). Gemessen ab Ausstellung, nicht verlaengerbar.
* **Leerlauf** – ``sitzung_leerlauf_minuten`` (Vorgabe 120). Jede Anfrage mit
  dem Token setzt "zuletzt gesehen". ⚠ Ein offener Tab fragt im Hintergrund
  staendig nach (Status-Polls) und gilt damit als aktiv; der Leerlauf greift
  faktisch bei geschlossenem Tab/Geraet und bei einem liegengebliebenen Token.
  Das ist gewollt und so mit dem Betreiber besprochen.
* **Widerruf** – ``widerrufe()`` beim Abmelden: genau DIESES Token, andere
  Geraete desselben Benutzers bleiben angemeldet. Den Widerruf ALLER Tokens
  eines Benutzers (Kennwortwechsel, Zwangsabmeldung, AD-Entzug) macht weiter
  die Epoche ``main._revoked_logins``.

**Merkmal "mit 2FA"** (BSI M3, 2026-10-04) – ``neu(..., mit_2fa=True)`` fuer
Sitzungen, deren Anmeldung den zweiten Faktor bestanden hat (bzw. die 2FA
gerade eingerichtet hat). Admin-Rechte gibt es bei eingeschalteter Pflicht nur
in solchen Sitzungen (``main._user_is_admin``). Unbekannt = OHNE 2FA:
Sitzungen von vor dem Ausrollen, Add-in-SSO und App-Anmeldungen bekommen damit
von selbst keine Admin-Rechte. Sofort auf Platte, sonst verloere ein Admin
seine Rechte bei jedem Neustart des Dienstes.

**Merkmal "ohne Admin"** (BSI M3, Entscheidung des Betreibers 2026-10-04) –
Anmeldungen ueber die Android-/Windows-App: die Apps koennen keinen zweiten
Faktor, ein Admin-Konto bekommt dort deshalb eine Sitzung OHNE Admin-Rechte,
unabhaengig von der 2FA-Pflicht.

GESPEICHERT WIRD NIE DAS TOKEN, nur ``sha256(sig)`` gekuerzt – die Datei
``data/auth_sitzungen.json`` gibt damit keine Vollmacht her, auch wenn sie
jemand liest.

UNBEKANNTES TOKEN = zuletzt gesehen bei Ausstellung. Ein Token, das die
Buchhaltung nie gesehen hat (ausgestellt vor diesem Modul, oder nach einem
Absturz vor dem naechsten Schreiben), bekommt KEINEN Vorschuss: wer es seit
mehr als dem Leerlauf nicht benutzt hat, meldet sich neu an. Folge beim
Ausrollen: jede Sitzung, die aelter als der Leerlauf ist, endet einmalig.

FALLSTRICK Leistung: ``pruefe_und_beruehre`` laeuft bei JEDER
authentifizierten Anfrage (mehrmals pro Sekunde). Deshalb nur Speicher;
geschrieben wird gedrosselt (``FLUSH_INTERVAL``) und sofort bei Widerruf.
Die Einstellungen werden aus demselben Grund nur alle ``_CFG_TTL`` Sekunden
neu gelesen (``config.get_setting`` liest jedes Mal settings.json).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path

STORE_PATH = Path(__file__).resolve().parent.parent / "data" / "auth_sitzungen.json"

MAX_STUNDEN_VORGABE = 12
LEERLAUF_MINUTEN_VORGABE = 120
# Zukunfts-Toleranz fuer den Zeitstempel: der Kennwortwechsel stellt das neue
# Token eine Sekunde NACH der Widerrufs-Epoche aus (sonst faellt es in dieselbe
# Sekunde und waere sofort mit widerrufen, ``ts <= rev``).
ZUKUNFT_TOLERANZ = 5

FLUSH_INTERVAL = 30.0
_CFG_TTL = 30.0

_lock = threading.Lock()
_zuletzt: dict[str, float] = {}      # Schluessel -> zuletzt gesehen (epoch)
_widerrufen: dict[str, int] = {}     # Schluessel -> Ausstellungszeit (zum Aufraeumen)
_mit_2fa: dict[str, int] = {}        # Schluessel -> Ausstellungszeit (zum Aufraeumen)
_ohne_admin: dict[str, int] = {}     # Schluessel -> Ausstellungszeit (zum Aufraeumen)
# Tokens, die VOR diesem Zeitpunkt ausgestellt wurden, gelten nicht (0 = aus).
# Gesetzt, wenn der Speicherstand unlesbar war – siehe _laden_unlocked.
_alle_vor = 0
_geladen = False
_dirty = False
_letzter_flush = 0.0

_cfg_cache: tuple[float, int, int] | None = None   # (gelesen, max_s, leerlauf_s)
_get_setting = None


def einstellungen_quelle(fn) -> None:
    """``main`` reicht ``config.get_setting`` herein – so importiert das Modul
    ``backend.config`` nie selbst (Tests: der echte Import schreibt die
    Live-settings.json)."""
    global _get_setting, _cfg_cache
    _get_setting = fn
    _cfg_cache = None


def _grenzen() -> tuple[int, int]:
    """(max_alter_s, leerlauf_s); Unsinn in settings.json faellt auf die Vorgabe
    zurueck, 0 oder weniger ist KEIN "aus" – eine abgeschaltete Laufzeit waere
    genau der Befund."""
    global _cfg_cache
    jetzt = time.time()
    if _cfg_cache and jetzt - _cfg_cache[0] < _CFG_TTL:
        return _cfg_cache[1], _cfg_cache[2]
    max_h, idle_m = MAX_STUNDEN_VORGABE, LEERLAUF_MINUTEN_VORGABE
    if _get_setting is not None:
        try:
            v = float(_get_setting("sitzung_max_stunden", MAX_STUNDEN_VORGABE))
            if v > 0:
                max_h = v
        except Exception:  # noqa: BLE001
            pass
        try:
            v = float(_get_setting("sitzung_leerlauf_minuten", LEERLAUF_MINUTEN_VORGABE))
            if v > 0:
                idle_m = v
        except Exception:  # noqa: BLE001
            pass
    _cfg_cache = (jetzt, int(max_h * 3600), int(idle_m * 60))
    return _cfg_cache[1], _cfg_cache[2]


def max_alter_s() -> int:
    """Absolute Token-Laufzeit in Sekunden (fuer das Aufraeumen der Epochen)."""
    return _grenzen()[0]


def leerlauf_s() -> int:
    """Leerlauf in Sekunden, nach dem ein unbenutztes Token endet."""
    return _grenzen()[1]


def schluessel(sig: str) -> str:
    """Kennung eines Tokens fuer die Buchhaltung – nie das Token selbst."""
    return hashlib.sha256((sig or "").encode()).hexdigest()[:32]


# ─── Persistenz ──────────────────────────────────────────────────────────────

def _laden_unlocked() -> None:
    """FAIL-CLOSED (Code-Review 2026-10-07): bis dahin startete eine unlesbare
    Datei leer – abgemeldete Tokens galten nach einem Absturz mitten im
    Schreiben wieder. Jetzt gilt dann kein Token, das vor dem Laden ausgestellt
    wurde (``_alle_vor``, mit auf Platte); die kaputte Datei bleibt liegen."""
    global _geladen, _alle_vor
    if _geladen:
        return
    _geladen = True
    try:
        if STORE_PATH.exists():
            d = json.loads(STORE_PATH.read_text(encoding="utf-8"))
            if not isinstance(d, dict):
                raise ValueError("kein Objekt")
            _alle_vor = int(d.get("alle_vor") or 0)
            for k, v in (d.get("zuletzt") or {}).items():
                _zuletzt[str(k)] = float(v)
            for k, v in (d.get("widerrufen") or {}).items():
                _widerrufen[str(k)] = int(v)
            for k, v in (d.get("mit_2fa") or {}).items():
                _mit_2fa[str(k)] = int(v)
            for k, v in (d.get("ohne_admin") or {}).items():
                _ohne_admin[str(k)] = int(v)
    except Exception as e:  # noqa: BLE001 – kaputte Datei darf den Start nicht kippen
        print(f"[Sitzung] Speicherstand nicht lesbar ({e}) – alle vorher "
              f"ausgestellten Tokens gelten als widerrufen", flush=True)
        for d_ in (_zuletzt, _widerrufen, _mit_2fa, _ohne_admin):
            d_.clear()
        _alle_vor = int(time.time())
        try:
            os.replace(STORE_PATH, STORE_PATH.with_name(
                STORE_PATH.name + f".kaputt.{_alle_vor}"))
        except Exception:  # noqa: BLE001
            pass
        _schreiben_unlocked()


def _aufraeumen_unlocked(jetzt: float, max_s: int, idle_s: int) -> None:
    """Eintraege, die ohnehin nicht mehr gelten koennten, fliegen raus: ein
    widerrufenes Token nach Ablauf seiner Laufzeit, ein "zuletzt gesehen" nach
    Ablauf des Leerlaufs (danach lehnt die Pruefung es sowieso ab – auch ohne
    Eintrag, weil unbekannt = Ausstellungszeit)."""
    global _alle_vor
    for k in [k for k, ts in _widerrufen.items() if jetzt - ts > max_s + ZUKUNFT_TOLERANZ]:
        _widerrufen.pop(k, None)
    for d in (_mit_2fa, _ohne_admin):
        for k in [k for k, ts in d.items() if jetzt - ts > max_s + ZUKUNFT_TOLERANZ]:
            d.pop(k, None)
    for k in [k for k, t in _zuletzt.items() if jetzt - t > idle_s]:
        _zuletzt.pop(k, None)
    if _alle_vor and jetzt - _alle_vor > max_s + ZUKUNFT_TOLERANZ:
        _alle_vor = 0


def _schreiben_unlocked() -> None:
    global _dirty, _letzter_flush
    try:
        STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STORE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps({"zuletzt": _zuletzt, "widerrufen": _widerrufen,
                                   "mit_2fa": _mit_2fa, "ohne_admin": _ohne_admin,
                                   "alle_vor": _alle_vor}),
                       encoding="utf-8")
        try:
            from backend.sandbox import privat_machen
            privat_machen(tmp)
        except Exception:  # noqa: BLE001
            pass
        os.replace(tmp, STORE_PATH)
        _dirty = False
        _letzter_flush = time.time()
    except Exception as e:  # noqa: BLE001
        print(f"[Sitzung] Speichern fehlgeschlagen: {e}", flush=True)


def flush() -> None:
    with _lock:
        _laden_unlocked()
        if _dirty:
            _schreiben_unlocked()


# ─── Pruefung ────────────────────────────────────────────────────────────────

def pruefe_und_beruehre(sig: str, ts: int, jetzt: float | None = None) -> bool:
    """Gilt das (HMAC-geprueft echte) Token mit Ausstellungszeit ``ts`` noch?

    True -> "zuletzt gesehen" wird auf jetzt gesetzt. False bei: abgelaufener
    Laufzeit, Zeitstempel zu weit in der Zukunft, Leerlauf ueberschritten,
    widerrufen. Die HMAC-Pruefung macht der Aufrufer (``main.verify_token``).
    """
    global _dirty
    jetzt = time.time() if jetzt is None else jetzt
    max_s, idle_s = _grenzen()
    alter = jetzt - ts
    if alter > max_s or alter < -ZUKUNFT_TOLERANZ:
        return False
    k = schluessel(sig)
    with _lock:
        _laden_unlocked()
        if k in _widerrufen or (_alle_vor and ts < _alle_vor):
            return False
        zuletzt = _zuletzt.get(k, float(ts))
        if jetzt - zuletzt > idle_s:
            return False
        _zuletzt[k] = jetzt
        _dirty = True
        if jetzt - _letzter_flush > FLUSH_INTERVAL:
            _aufraeumen_unlocked(jetzt, max_s, idle_s)
            _schreiben_unlocked()
    return True


def sitzung_besteht(kennung: str, ts: int, jetzt: float | None = None) -> bool:
    """Besteht die Sitzung mit dieser Kennung (``schluessel(sig)``) und
    Ausstellungszeit noch – nicht abgemeldet, nicht abgelaufen? Fuer den
    Abruf-Schluessel (``download_key``), der nur die Kennung traegt. Der
    Leerlauf zaehlt hier nicht: der Schluessel hat seine eigene, kurze Frist.
    Die Epochen (Kennwortwechsel, Zwangsabmeldung) prueft der Aufrufer."""
    jetzt = time.time() if jetzt is None else jetzt
    max_s, _ = _grenzen()
    alter = jetzt - int(ts)
    if alter > max_s or alter < -ZUKUNFT_TOLERANZ:
        return False
    with _lock:
        _laden_unlocked()
        if _alle_vor and int(ts) < _alle_vor:
            return False
        return str(kennung) not in _widerrufen


def neu(sig: str, ts: int, mit_2fa: bool = False, ohne_admin: bool = False) -> None:
    """Frisch ausgestelltes Token: zuletzt gesehen = Ausstellung. Nur der
    Vollstaendigkeit halber (unbekannt heisst ohnehin Ausstellungszeit) –
    aber so steht es sofort in der Datei, falls der Dienst gleich neu startet.
    ``mit_2fa``/``ohne_admin`` siehe Modulkopf; dann sofort geschrieben."""
    global _dirty
    with _lock:
        _laden_unlocked()
        _zuletzt[schluessel(sig)] = float(ts)
        _dirty = True
        if mit_2fa:
            _mit_2fa[schluessel(sig)] = int(ts)
        if ohne_admin:
            _ohne_admin[schluessel(sig)] = int(ts)
        if mit_2fa or ohne_admin:
            _schreiben_unlocked()


def setze_mit_2fa(sig: str, ts: int) -> None:
    """Bestehende Sitzung nachtraeglich als "mit 2FA" markieren – wer in ihr die
    2FA gerade eingerichtet hat, hat den Faktor eben vorgezeigt."""
    with _lock:
        _laden_unlocked()
        _mit_2fa[schluessel(sig)] = int(ts)
        _schreiben_unlocked()


def ohne_admin(sig: str) -> bool:
    """Wurde diese Sitzung ausdruecklich ohne Admin-Rechte ausgestellt (App)?"""
    with _lock:
        _laden_unlocked()
        return schluessel(sig) in _ohne_admin


def mit_2fa(sig: str) -> bool:
    """Hat die Anmeldung dieser Sitzung den zweiten Faktor bestanden?"""
    with _lock:
        _laden_unlocked()
        return schluessel(sig) in _mit_2fa


def widerrufe(sig: str, ts: int) -> None:
    """Genau dieses Token ungueltig machen (Abmelden). Sofort auf Platte – ein
    Neustart direkt nach dem Abmelden darf das Token nicht wiederbeleben."""
    global _dirty
    k = schluessel(sig)
    with _lock:
        _laden_unlocked()
        _widerrufen[k] = int(ts)
        _zuletzt.pop(k, None)
        _mit_2fa.pop(k, None)
        _ohne_admin.pop(k, None)
        _dirty = True
        _schreiben_unlocked()


def _zuruecksetzen_fuer_test() -> None:
    global _geladen, _dirty, _letzter_flush, _cfg_cache, _alle_vor
    with _lock:
        _alle_vor = 0
        _zuletzt.clear()
        _widerrufen.clear()
        _mit_2fa.clear()
        _ohne_admin.clear()
        _geladen = False
        _dirty = False
        _letzter_flush = 0.0
        _cfg_cache = None
