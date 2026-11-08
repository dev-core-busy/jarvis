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

PASSWORD SPRAYING (2026-10-15). Beide Zaehler oben greifen nur, wenn EIN Konto
oder EINE Adresse oft scheitert. Spraying ist das Gegenteil: ein Kennwort fuer
viele Konten, verteilt ueber viele Adressen – kein Zaehler erreicht seine
Schwelle. Dagegen drei Bausteine:

* **Kontoschwelle unter der Domaenen-Schwelle** (``schwellen_setzen``): die
  Domaene sperrt ein Konto nach ``lockoutThreshold`` Fehlversuchen im
  ``lockOutObservationWindow`` – auch fuer Windows. Lag die Jarvis-Schwelle
  DARUEBER (fest 5 gegen 3), konnte jeder ueber Jarvis beliebige
  Domaenenkonten sperren. Der Aufrufer liest die Richtlinie und setzt
  Schwelle - 1 und ein Fenster, das mindestens so lang ist wie das der Domaene.
* **IPv6 als /64** (``ip_schluessel``): ein einzelner Anschluss hat 2^64
  Adressen; je Adresse gezaehlt waere die IP-Grenze wirkungslos. IPv4 bleibt
  exakt – ein /24 waere im Firmennetz die halbe Belegschaft.
* **Erkennung ueber alle Konten** (``spruehlage``): scheitern in
  ``SPRUEH_FENSTER_S`` Anmeldungen fuer mindestens ``SPRUEH_KONTEN``
  VERSCHIEDENE Konten, gilt das als Spruehangriff. Dann wird jede Anmeldung
  JE QUELLE (``ip_schluessel``) auf einen Versuch je ``SPRUEH_ABSTAND_S``
  gebremst (``bremse``), und der Aufrufer meldet den Angriff EINMAL
  (``sprueh_neu_melden``).

  Bis 2026-11-05 bremste die Bremse GLOBAL mit unbegrenzter Warteschlange
  (Pentest-Vorbereitung, Befund A2): zehn Fehlversuche mit erfundenen Namen
  legten die Anmeldung fuer ALLE Benutzer lahm (einer je 2 s, Warteschlange
  ohne Deckel). Jetzt wartet nur, wer von derselben Quelle kommt, und die
  Warteschlange ist begrenzt (``BREMSE_WARTEND_JE_QUELLE``,
  ``BREMSE_WARTEND_GESAMT``) – bei Ueberlauf meldet ``bremse`` False, der
  Aufrufer antwortet 429 statt zu warten. Die Wartezeit verraet weiterhin
  nicht, WELCHES Konto gemeint ist: der Schluessel ist die Quelle, nicht der
  Name.

RESERVIERUNG VOR DER PRUEFUNG (2026-11-05, Befund A1). Bis dahin wurde die
Schranke GELESEN (``ip_wartezeit``/``konto_wartezeit``), dann das Kennwort im
Thread geprueft und erst DANACH der Fehlversuch gebucht. N gleichzeitige
Anfragen lasen alle denselben Stand und kamen alle zur Pruefung – die
Kontoschwelle unter der Domaenen-Schwelle war damit von aussen ueberrennbar
(Domaenenkonten sperren) und TOTP-Codes liessen sich parallel raten.
``reservieren`` prueft und belegt jetzt UNTER EINER Sperre: je Quelle zaehlen
laufende Pruefungen wie Fehlversuche, je Konto laeuft hoechstens EINE
Pruefung gleichzeitig. ``freigeben`` gibt die Belegung zurueck – nach einem
Fehlschlag ist der Fehlversuch dann schon gebucht (``fehlversuch`` VOR
``freigeben``, die Luecke dazwischen ist also nie zu grosszuegig), nach einem
Erfolg zaehlt nichts.

Dazu ``angleichen``: jede fehlgeschlagene Anmeldung dauert mindestens
``FEHL_MINDESTDAUER_S`` (plus Streuung). Ohne das verraet die Antwortzeit, ob
das Kennwort zum Domain-Controller ging oder vorher abgewiesen wurde.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import random
import threading
import time
from pathlib import Path

STORE_PATH = Path(__file__).resolve().parent.parent / "data" / "anmelde_schutz.json"

IP_MAX = 5
IP_FENSTER_S = 300
# Vorgaben ohne Domaene. Mit Domaene setzt ``schwellen_setzen`` die Werte aus
# deren Sperrrichtlinie; die Namen bleiben Modulattribute, damit Anzeige und
# Waechter immer den GELTENDEN Wert lesen.
KONTO_MAX_VORGABE = 5
KONTO_FENSTER_VORGABE_S = 900
# Domaene konfiguriert, Richtlinie aber nicht lesbar: lieber zu frueh sperren
# als ueber Jarvis Domaenenkonten sperren lassen.
KONTO_MAX_OHNE_RICHTLINIE = 2
KONTO_FENSTER_OHNE_RICHTLINIE_S = 1800
KONTO_MAX = KONTO_MAX_VORGABE
KONTO_FENSTER_S = KONTO_FENSTER_VORGABE_S
KONTO_SPERRE_S = 900
SCHWELLEN_QUELLE = "vorgabe"

SPRUEH_FENSTER_S = 600
SPRUEH_KONTEN = 10
SPRUEH_DAUER_S = 1800
SPRUEH_ABSTAND_S = 2.0
FEHL_MINDESTDAUER_S = 1.0
FEHL_STREUUNG_S = 0.25
# Warteschlange der Bremse (A2): wie viele Anmeldungen je Quelle bzw.
# insgesamt warten duerfen, bevor ``bremse`` False meldet (-> 429).
BREMSE_WARTEND_JE_QUELLE = 3
BREMSE_WARTEND_GESAMT = 200
# Reservierung (A1): verfaellt nach dieser Zeit von selbst – eine Pruefung,
# die abstuerzt, ohne freizugeben, sperrt das Konto sonst fuer immer.
RESERVIERUNG_MAX_S = 120
# Deckel gegen eine Datei, die ein Angreifer mit erfundenen Namen fuellt.
# Bei Ueberlauf fliegen die aeltesten Eintraege – nie eine laufende Sperre.
MAX_EINTRAEGE = 20000

_lock = threading.Lock()
_ip: dict[str, list[float]] = {}
_konto: dict[str, list[float]] = {}
_gesperrt: dict[str, float] = {}      # Konto -> gesperrt bis (epoch)
_global: list[list] = []              # [zeit, konto] aller Fehlversuche mit Konto
_sprueh = {"seit": 0.0, "bis": 0.0, "gemeldet": False}
_geladen = False
# Laufende Pruefungen (nur im Speicher – ein Neustart beendet sie ohnehin):
_res_ip: dict[str, dict[int, float]] = {}   # Quelle -> {Kennung: Beginn}
_res_konto: dict[str, tuple[int, float]] = {}  # Konto -> (Kennung, Beginn)
_res_naechste = [0]


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
                for e in d.get("global") or []:
                    if isinstance(e, list) and len(e) == 2:
                        _global.append([float(e[0]), str(e[1])])
                s = d.get("sprueh")
                if isinstance(s, dict):
                    _sprueh.update({"seit": float(s.get("seit", 0)),
                                    "bis": float(s.get("bis", 0)),
                                    "gemeldet": bool(s.get("gemeldet"))})
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
    _global[:] = [e for e in _global if jetzt - e[0] < SPRUEH_FENSTER_S][-MAX_EINTRAEGE:]
    for d in (_ip, _konto):
        if len(d) > MAX_EINTRAEGE:
            for k in sorted(d, key=lambda k: max(d[k]))[:len(d) - MAX_EINTRAEGE]:
                del d[k]


def _schreiben_unlocked() -> None:
    try:
        STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STORE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps({"ip": _ip, "konto": _konto, "gesperrt": _gesperrt,
                                   "global": _global, "sprueh": _sprueh}),
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
        v = [t for t in _ip.get(ip_schluessel(ip), []) if jetzt - t < IP_FENSTER_S]
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
            _ip.setdefault(ip_schluessel(ip), []).append(jetzt)
        if konto:
            _global.append([jetzt, konto])
            _sprueh_pruefen_unlocked(jetzt)
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


def _res_aufraeumen_unlocked(jetzt: float) -> None:
    """Verfallene Reservierungen entfernen (Absturzschutz, ``RESERVIERUNG_MAX_S``)."""
    for k in list(_res_ip):
        _res_ip[k] = {i: t for i, t in _res_ip[k].items() if jetzt - t < RESERVIERUNG_MAX_S}
        if not _res_ip[k]:
            del _res_ip[k]
    for k in [k for k, (_, t) in _res_konto.items() if jetzt - t >= RESERVIERUNG_MAX_S]:
        del _res_konto[k]


def reservieren(ip: str, konto: str, jetzt: float | None = None) -> tuple:
    """Einen Pruefversuch VOR der Kennwort-/Codepruefung atomar belegen.

    Rueckgabe ``(reservierung, grund, wartezeit_s)``:
      * ``(dict, "", 0)``          – darf pruefen; danach IMMER ``freigeben``.
      * ``(None, "ip", s)``        – Quelle hat ihre Versuche (gebucht +
                                     laufend) ausgeschoepft.
      * ``(None, "konto", s)``     – Konto gesperrt.
      * ``(None, "laeuft", s)``    – fuer dieses Konto laeuft schon eine Pruefung.

    Pruefen und Belegen geschehen unter EINER Sperre – das ist der ganze Punkt:
    N gleichzeitige Anfragen sehen nicht mehr denselben Stand."""
    jetzt = time.time() if jetzt is None else jetzt
    schluessel = ip_schluessel(ip) if ip else ""
    with _lock:
        _laden_unlocked()
        _res_aufraeumen_unlocked(jetzt)
        if konto:
            bis = _gesperrt.get(konto, 0.0)
            if bis > jetzt:
                return None, "konto", max(1, int(bis - jetzt) + 1)
            if konto in _res_konto:
                return None, "laeuft", 2
        if schluessel:
            gebucht = sorted(t for t in _ip.get(schluessel, []) if jetzt - t < IP_FENSTER_S)
            laufend = len(_res_ip.get(schluessel, {}))
            if len(gebucht) + laufend >= IP_MAX:
                if len(gebucht) >= IP_MAX:
                    warte = max(1, int(gebucht[len(gebucht) - IP_MAX] + IP_FENSTER_S - jetzt) + 1)
                else:
                    warte = 2   # laufende Pruefungen enden gleich
                return None, "ip", warte
        _res_naechste[0] += 1
        kennung = _res_naechste[0]
        if schluessel:
            _res_ip.setdefault(schluessel, {})[kennung] = jetzt
        if konto:
            _res_konto[konto] = (kennung, jetzt)
        return {"kennung": kennung, "ip": schluessel, "konto": konto}, "", 0


def freigeben(reservierung) -> None:
    """Belegung aus ``reservieren`` zurueckgeben. Mehrfach und mit None harmlos."""
    if not isinstance(reservierung, dict):
        return
    kennung = reservierung.get("kennung")
    with _lock:
        ip = reservierung.get("ip") or ""
        if ip in _res_ip:
            _res_ip[ip].pop(kennung, None)
            if not _res_ip[ip]:
                del _res_ip[ip]
        konto = reservierung.get("konto") or ""
        if konto and _res_konto.get(konto, (None,))[0] == kennung:
            del _res_konto[konto]


def ip_schluessel(ip: str) -> str:
    """Zaehlschluessel einer Adresse: IPv6 als /64, IPv4 (auch IPv4-in-IPv6) exakt.

    Was keine Adresse ist ("unknown", Testwerte), bleibt wie es ist."""
    try:
        a = ipaddress.ip_address(str(ip).strip())
    except ValueError:
        return str(ip)
    if a.version == 6:
        if a.ipv4_mapped is not None:
            return str(a.ipv4_mapped)
        return str(ipaddress.ip_network(f"{a}/64", strict=False))
    return str(a)


def schwellen_setzen(konto_max: int, fenster_s: float, quelle: str) -> None:
    """Kontoschwelle und -fenster setzen (aus der Sperrrichtlinie der Domaene).

    Untergrenzen statt blindem Uebernehmen: mindestens 1 Versuch, und das
    Fenster nie kuerzer als die Vorgabe – ein kurzes Fenster liesse mehr
    Versuche je Domaenenfenster durch, als die Schwelle verspricht."""
    global KONTO_MAX, KONTO_FENSTER_S, SCHWELLEN_QUELLE
    with _lock:
        KONTO_MAX = max(1, int(konto_max))
        KONTO_FENSTER_S = max(KONTO_FENSTER_VORGABE_S, int(fenster_s))
        SCHWELLEN_QUELLE = str(quelle)


def schwellen_aus_richtlinie(richtlinie: dict | None, ad_aktiv: bool) -> tuple:
    """(konto_max, fenster_s, quelle) aus einer gelesenen Domaenen-Richtlinie.

    ``richtlinie`` = {"schwelle": int, "fenster_s": float} oder None (nicht lesbar).
    Schwelle 0 heisst: die Domaene sperrt nie – dann gilt die Vorgabe."""
    if not ad_aktiv:
        return KONTO_MAX_VORGABE, KONTO_FENSTER_VORGABE_S, "vorgabe"
    if not richtlinie:
        return KONTO_MAX_OHNE_RICHTLINIE, KONTO_FENSTER_OHNE_RICHTLINIE_S, "ohne_richtlinie"
    schwelle = int(richtlinie.get("schwelle") or 0)
    fenster = float(richtlinie.get("fenster_s") or 0)
    if schwelle <= 0:
        return KONTO_MAX_VORGABE, max(KONTO_FENSTER_VORGABE_S, fenster), "domaene_ohne_sperre"
    return max(1, schwelle - 1), max(KONTO_FENSTER_VORGABE_S, fenster), "domaene"


def _sprueh_pruefen_unlocked(jetzt: float) -> None:
    konten = {k for t, k in _global if jetzt - t < SPRUEH_FENSTER_S}
    if len(konten) >= SPRUEH_KONTEN:
        if _sprueh["bis"] <= jetzt:          # neuer Angriff, nicht Verlaengerung
            _sprueh["seit"] = jetzt
            _sprueh["gemeldet"] = False
        _sprueh["bis"] = jetzt + SPRUEH_DAUER_S


def spruehlage(jetzt: float | None = None) -> dict:
    """{aktiv, seit, bis, konten}: laufender Spruehangriff und seine Breite."""
    jetzt = time.time() if jetzt is None else jetzt
    with _lock:
        _laden_unlocked()
        konten = len({k for t, k in _global if jetzt - t < SPRUEH_FENSTER_S})
        return {"aktiv": _sprueh["bis"] > jetzt, "seit": int(_sprueh["seit"]),
                "bis": int(_sprueh["bis"]), "konten": konten}


def sprueh_neu_melden(jetzt: float | None = None) -> dict | None:
    """Die Lage EINMAL je Angriff zurueckgeben (danach None) – fuer die Meldung."""
    jetzt = time.time() if jetzt is None else jetzt
    with _lock:
        _laden_unlocked()
        if _sprueh["bis"] <= jetzt or _sprueh["gemeldet"]:
            return None
        _sprueh["gemeldet"] = True
        _schreiben_unlocked()
        konten = len({k for t, k in _global if jetzt - t < SPRUEH_FENSTER_S})
        return {"seit": int(_sprueh["seit"]), "bis": int(_sprueh["bis"]), "konten": konten}


def uhr() -> float:
    """Monotone Uhr fuer ``angleichen`` (eigene Funktion: Waechter ersetzen sie)."""
    return time.monotonic()


async def angleichen(start: float) -> None:
    """Eine fehlgeschlagene Anmeldung auf die Mindestdauer strecken."""
    rest = FEHL_MINDESTDAUER_S + random.uniform(0, FEHL_STREUUNG_S) - (uhr() - start)
    if rest > 0:
        await asyncio.sleep(rest)


_bremse_stand: dict = {"loop": None, "locks": {}, "letzte": {}, "wartend": {}}


async def bremse(ip: str = "") -> bool:
    """Waehrend eines Spruehangriffs: hoechstens ein Anmeldeversuch je
    ``SPRUEH_ABSTAND_S`` JE QUELLE (``ip_schluessel``). True = weiter,
    False = Warteschlange voll -> der Aufrufer antwortet 429.

    Je Quelle statt global (Befund A2, 2026-11-05): global legten zehn
    Fehlversuche mit erfundenen Namen die Anmeldung fuer ALLE lahm. Der
    Schluessel ist die Quelle, nicht das Konto – die Wartezeit verraet also
    weiterhin nicht, wer gemeint ist.

    Die Sperren haengen an der laufenden Ereignisschleife (asyncio.Lock darf
    nicht zwischen Schleifen wandern); eine neue Schleife bekommt neue."""
    if not spruehlage()["aktiv"]:
        return True
    loop = asyncio.get_running_loop()
    if _bremse_stand["loop"] is not loop:
        _bremse_stand.update(loop=loop, locks={}, letzte={}, wartend={})
    quelle = ip_schluessel(ip) if ip else ""
    wartend = _bremse_stand["wartend"]
    if (wartend.get(quelle, 0) >= BREMSE_WARTEND_JE_QUELLE
            or sum(wartend.values()) >= BREMSE_WARTEND_GESAMT):
        return False
    wartend[quelle] = wartend.get(quelle, 0) + 1
    try:
        sperre = _bremse_stand["locks"].setdefault(quelle, asyncio.Lock())
        async with sperre:
            warte = _bremse_stand["letzte"].get(quelle, 0.0) + SPRUEH_ABSTAND_S - uhr()
            if warte > 0:
                await asyncio.sleep(warte)
            _bremse_stand["letzte"][quelle] = uhr()
    finally:
        wartend[quelle] -= 1
        if wartend[quelle] <= 0:
            del wartend[quelle]
            # Aufraeumen: eine Quelle ohne Wartende braucht keine eigene Sperre
            # mehr, sobald ihr Abstand verstrichen ist (sonst waechst die
            # Tabelle mit jeder Adresse eines Angriffs).
            for q in [q for q, t in _bremse_stand["letzte"].items()
                      if q not in wartend and uhr() - t > SPRUEH_ABSTAND_S]:
                _bremse_stand["letzte"].pop(q, None)
                _bremse_stand["locks"].pop(q, None)
    return True


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
    global _geladen, KONTO_MAX, KONTO_FENSTER_S, SCHWELLEN_QUELLE
    KONTO_MAX, KONTO_FENSTER_S, SCHWELLEN_QUELLE = (KONTO_MAX_VORGABE,
                                                   KONTO_FENSTER_VORGABE_S, "vorgabe")
    with _lock:
        _ip.clear()
        _konto.clear()
        _gesperrt.clear()
        _global.clear()
        _sprueh.update(seit=0.0, bis=0.0, gemeldet=False)
        _res_ip.clear()
        _res_konto.clear()
        _geladen = False
    _bremse_stand.update(loop=None, locks={}, letzte={}, wartend={})
