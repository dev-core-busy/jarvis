"""Start-Diagnose des Outlook-Add-ins – ins Journal, ohne Anmeldung.

ANLASS (2026-11-05, ECHT): Outlook im Web des eigenen Exchange meldete nur
"Add-In-Fehler – Beim Starten dieses Add-Ins ist ein Fehler aufgetreten",
im Journal stand NICHTS. Der Server fuehrt kein Zugriffsprotokoll; ob das
Fenster ueberhaupt abgerufen wurde und wo der Start abbrach, war von hier aus
nicht zu sehen.

ZWEI QUELLEN, beide nur ins Journal (Praefix ``[Add-in-Diagnose]``):

* ``abruf()`` – jeder Abruf von ``/addin/taskpane.html``: wer rahmt ein
  (``Sec-Fetch-Dest``/``-Site``, Host aus dem ``Referer``), welcher Browser,
  welche Abfrageparameter (nur NAMEN, dazu ``_host_Info`` – der sagt, welcher
  Office-Host das Fenster oeffnet).
* ``melden()`` – Startschritte, die das Fenster selbst meldet
  (``/static/addin/diag.js``): Skript laeuft, office.js da, ``onReady``
  ausgeloest, Zeitgrenze, JS-Fehler.

OHNE ANMELDUNG, weil genau der Weg VOR der Anmeldung untersucht wird. Deshalb
dieselben Schranken wie beim CSP-Meldepfad: Lastbremse je IP, Schritt aus
einer festen Liste, harte Feldlaengen, nur druckbare Zeichen, keine IP und
kein Token im Journal.
"""
from __future__ import annotations

import json
import re
import threading
import time
from urllib.parse import parse_qs, urlparse

PRAEFIX = "[Add-in-Diagnose]"
RATE_JE_MINUTE = 40
FELD_MAX = 300
KOERPER_MAX = 4096
SCHRITTE = ("html", "skript", "office_da", "office_bereit", "office_zeit",
            "mailbox", "fehler", "versprechen", "verlassen")

_sperre = threading.Lock()
_rate: dict[str, list[float]] = {}
_HOST_INFO_OK = re.compile(r"^[A-Za-z0-9$|._\-]{1,80}$")


def _kurz(v, n: int = FELD_MAX) -> str:
    s = str(v if v is not None else "")
    s = "".join(ch if ch.isprintable() else " " for ch in s)
    return s[:n]


def _ua_kurz(ua: str) -> str:
    """Browser + Version statt des vollstaendigen User-Agents (Personenbezug)."""
    ua = ua or ""
    for name in ("Edg/", "OPR/", "Firefox/", "Chrome/", "Safari/"):
        i = ua.find(name)
        if i >= 0:
            ver = ua[i + len(name):].split(" ")[0].split(".")[0]
            return name.rstrip("/") + " " + _kurz(ver, 10)
    return "unbekannt"


def _rate_ok(ip: str, jetzt: float) -> bool:
    with _sperre:
        liste = [t for t in _rate.get(ip, []) if jetzt - t < 60]
        if len(liste) >= RATE_JE_MINUTE:
            _rate[ip] = liste
            return False
        liste.append(jetzt)
        _rate[ip] = liste
        if len(_rate) > 5000:              # Speicher der Lastbremse begrenzen
            for k in [k for k, v in _rate.items() if not v or jetzt - v[-1] >= 60]:
                _rate.pop(k, None)
        return True


def abruf_zeile(kopf: dict, abfrage: str) -> str:
    """Journalzeile fuer einen Abruf des Aufgabenfensters (rein, testbar)."""
    k = {str(a).lower(): str(b) for a, b in (kopf or {}).items()}
    ref = k.get("referer", "")
    ref_host = urlparse(ref).hostname or ("-" if not ref else "?")
    params = parse_qs(abfrage or "", keep_blank_values=True)
    namen = ",".join(sorted(_kurz(n, 30) for n in params)) or "-"
    host_info = (params.get("_host_Info") or [""])[0]
    if host_info and not _HOST_INFO_OK.match(host_info):
        host_info = "?"
    return ("%s Abruf taskpane: dest=%s site=%s referer=%s browser=%s params=%s host_info=%s" % (
        PRAEFIX, _kurz(k.get("sec-fetch-dest", "-"), 20), _kurz(k.get("sec-fetch-site", "-"), 20),
        _kurz(ref_host, 100), _ua_kurz(k.get("user-agent", "")), namen, host_info or "-"))


def abruf(kopf: dict, abfrage: str) -> None:
    try:
        print(abruf_zeile(kopf, abfrage), flush=True)
    except Exception:  # noqa: BLE001 – Diagnose darf die Seite nie brechen
        pass


def meldung_zeile(koerper: bytes, ua: str = "") -> str | None:
    """Journalzeile fuer eine Meldung des Fensters – ``None`` = verworfen."""
    if not koerper or len(koerper) > KOERPER_MAX:
        return None
    try:
        d = json.loads(koerper.decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(d, dict):
        return None
    schritt = str(d.get("schritt") or "")
    if schritt not in SCHRITTE:
        return None
    lauf = re.sub(r"[^A-Za-z0-9]", "", str(d.get("lauf") or ""))[:12] or "-"
    try:
        ms = max(0, min(int(d.get("ms") or 0), 10 ** 7))
    except (TypeError, ValueError):
        ms = 0
    detail = _kurz(d.get("detail"))
    return "%s lauf=%s +%dms %s browser=%s %s" % (
        PRAEFIX, lauf, ms, schritt, _ua_kurz(ua), detail)


def melden(koerper: bytes, ip: str = "", ua: str = "") -> bool:
    if not _rate_ok(ip or "-", time.time()):
        return False
    zeile = meldung_zeile(koerper, ua)
    if zeile is None:
        return False
    print(zeile, flush=True)
    return True
