#!/usr/bin/env python3
"""Serverueberwachung (Haertung B13, Checkliste 136).

WAS GEPRUEFT WIRD (alle 5 Minuten, jarvis-ueberwachung.timer, als root)
----------------------------------------------------------------------
* Dienste: eine aktivierte Unit (``is-enabled`` = enabled), die nicht laeuft,
  ist ein ALARM; jede Unit im Zustand ``failed`` eine WARNUNG.
* Freier Platz auf ``/`` und ``/var/log`` (je Dateisystem einmal): unter
  ``PLATZ_WARNUNG`` % eine Warnung, unter ``PLATZ_ALARM`` % ein Alarm.
* Ablauf des Server-Zertifikats: hoechstens 30 Tage = Warnung, hoechstens
  7 Tage oder abgelaufen = Alarm, unlesbar = Warnung.
* Fehlgeschlagene SSH-Anmeldungen (Journal von ssh.service) – gezaehlt je
  VERBINDUNG, nicht je Zeile (siehe ``ssh_fehlversuche``).
* Verworfene Pakete der Firewall (B11, Kernel-Journal):
  ``nft-out-drop`` mit der UID des Dienstbenutzers ist ein ALARM – der Dienst
  selbst wollte ins Netz und wurde abgewiesen; mit einer fremden UID eine
  Warnung; von den Sandbox-Benutzern ein Hinweis (dafuer gibt es die Sperre).
  ``nft-in-drop`` ist ein Hinweis mit Zaehler; ist die Drossel (5/min) in
  einem Lauf nahezu ausgeschoepft, eine Warnung.

EREIGNISSE BLEIBEN 24 STUNDEN SICHTBAR
--------------------------------------
Eine Fehlanmeldung oder ein verworfenes Paket ist kein Zustand, der anhaelt:
im naechsten Lauf ist er vorbei. Damit ein Administrator ihn trotzdem sieht,
fuehrt der Zustand die Ereignisse ``HALTE_S`` lang mit und leitet daraus den
Befund ab. Es gibt bewusst KEIN Quittieren ueber die Oberflaeche – ein
Web-Weg, Befunde verschwinden zu lassen, waere ein Weg, Spuren wegzuerklaeren
(dieselbe Ueberlegung wie in ``sicherheits_log.py``).

WOHIN GEMELDET WIRD
-------------------
1. Journal (syslog, Kennung ``jarvis-ueberwachung``, Facility daemon) – nur bei
   einer AENDERUNG (neu, Stufe geaendert, behoben) und fuer einen anhaltenden
   Alarm einmal je ``ERINNERN_S``. Jede Zeile beginnt mit ``B13 ALARM``,
   ``B13 WARNUNG`` oder ``B13 BEHOBEN`` – danach sucht eine zentrale Auswertung.
   Bei jedem Lauf zu schreiben wuerde das Journal fuellen und die eine wichtige
   Zeile unter tausend gleichen verstecken.
2. ``ZUSTAND_DATEI`` (root:jarvis 0640) – der Dienst liest sie (``lesen``) und
   zeigt Administratoren den Befund an der CPU-Anzeige. Die Sandbox-Benutzer
   koennen sie nicht lesen: sie nennt Quelladressen und Dienstnamen.

EIN STEHENGEBLIEBENER WAECHTER IST SELBST EIN BEFUND
----------------------------------------------------
Laeuft der Timer nicht mehr, aendert sich die Datei nicht – und eine Anzeige,
die den letzten Stand zeigt, sagte "alles in Ordnung". ``lesen`` meldet einen
Zustand, der aelter als ``VERALTET_S`` ist, deshalb als Warnung.

Das Modul importiert nur die Standardbibliothek: es laeuft als root aus der
root-eigenen Broker-Kopie (``/usr/local/lib/jarvis-broker/backend``) mit dem
System-Python, nicht aus /opt/jarvis (Befund K1).

Aufruf (root):  python3 -I ueberwachung.py --lauf | --zeigen
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ZUSTAND_DATEI = Path("/var/lib/jarvis-ueberwachung/zustand.json")
KONF_DATEI = Path("/etc/jarvis/ueberwachung.conf")
# AIDE-Abgleich (Nachlauf von dailyaidecheck.service, backend/aide_abgleich.py)
AIDE_ZUSTAND = Path("/var/lib/jarvis-aide/abgleich.json")
AIDE_DROPIN = Path("/etc/systemd/system/dailyaidecheck.service.d/80-jarvis-abgleich.conf")
# Der Timer laeuft taeglich um 01:50 mit bis zu 2 h Zufallsverzug (Debian-Unit)
AIDE_VERALTET_S = 2 * 86400 + 3 * 3600

TAKT_S = 300                 # Abstand der Laeufe (Timer)
VERALTET_S = 3 * TAKT_S      # drei verpasste Laeufe = der Waechter steht
HALTE_S = 24 * 3600          # so lange bleibt ein Ereignis sichtbar
VERLAUF_MAX = 10             # so viele Laeufe mit SSH-Fehlversuchen nennt der Befund
ERINNERN_S = 24 * 3600       # anhaltender Alarm: Erinnerung im Journal

# Vorgaben – ueberschreibbar in KONF_DATEI (root-eigen, siehe konf_laden)
VORGABE = {
    "DIENSTE": ("jarvis.service jarvis-broker.service jarvis-firewall.service "
                "jarvis-egress.service whatsapp-bridge.service auditd.service "
                "ssh.service chrony.service sentinelone.service"),
    "PFADE": "/ /var/log",
    "PLATZ_WARNUNG": "15",
    "PLATZ_ALARM": "5",
    "ZERT": "/opt/jarvis/certs/server.crt",
    "ZERT_WARNUNG_TAGE": "30",
    "ZERT_ALARM_TAGE": "7",
    "SSH_UNIT": "ssh.service",
    # Fehlversuche in EINEM Lauf, ab denen es ein Alarm ist (Durchprobieren)
    "SSH_ALARM": "10",
    # nft-in-drop-Zeilen in einem Lauf, ab denen die Drossel als ausgeschoepft
    # gilt: 5/min x 5 min = 25 moeglich
    "IN_WARNUNG": "20",
    "DIENSTBENUTZER": "jarvis",
    "SANDBOX_PRAEFIX": "jarvis_sandbox",
}

STUFEN = ("ok", "info", "warnung", "alarm")
# Zustaende von ``systemctl is-active``, die kein Ausfall sind
UEBERGANG = ("active", "activating", "deactivating", "reloading", "refreshing")


def _rang(stufe: str) -> int:
    return STUFEN.index(stufe) if stufe in STUFEN else 0


# ── Konfiguration ────────────────────────────────────────────────────────────

def konf_laden(pfad: Path = KONF_DATEI) -> dict:
    """Vorgaben plus KONF_DATEI. Gelesen wird nur eine root-eigene Datei, die
    weder Gruppe noch andere beschreiben koennen – sonst bestimmte ein anderer
    Benutzer, welche Dienste und Pfade der root-Waechter (nicht) ansieht. Nur
    bekannte Schluessel; ``source`` waere Codeausfuehrung."""
    konf = dict(VORGABE)
    try:
        st = pfad.stat()
    except OSError:
        return konf
    if st.st_uid != 0 or st.st_mode & 0o022 or not pfad.is_file() or pfad.is_symlink():
        konf["_konf_fehler"] = "%s ist nicht root-eigen oder fremd beschreibbar - ignoriert" % pfad
        return konf
    for zeile in pfad.read_text(encoding="utf-8", errors="replace").splitlines():
        zeile = zeile.strip()
        if not zeile or zeile.startswith("#") or "=" not in zeile:
            continue
        k, v = zeile.split("=", 1)
        k = k.strip()
        if k in VORGABE:
            konf[k] = v.strip().strip('"').strip("'")
    return konf


def _zahl(konf: dict, k: str) -> float:
    try:
        return float(konf.get(k, VORGABE[k]))
    except (TypeError, ValueError):
        return float(VORGABE[k])


# ── Sammeln (nur hier wird das System gefragt) ───────────────────────────────

def _befehl(argv: list[str], timeout: int = 30) -> tuple[int, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           env=dict(os.environ, LC_ALL="C", SYSTEMD_COLORS="0"))
        return p.returncode, p.stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        return 99, str(e)


def _journal(argv: list[str], cursor: str) -> tuple[list[dict], str]:
    """Neue Journal-Eintraege seit ``cursor`` (beim ersten Lauf: die letzten
    zwei Takte). Ein ungueltiger Cursor (Journal rotiert) faellt auf dasselbe
    Fenster zurueck, statt den ganzen Bestand erneut zu melden."""
    basis = ["journalctl", "--no-pager", "-o", "json", "-q"] + argv
    versuche = []
    if cursor:
        versuche.append(basis + ["--after-cursor", cursor])
    versuche.append(basis + ["--since", "-%ds" % (2 * TAKT_S)])
    for argv_ in versuche:
        rc, out = _befehl(argv_, timeout=60)
        if rc != 0:
            continue
        eintraege, neu = [], cursor
        for zeile in out.splitlines():
            try:
                e = json.loads(zeile)
            except ValueError:
                continue
            msg = e.get("MESSAGE", "")
            if isinstance(msg, list):          # nicht-UTF-8: Bytefolge
                msg = bytes(x & 0xFF for x in msg).decode("utf-8", "replace")
            msg = _mit_kennung(str(msg), e.get("SYSLOG_IDENTIFIER"))
            try:
                zeit = int(e.get("__REALTIME_TIMESTAMP", "0")) / 1e6
            except ValueError:
                zeit = 0.0
            eintraege.append({"zeit": zeit, "msg": str(msg)})
            neu = e.get("__CURSOR", neu)
        return eintraege, neu
    return [], cursor


def _mit_kennung(msg: str, kennung) -> str:
    """Eine Zeile, die NICHT der Kernel selbst nach /dev/kmsg schreibt (Facility
    user – z. B. eine Probe als root), zerlegt journald in SYSLOG_IDENTIFIER
    ``nft-out-drop`` und den Rest; das Praefix fehlt dann im Text (auf DEV
    gemessen 2026-11-20). Echte Firewall-Zeilen tragen es im Text. Fuer die
    Auswertung wird beides gleich: Kennung wieder voran."""
    if isinstance(kennung, str) and re.fullmatch(r"nft-(?:in|out|fwd)-drop", kennung) \
            and not msg.startswith(kennung + ":"):
        return kennung + ": " + msg
    return msg


def _uid(name: str) -> int | None:
    try:
        import pwd
        return pwd.getpwnam(name).pw_uid
    except (KeyError, ImportError):
        return None


def _sandbox_uids(praefix: str) -> list[int]:
    try:
        import pwd
        return sorted(p.pw_uid for p in pwd.getpwall() if p.pw_name.startswith(praefix))
    except ImportError:
        return []


def _zert_ablauf(pfad: str) -> tuple[float | None, str]:
    """Ablaufzeit (Epoche) des Zertifikats, oder (None, Grund)."""
    if not Path(pfad).is_file():
        return None, "Datei fehlt: %s" % pfad
    rc, out = _befehl(["openssl", "x509", "-noout", "-enddate", "-dateopt", "iso_8601", "-in", pfad])
    m = re.search(r"notAfter=(\d{4}-\d\d-\d\d) (\d\d:\d\d:\d\d)Z", out) if rc == 0 else None
    if m:
        return _utc(m.group(1) + " " + m.group(2), "%Y-%m-%d %H:%M:%S"), ""
    # Aeltere OpenSSL ohne -dateopt: "notAfter=Nov  9 12:53:09 2028 GMT" (LC_ALL=C)
    rc, out = _befehl(["openssl", "x509", "-noout", "-enddate", "-in", pfad])
    m = re.search(r"notAfter=(\w{3}\s+\d+ \d\d:\d\d:\d\d \d{4}) GMT", out) if rc == 0 else None
    if m:
        return _utc(re.sub(r"\s+", " ", m.group(1)), "%b %d %H:%M:%S %Y"), ""
    return None, "nicht lesbar: %s" % pfad


def _utc(text: str, fmt: str) -> float:
    import calendar
    return float(calendar.timegm(time.strptime(text, fmt)))


def sammeln(konf: dict, vorher: dict) -> dict:
    """Alle Eingaben eines Laufs. Getrennt von ``auswerten``, damit die
    Auswertung ohne System pruefbar ist (tests/test_ueberwachung.py)."""
    eing: dict = {"dienste": {}, "fehlgeschlagen": [], "platz": {}}
    for unit in konf["DIENSTE"].split():
        _, en = _befehl(["systemctl", "is-enabled", unit])
        _, ak = _befehl(["systemctl", "is-active", unit])
        eing["dienste"][unit] = {"enabled": (en.strip().splitlines() or [""])[0],
                                 "active": (ak.strip().splitlines() or [""])[0]}
    rc, out = _befehl(["systemctl", "list-units", "--state=failed", "--no-legend", "--plain", "--all"])
    if rc == 0:
        eing["fehlgeschlagen"] = [z.split()[0] for z in out.splitlines() if z.split()]
    for pfad in konf["PFADE"].split():
        try:
            st = os.statvfs(pfad)
            eing["platz"][pfad] = {"frei": st.f_bavail * st.f_frsize, "gesamt": st.f_blocks * st.f_frsize,
                                   "geraet": os.stat(pfad).st_dev}
        except OSError as e:
            eing["platz"][pfad] = {"fehler": str(e)}
    eing["zert_ablauf"], eing["zert_fehler"] = _zert_ablauf(konf["ZERT"])
    cur = vorher.get("cursor") or {}
    eing["ssh"], c_ssh = _journal(["-u", konf["SSH_UNIT"]], cur.get("ssh", ""))
    eing["kern"], c_kern = _journal(["-k"], cur.get("kern", ""))
    eing["cursor"] = {"ssh": c_ssh, "kern": c_kern}
    eing["uid_dienst"] = _uid(konf["DIENSTBENUTZER"])
    eing["uid_sandbox"] = _sandbox_uids(konf["SANDBOX_PRAEFIX"])
    try:
        eing["aide_eingerichtet"] = AIDE_DROPIN.stat().st_mtime
    except OSError:
        eing["aide_eingerichtet"] = None
    eing["aide"] = _lesen_roh(AIDE_ZUSTAND) or None
    return eing


# ── Auswerten (rein, ohne System) ────────────────────────────────────────────

_IP_PORT = re.compile(r"(?P<ip>(?:\d{1,3}\.){3}\d{1,3}|[0-9A-Fa-f]*:[0-9A-Fa-f:]+) port (?P<port>\d+)")
_IP = re.compile(r"\bfrom (?P<ip>(?:\d{1,3}\.){3}\d{1,3}|[0-9A-Fa-f]*:[0-9A-Fa-f:]+)")
# Zeilen, mit denen eine Verbindung als GESCHEITERT feststeht. "Failed
# publickey" gehoert NICHT dazu: ein Client bietet seine Schluessel der Reihe
# nach an, und mit LogLevel VERBOSE (B9) steht fuer jeden abgelehnten eine
# solche Zeile – auch vor einem "Accepted" (auf ECHT gemessen 2026-11-20).
# Gibt der Client danach auf, folgt "Connection closed by authenticating user".
_SSH_FEHL = re.compile(
    r"^(?:Failed (?:password|keyboard-interactive\S*) for"
    r"|Invalid user "
    r"|Connection (?:closed|reset) by (?:authenticating|invalid) user "
    r"|error: maximum authentication attempts exceeded"
    r"|Disconnecting (?:authenticating|invalid) user .*Too many authentication failures"
    r"|User \S+ from \S+ not allowed because )")
_SSH_OK = re.compile(r"^Accepted \S+ for ")
_SSH_USER = re.compile(r"(?:user|for|User) (?:invalid user )?(?P<u>[^\s]+) (?:from )?")


def ssh_fehlversuche(eintraege: list[dict]) -> list[dict]:
    """Gescheiterte VERBINDUNGEN: je (IP, Port) einmal, auch wenn sshd zwei
    Zeilen dafuer schreibt ("Invalid user x" + "Connection reset by invalid
    user x"); eine Verbindung mit "Accepted" zaehlt nie. Zeilen ohne Port
    (AllowUsers) zaehlen je Zeile."""
    verb: dict = {}
    for i, e in enumerate(eintraege):
        msg = e["msg"].strip()
        m = _IP_PORT.search(msg)
        if m:
            schluessel = "%s:%s" % (m.group("ip"), m.group("port"))
            ip = m.group("ip")
        else:
            mi = _IP.search(msg)
            if not mi:
                continue
            schluessel, ip = "%s:-%d:%d" % (mi.group("ip"), int(e["zeit"]), i), mi.group("ip")
        v = verb.setdefault(schluessel, {"ip": ip, "fehl": False, "ok": False, "zeit": e["zeit"], "user": ""})
        if _SSH_OK.match(msg):
            v["ok"] = True
        elif _SSH_FEHL.match(msg):
            v["fehl"] = True
            v["zeit"] = e["zeit"]
            mu = _SSH_USER.search(msg)
            if mu and not v["user"]:
                v["user"] = mu.group("u")
    return [dict(v, schluessel=k) for k, v in verb.items() if v["fehl"] and not v["ok"]]


_NFT = re.compile(r"nft-(?P<r>in|out|fwd)-drop: ")


def nft_zeilen(eintraege: list[dict]) -> list[dict]:
    aus = []
    for e in eintraege:
        m = _NFT.search(e["msg"])
        if not m:
            continue
        felder = dict(re.findall(r"\b([A-Z]+)=(\S*)", e["msg"][m.end():]))
        aus.append({"richtung": m.group("r"), "zeit": e["zeit"], "src": felder.get("SRC", ""),
                    "dst": felder.get("DST", ""), "dpt": felder.get("DPT", ""),
                    "uid": felder.get("UID", "")})
    return aus


def _befund(bid: str, art: str, stufe: str, text: str, **werte) -> dict:
    return {"id": bid, "art": art, "stufe": stufe, "text": text, "werte": werte}


def _gb(n: float) -> str:
    return ("%.1f GB" % (n / 1e9)).replace(".", ",")


def _uhr(t: float) -> str:
    return time.strftime("%d.%m. %H:%M", time.localtime(t))


def auswerten(eing: dict, vorher: dict, konf: dict, jetzt: float) -> tuple[dict, list[tuple[str, str]]]:
    """Neuer Zustand + Journal-Meldungen [(stufe, text)] aus den Eingaben."""
    befunde: list[dict] = []

    # Dienste. Uebergaenge zaehlen nicht als Ausfall – auch "deactivating"
    # nicht: auf ECHT traf der erste Lauf am 2026-11-21 genau die 5 Sekunden
    # eines Neustarts von jarvis.service und meldete einen Alarm, der keiner
    # war. Ein Neustart durchlaeuft deactivating -> activating ohne "inactive";
    # ein haengendes Beenden endet in failed oder inactive und wird dann gemeldet.
    for unit, z in sorted(eing.get("dienste", {}).items()):
        if z.get("enabled") in ("enabled", "enabled-runtime") \
                and z.get("active") not in UEBERGANG:
            befunde.append(_befund("dienst:" + unit, "dienst_aus", "alarm",
                                   "%s ist aktiviert, laeuft aber nicht (%s)" % (unit, z.get("active") or "?"),
                                   unit=unit, zustand=z.get("active", "")))
    fehl = sorted(set(eing.get("fehlgeschlagen") or []))
    if fehl:
        befunde.append(_befund("failed", "units_failed", "warnung",
                               "Units im Zustand failed: %s" % ", ".join(fehl), units=fehl))

    # Platz – je Dateisystem einmal (auf ECHT liegt /var/log auf /)
    gesehen = set()
    for pfad, p in eing.get("platz", {}).items():
        if "fehler" in p:
            befunde.append(_befund("platz:" + pfad, "platz_fehler", "warnung",
                                   "Freier Platz auf %s nicht messbar: %s" % (pfad, p["fehler"]), pfad=pfad))
            continue
        if p.get("geraet") in gesehen or not p.get("gesamt"):
            continue
        gesehen.add(p.get("geraet"))
        anteil = 100.0 * p["frei"] / p["gesamt"]
        stufe = "alarm" if anteil < _zahl(konf, "PLATZ_ALARM") else \
            "warnung" if anteil < _zahl(konf, "PLATZ_WARNUNG") else ""
        if stufe:
            befunde.append(_befund("platz:" + pfad, "platz", stufe,
                                   "Auf %s sind nur noch %.1f %% frei (%s)" % (pfad, anteil, _gb(p["frei"])),
                                   pfad=pfad, prozent=round(anteil, 1), frei=p["frei"]))

    # Zertifikat
    ab = eing.get("zert_ablauf")
    if ab is None:
        befunde.append(_befund("zert", "zert_fehler", "warnung",
                               "Server-Zertifikat nicht pruefbar: %s" % (eing.get("zert_fehler") or "?"),
                               grund=eing.get("zert_fehler") or ""))
    else:
        tage = (ab - jetzt) / 86400.0
        stufe = "alarm" if tage <= _zahl(konf, "ZERT_ALARM_TAGE") else \
            "warnung" if tage <= _zahl(konf, "ZERT_WARNUNG_TAGE") else ""
        if stufe:
            befunde.append(_befund("zert", "zert_ablauf", stufe,
                                   ("Server-Zertifikat ist abgelaufen (%s)" if tage < 0 else
                                    "Server-Zertifikat laeuft in %d Tagen ab (%%s)" % int(tage))
                                   % time.strftime("%d.%m.%Y", time.localtime(ab)),
                                   tage=int(tage), ablauf=ab))

    # Ereignisse: neue anhaengen, alte (> HALTE_S) verwerfen
    ereignisse = [e for e in (vorher.get("ereignisse") or []) if jetzt - e.get("zeit", 0) <= HALTE_S]
    gezaehlt = {k: t for k, t in (vorher.get("ssh_gezaehlt") or {}).items() if jetzt - t <= HALTE_S}
    ssh_neu = [v for v in ssh_fehlversuche(eing.get("ssh") or []) if v["schluessel"] not in gezaehlt]
    for v in ssh_neu:
        gezaehlt[v["schluessel"]] = v["zeit"] or jetzt
    if len(gezaehlt) > 2000:            # Deckel: ein Durchprobieren darf die Datei nicht aufblaehen
        gezaehlt = dict(sorted(gezaehlt.items(), key=lambda kv: kv[1])[-2000:])
    if ssh_neu:
        letzte = max(ssh_neu, key=lambda v: v["zeit"])
        ereignisse.append({"zeit": jetzt, "art": "ssh", "anzahl": len(ssh_neu),
                           "ip": letzte["ip"], "user": letzte["user"],
                           "ips": sorted({v["ip"] for v in ssh_neu})[:10]})

    uid_dienst = eing.get("uid_dienst")
    sandbox = {str(u) for u in eing.get("uid_sandbox") or []}
    zaehl: dict = {}
    for z in nft_zeilen(eing.get("kern") or []):
        if z["richtung"] == "out":
            art = "out_dienst" if uid_dienst is not None and z["uid"] == str(uid_dienst) else \
                "out_sandbox" if z["uid"] in sandbox else "out_fremd"
        else:
            art = z["richtung"] + "_drop"
        e = zaehl.setdefault(art, {"zeit": jetzt, "art": art, "anzahl": 0, "ziele": [], "uids": []})
        e["anzahl"] += 1
        ziel = "%s:%s" % (z["dst"] if z["richtung"] == "out" else z["src"], z["dpt"])
        if ziel not in e["ziele"] and len(e["ziele"]) < 10:
            e["ziele"].append(ziel)
        if z["uid"] and z["uid"] not in e["uids"]:
            e["uids"].append(z["uid"])
    ereignisse.extend(zaehl.values())

    def summe(art):
        es = [e for e in ereignisse if e["art"] == art]
        return sum(e["anzahl"] for e in es), es

    n, es = summe("ssh")
    if n:
        spitze = max(e["anzahl"] for e in es)
        letzt = es[-1]
        befunde.append(_befund("ssh", "ssh_fehl", "alarm" if spitze >= _zahl(konf, "SSH_ALARM") else "warnung",
                               "%d fehlgeschlagene SSH-Anmeldungen in 24 h, zuletzt %s von %s%s"
                               % (n, _uhr(letzt["zeit"]), letzt["ip"],
                                  (" (Benutzer %s)" % letzt["user"]) if letzt.get("user") else ""),
                               anzahl=n, spitze=spitze, ip=letzt["ip"], user=letzt.get("user", ""),
                               zuletzt=letzt["zeit"],
                               # Die einzelnen Laeufe, juengster zuerst: das Zahnrad
                               # klappt sie auf (ein Klick muss etwas zeigen). Gedeckelt;
                               # die Gesamtzahl steht in "anzahl", "verlauf_gesamt" sagt,
                               # wie viele Laeufe es waren.
                               verlauf=[{"zeit": e["zeit"], "anzahl": e["anzahl"],
                                         "ips": list(e.get("ips") or [e.get("ip", "")])[:10],
                                         "user": e.get("user", "")}
                                        for e in reversed(es)][:VERLAUF_MAX],
                               verlauf_gesamt=len(es)))
    for art, stufe, satz in (
            ("out_dienst", "alarm", "Der Dienstbenutzer wollte ins Netz und wurde abgewiesen: %d Pakete in 24 h, Ziele %s"),
            ("out_fremd", "warnung", "Abgewiesene Verbindungen eines unerwarteten Benutzers (UID %s): %d Pakete in 24 h"),
            ("out_sandbox", "info", "Abgewiesene Internetzugriffe der Sandbox: %d Pakete in 24 h"),
            ("fwd_drop", "info", "Verworfene weitergeleitete Pakete: %d in 24 h")):
        n, es = summe(art)
        if not n:
            continue
        ziele = sorted({z for e in es for z in e.get("ziele", [])})[:10]
        uids = sorted({u for e in es for u in e.get("uids", [])})
        if art == "out_dienst":
            text = satz % (n, ", ".join(ziele))
        elif art == "out_fremd":
            text = satz % (", ".join(uids), n)
        else:
            text = satz % n
        befunde.append(_befund(art, art, stufe, text, anzahl=n, ziele=ziele, uids=uids,
                               zuletzt=es[-1]["zeit"]))
    n, es = summe("in_drop")
    if n:
        spitze = max(e["anzahl"] for e in es)
        voll = spitze >= _zahl(konf, "IN_WARNUNG")
        befunde.append(_befund("in_drop", "in_drop", "warnung" if voll else "info",
                               ("Verworfene eingehende Verbindungen: %d in 24 h" % n)
                               + (" – die Drossel war in einem Lauf ausgeschoepft (%d), es wurde mehr verworfen als protokolliert" % spitze
                                  if voll else ""),
                               anzahl=n, spitze=spitze, quellen=sorted({z for e in es for z in e.get("ziele", [])})[:10],
                               zuletzt=es[-1]["zeit"]))
    if konf.get("_konf_fehler"):
        befunde.append(_befund("konf", "konf_fehler", "warnung", konf["_konf_fehler"]))

    # AIDE-Abgleich: ein offener Abgleich wartet auf die Durchsicht eines
    # Administrators – bis dahin bleibt der alte Stand, und jede Nacht meldet
    # AIDE dieselben Aenderungen weiter. Ein Abgleich, der nicht mehr laeuft,
    # ist selbst ein Befund (dieselbe Ueberlegung wie VERALTET_S).
    if eing.get("aide_eingerichtet"):
        a = eing.get("aide") or {}
        zeit = a.get("zeit") or 0
        if a.get("zustand") == "offen":
            befunde.append(_befund("aide", "aide_offen", "warnung",
                                   "AIDE: %d Aenderung(en) seit dem letzten Stand nicht erklaert (Pruefung %s) – "
                                   "Durchsicht unter Einstellungen > System > Paket-Updates"
                                   % (a.get("offen_anzahl", 0), _uhr(zeit)),
                                   anzahl=a.get("offen_anzahl", 0), kennung=a.get("kennung", "")))
        elif a.get("zustand") == "fehler":
            befunde.append(_befund("aide", "aide_fehler", "warnung",
                                   "AIDE-Abgleich gescheitert: %s" % (a.get("grund") or "?")))
        juengst = zeit or eing["aide_eingerichtet"]
        if jetzt - juengst > AIDE_VERALTET_S:
            befunde.append(_befund("aide_alt", "aide_veraltet", "warnung",
                                   "AIDE-Abgleich seit %s nicht mehr gelaufen" % _uhr(juengst),
                                   zuletzt=juengst))

    # "seit" und "gemeldet" aus dem Vorzustand fortfuehren; Meldungen bei Aenderung
    alt = {b["id"]: b for b in (vorher.get("befunde") or [])}
    meldungen: list[tuple[str, str]] = []
    for b in befunde:
        a = alt.get(b["id"])
        gleich = a is not None and a.get("stufe") == b["stufe"]
        b["seit"] = a.get("seit", jetzt) if gleich else jetzt
        b["gemeldet"] = a.get("gemeldet", 0) if gleich else 0
        if b["stufe"] in ("warnung", "alarm"):
            erinnern = b["stufe"] == "alarm" and jetzt - b["gemeldet"] >= ERINNERN_S
            if not gleich or erinnern or not b["gemeldet"]:
                meldungen.append((b["stufe"], "B13 %s %s: %s" % (b["stufe"].upper(), b["id"], b["text"])))
                b["gemeldet"] = jetzt
    neu_ids = {b["id"] for b in befunde}
    for bid, a in alt.items():
        if bid not in neu_ids and a.get("stufe") in ("warnung", "alarm"):
            meldungen.append(("behoben", "B13 BEHOBEN %s: %s" % (bid, a.get("text", ""))))

    befunde.sort(key=lambda b: (-_rang(b["stufe"]), b["id"]))
    zustand = {
        "version": 1, "zeit": jetzt, "takt_s": TAKT_S,
        "stufe": befunde[0]["stufe"] if befunde else "ok",
        "befunde": befunde, "ereignisse": ereignisse, "ssh_gezaehlt": gezaehlt,
        "cursor": eing.get("cursor") or vorher.get("cursor") or {},
    }
    return zustand, meldungen


# ── Ablage ───────────────────────────────────────────────────────────────────

def _lesen_roh(pfad: Path) -> dict:
    try:
        return json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def schreiben(zustand: dict, pfad: Path = ZUSTAND_DATEI, gruppe: str = "jarvis") -> None:
    """Atomar, root:<gruppe> 0640. Ohne die Gruppe (fremdes System) 0600."""
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pfad.with_name(pfad.name + ".tmp")
    tmp.write_text(json.dumps(zustand, ensure_ascii=False, indent=1), encoding="utf-8")
    modus = 0o600
    try:
        import grp
        os.chown(tmp, 0, grp.getgrnam(gruppe).gr_gid)
        modus = 0o640
    except (KeyError, ImportError, PermissionError):
        pass
    os.chmod(tmp, modus)
    os.replace(tmp, pfad)


def melden(meldungen: list[tuple[str, str]]) -> None:
    import syslog
    prio = {"alarm": syslog.LOG_CRIT, "warnung": syslog.LOG_WARNING, "behoben": syslog.LOG_NOTICE}
    syslog.openlog("jarvis-ueberwachung", 0, syslog.LOG_DAEMON)
    for stufe, text in meldungen:
        syslog.syslog(prio.get(stufe, syslog.LOG_INFO), text)
    syslog.closelog()


def lauf(pfad: Path = ZUSTAND_DATEI) -> int:
    konf = konf_laden()
    vorher = _lesen_roh(pfad)
    jetzt = time.time()
    zustand, meldungen = auswerten(sammeln(konf, vorher), vorher, konf, jetzt)
    schreiben(zustand, pfad)
    melden(meldungen)
    for stufe, text in meldungen:
        print(text)
    print("Stufe: %s, %d Befund(e)" % (zustand["stufe"], len(zustand["befunde"])))
    return 0


# ── Lesen (Dienst, fuer die Anzeige) ─────────────────────────────────────────

def lesen(pfad: Path = ZUSTAND_DATEI, jetzt: float | None = None) -> dict:
    """Fuer die Oberflaeche: Stufe, Befunde, Alter. Ohne Datei heisst es
    "nicht eingerichtet" (kein Alarm – auf einem System ohne B13 waere ein
    Dauerhinweis Laerm); eine VERALTETE Datei ist eine Warnung, denn dann steht
    der Waechter und die Anzeige zeigte sonst einen alten guten Stand."""
    jetzt = time.time() if jetzt is None else jetzt
    if not pfad.exists():
        return {"ok": True, "eingerichtet": False, "stufe": "ok", "befunde": []}
    z = _lesen_roh(pfad)
    if not z or "zeit" not in z:
        return {"ok": True, "eingerichtet": True, "stufe": "warnung", "alter_s": None, "befunde": [
            _befund("lesbar", "unlesbar", "warnung", "Zustand der Ueberwachung nicht lesbar")]}
    alter = max(0.0, jetzt - float(z.get("zeit", 0)))
    befunde = [{k: b.get(k) for k in ("id", "art", "stufe", "text", "werte", "seit")}
               for b in z.get("befunde") or []]
    if alter > VERALTET_S:
        befunde.insert(0, dict(_befund("veraltet", "veraltet", "warnung",
                                       "Die Ueberwachung laeuft nicht: letzter Lauf vor %d Minuten" % (alter // 60),
                                       minuten=int(alter // 60)), seit=z.get("zeit")))
    stufe = max((b["stufe"] for b in befunde), key=_rang, default="ok")
    return {"ok": True, "eingerichtet": True, "stufe": stufe, "zeit": z.get("zeit"),
            "alter_s": int(alter), "veraltet": alter > VERALTET_S, "takt_s": z.get("takt_s", TAKT_S),
            "befunde": befunde}


def main(argv: list[str]) -> int:
    if argv[1:] == ["--lauf"]:
        if os.geteuid() != 0:
            print("ueberwachung.py --lauf: nur als root", file=sys.stderr)
            return 2
        return lauf()
    if argv[1:] == ["--zeigen"]:
        print(json.dumps(lesen(), ensure_ascii=False, indent=1))
        return 0
    print("Aufruf: ueberwachung.py --lauf | --zeigen", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
