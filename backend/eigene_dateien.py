#!/usr/bin/env python3
"""Register der Uebergaenge, die der Root-Broker an seinen eigenen Dateien
unter /etc/jarvis selbst vorgenommen hat – fuer den AIDE-Abgleich.

WARUM (ECHT 25.11.2026)
-----------------------
``/etc/jarvis/broker.conf``, ``broker-policy.json`` und
``broker-freigabe.state`` schreibt der Broker im Betrieb selbst: der
Mailversand und der Fernzugang ihre Schluessel, die Policy jeden neu
auftauchenden Op-Eintrag und jede Admin-Entscheidung, die Freigabe den
verbrauchten Code-Schritt. AIDE meldete jede dieser Aenderungen als "geaendert,
gehoert keinem Paket" – drei Dauerlaeufer in jeder Meldung, und eine echte
Manipulation dieser Dateien sah genauso aus.

WAS VERMERKT WIRD: nicht "dieser Stand ist gut", sondern ein UEBERGANG
(Pruefsumme vorher -> nachher), aufgenommen genau dort, wo der Broker schreibt.
Der Abgleich erklaert eine gemeldete Aenderung nur, wenn sich aus diesen
Uebergaengen ein lueckenloser Weg vom alten Stand (aide.db) zum neuen bauen
laesst. Ein fremder Eingriff dazwischen ist eine Luecke in der Kette: auch wenn
der Broker die Datei danach noch einmal schreibt (lesen, aendern, schreiben),
beginnt sein Uebergang bei dem fremden Stand, und der Weg reisst ab. Ein
"zuletzt geschrieben"-Merkzettel (wie mail_meldung) wuerde den fremden Eingriff
mit der naechsten Broker-Schreibung uebernehmen.

GRENZE: wer root ist, kann auch dieses Register schreiben – es schuetzt gegen
Eingriffe ausserhalb des Brokers (Hand, Skript, anderes Programm), nicht gegen
einen Angreifer mit root. Dasselbe gilt fuer die AIDE-Datenbank selbst.

Nur Standardbibliothek; wirft nie in den Aufrufer (ein Fehler hier darf keine
Broker-Op scheitern lassen – dann bleibt die Aenderung eben "nicht erklaert").
"""

from __future__ import annotations

import base64
import binascii
import fcntl
import hashlib
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

# Testwurzel wie aide_abgleich.py (dieselbe Variable: Abgleich und Register
# sehen im Waechter denselben Sandkasten)
W = os.environ.get("JARVIS_AIDE_WURZEL", "")

PFADE = ("/etc/jarvis/broker.conf", "/etc/jarvis/broker-policy.json", "/etc/jarvis/broker-freigabe.state")
# Im (AIDE-ausgenommenen, root-eigenen 0700) Zustandsverzeichnis des Abgleichs
ZUSTAND_DIR = "/var/lib/jarvis-aide"
REGISTER = ZUSTAND_DIR + "/eigene.json"
SPERRE = ZUSTAND_DIR + "/.eigene.sperre"
# Je Datei so viele Uebergaenge und so lange: die taegliche Pruefung braucht
# nur die seit dem letzten uebernommenen Stand; ein liegengebliebener offener
# Abgleich soll aber auch nach Wochen noch erklaerbar sein.
MAX_JE_DATEI = 400
MAX_ALTER_S = 120 * 86400


def _p(pfad: str) -> Path:
    return Path(W + pfad) if W else Path(pfad)


def _norm(pfad) -> str | None:
    """Absoluter Systempfad (ohne Testwurzel), wenn er zum Register gehoert."""
    s = str(pfad)
    if W and s.startswith(W):
        s = s[len(W):]
    return s if s in PFADE else None


def _darf() -> bool:
    return bool(W) or os.geteuid() == 0


def sha(pfad) -> str | None:
    """sha256 (hex) der Datei oder None, wenn sie nicht existiert/lesbar ist."""
    try:
        with open(pfad, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


@contextmanager
def _sperre():
    _p(ZUSTAND_DIR).mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(_p(SPERRE), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def lesen() -> dict:
    try:
        d = json.loads(_p(REGISTER).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _schreiben(d: dict) -> None:
    ziel = _p(REGISTER)
    tmp = ziel.with_name(ziel.name + ".tmp.%d" % os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, (json.dumps(d, indent=1, sort_keys=True) + "\n").encode("utf-8"))
    finally:
        os.close(fd)
    os.replace(tmp, ziel)


def vermerken(pfad, vorher: str | None, nachher: str | None) -> bool:
    """Einen Uebergang aufnehmen. True = aufgenommen. Wirft nie."""
    try:
        name = _norm(pfad)
        if name is None or vorher == nachher or not _darf():
            return False
        jetzt = time.time()
        with _sperre():
            d = lesen()
            liste = [u for u in d.get(name, []) if isinstance(u, list) and len(u) == 3
                     and jetzt - float(u[2] or 0) <= MAX_ALTER_S]
            liste.append([vorher, nachher, jetzt])
            d[name] = liste[-MAX_JE_DATEI:]
            _schreiben(d)
        return True
    except Exception:  # noqa: BLE001 - nie die Broker-Op stoeren
        return False


@contextmanager
def schreibt(pfad):
    """Um genau eine Schreibstelle: Pruefsumme davor und danach, Uebergang
    vermerken. Fuer Pfade ausserhalb des Registers wirkungslos."""
    if _norm(pfad) is None:
        yield
        return
    vorher = sha(pfad)
    try:
        yield
    finally:
        vermerken(pfad, vorher, sha(pfad))


def stand() -> dict:
    """Pruefsummen aller Registerdateien (fuer eine Op, die mehrere Schreiber
    anstossen kann – auch Shell-Skripte wie firewall.sh)."""
    return {name: sha(_p(name)) for name in PFADE}


def stand_vermerken(vorher: dict) -> None:
    """Gegenstueck zu ``stand()`` nach der Op: jede geaenderte Datei vermerken."""
    try:
        for name, alt in (vorher or {}).items():
            neu = sha(_p(name))
            if neu != alt:
                vermerken(_p(name), alt, neu)
    except Exception:  # noqa: BLE001
        pass


def aus_aide(wert: str | None) -> str | None:
    """AIDE druckt sha256 als base64 – in hex, oder None."""
    if not wert:
        return None
    try:
        roh = base64.b64decode(wert, validate=True)
    except (binascii.Error, ValueError):
        return None
    return roh.hex() if len(roh) == 32 else None


def erklaert(pfad: str, alt: str | None, neu: str | None) -> bool:
    """Fuehrt eine lueckenlose Kette vermerkter Uebergaenge von ``alt`` nach
    ``neu``? (``None`` = Datei existierte nicht.) Ohne Register: nie."""
    name = _norm(pfad) or pfad
    if name not in PFADE or alt == neu:
        return False
    kanten: dict = {}
    for u in lesen().get(name, []):
        if isinstance(u, list) and len(u) == 3:
            kanten.setdefault(u[0], set()).add(u[1])
    gesehen, offen = {alt}, [alt]
    while offen:
        knoten = offen.pop()
        for weiter in kanten.get(knoten, ()):
            if weiter == neu:
                return True
            if weiter not in gesehen:
                gesehen.add(weiter)
                offen.append(weiter)
    return False
