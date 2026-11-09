"""Reihenfolge fuer Auswahllisten in der Admin-Oberflaeche.

WOFUER (gemeldet 2026-11-09): *Einstellungen → Fehleranalyse → Benutzer* stand
unsortiert da. Die Quelle (``conv_log.get_known_users``) liefert die Namen in
der Reihenfolge der LETZTEN AKTIVITAET – fuer die Verlaufs-Logik richtig, fuer
ein Pulldown, in dem man einen Namen SUCHT, wertlos: dieselbe Person steht
morgen an anderer Stelle. Dieselbe Herkunft hatten der Benutzer- und der
IP-Filter im Verlauf (Telemetrie) und der Benutzerfilter der
Zugriffs-Verstoesse (``security_guard.known_violation_users``, „neueste
Aktivitaet zuerst").

WARUM HIER UND NICHT IN DER QUELLE: die Quellen dienen auch Stellen, an denen
die Aktualitaet zaehlt (Userchat-Kandidaten, Docstring von
``known_violation_users``). Sortiert wird dort, wo die Liste zur ANZEIGE wird –
am Endpunkt, NACH der Aufbereitung zum Anzeigenamen. Vorher sortiert waere die
Reihenfolge die der Rohnamen, und die weicht ab, sobald ein Teil der Namen
einen Domaenen-Praefix bekommt und ein anderer nicht.

Sortiert wird nach dem ANGEZEIGTEN Text: was der Leser sieht, muss
alphabetisch aussehen. Gross/Klein und Akzente entscheiden nicht (``Ä`` wie
``A``), Ziffernfolgen zaehlen als Zahl (``user2`` vor ``user10``) – dieselben
Regeln wie ``frontend/js/alpha_sort.js`` (``Intl.Collator`` mit
``sensitivity: 'base'``, ``numeric: true``).
"""
from __future__ import annotations

import ipaddress
import re
import unicodedata

_ZIFFERN = re.compile(r"(\d+)")


def _grundform(text: str) -> str:
    """Kleinschreibung ohne Akzente: ``Ärger`` → ``arger``."""
    zerlegt = unicodedata.normalize("NFKD", text)
    return "".join(z for z in zerlegt if not unicodedata.combining(z)).casefold()


def text_schluessel(text) -> tuple:
    """Sortierschluessel fuer einen Anzeigetext.

    Ziffernfolgen werden als ``(1, Zahl)`` eingereiht, Text als ``(0, text)`` –
    der Typ steht vorn, damit Zahl und Text nie direkt verglichen werden (das
    wuerde werfen, statt zu sortieren). Das Original haengt als letzter
    Entscheider an: zwei Eintraege, die sich nur in der Schreibung
    unterscheiden, stehen damit in fester Reihenfolge statt in zufaelliger.
    """
    t = str(text if text is not None else "").strip()
    teile = []
    for i, stueck in enumerate(_ZIFFERN.split(_grundform(t))):
        if not stueck:
            continue
        # split() mit Gruppe: ungerade Indizes sind die Ziffernfolgen.
        teile.append((1, int(stueck), "") if i % 2 else (0, 0, stueck))
    return (tuple(teile), t)


def namen_sortiert(namen) -> list[str]:
    """Anzeigenamen alphabetisch, jeder genau einmal, leere Eintraege raus.

    Doppelte entstehen, wenn zwei Tippformen derselben Person zum selben
    Anzeigenamen aufbereitet werden – im Pulldown waeren das zwei gleiche
    Zeilen, die zur selben Auswahl fuehren.
    """
    gesehen: set[str] = set()
    aus: list[str] = []
    for n in namen or []:
        if not isinstance(n, str) or not n.strip() or n in gesehen:
            continue
        gesehen.add(n)
        aus.append(n)
    return sorted(aus, key=text_schluessel)


def _ip_schluessel(text: str) -> tuple:
    """IPv4 vor IPv6, jeweils numerisch; alles andere (``unknown``) danach."""
    try:
        ip = ipaddress.ip_address(text.strip())
        return (0, ip.version, int(ip), "")
    except ValueError:
        return (1, 0, 0) + (text_schluessel(text),)


def ips_sortiert(ips) -> list[str]:
    """Adressen NUMERISCH (``10.0.0.9`` vor ``10.0.0.10``), Unbekanntes am Ende.

    Als Text sortiert stuende ``10.0.0.10`` vor ``10.0.0.9`` – das sieht fuer
    den Leser genauso unsortiert aus wie die Aktivitaetsreihenfolge vorher.
    """
    gesehen: set[str] = set()
    aus: list[str] = []
    for ip in ips or []:
        if not isinstance(ip, str) or not ip.strip() or ip in gesehen:
            continue
        gesehen.add(ip)
        aus.append(ip)
    return sorted(aus, key=_ip_schluessel)
