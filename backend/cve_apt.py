"""Debian-Paketwerkzeuge fuer die CVE-Pruefung – NUR Standardbibliothek.

Zwei Nutzer, deshalb ohne venv-Abhaengigkeit:
  * ``backend/cve_pruefung.py`` (Dienst, unprivilegiert): Versionsvergleich,
    Kandidaten und Herkunft aus ``apt-cache``.
  * der Root-Broker (Op ``cve_beheben``): laeuft aus einer root-eigenen Kopie
    mit dem SYSTEM-Python (deploy/security/broker_installieren.sh). Ein Import
    von ``packaging`` oder ``requests`` liesse die Op dort mit ImportError
    sterben – und zwar erst im Ernstfall.

⚠ VERSIONSVERGLEICH IN PYTHON STATT ``dpkg --compare-versions``: eine Pruefung
vergleicht einige tausend Versionspaare (jede CVE jedes installierten
Quellpakets). Ein Unterprozess je Vergleich kostete Sekunden bis Minuten. Der
Algorithmus ist der von dpkg (``verrevcmp``) Zeichen fuer Zeichen; der Waechter
``tests/test_cve_pruefung.py`` vergleicht ihn an echten Versionspaaren gegen
``dpkg --compare-versions`` – ein Teilstring-Vergleich wie ``"1.10" > "1.9"``
waere genau die Sorte Fehler, die wie Entwarnung aussieht.

⚠ BEHEBEN (nur als root, ueber den Broker): ``apt-get install --only-upgrade
--no-remove`` fuer GENAU die benannten, installierten Pakete. Kein
``autoremove``, kein Neustart – dieselben Grenzen wie in ``apt_upgrades.py``,
mit derselben Begruendung (ein Aufraeumen entfernt Abhaengigkeiten des Agenten).
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

# Debian-Paketname (Policy 5.6.1) plus optionale Architektur (``libc6:i386``).
PAKETNAME = re.compile(r"^[a-z0-9][a-z0-9+.\-]{0,99}(:[a-z0-9]+)?$")
# Obergrenze je Behebungslauf – ein Ruf mit tausend Namen ist kein Behebungs-,
# sondern ein Systemupgrade, und dafuer ist diese Op nicht da.
MAX_PAKETE = 300
REBOOT_DATEI = "/var/run/reboot-required"
_UMG = {"LANG": "C", "LC_ALL": "C", "LANGUAGE": "C",
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin"}


# ── Versionsvergleich (dpkg verrevcmp) ──────────────────────────────────────

def _ordnung(c: str) -> int:
    if not c or c.isdigit():
        return 0
    if c.isalpha():
        return ord(c)
    if c == "~":
        return -1
    return ord(c) + 256


def _verrev(a: str, b: str) -> int:
    i = j = 0
    la, lb = len(a), len(b)
    while i < la or j < lb:
        erste = 0
        while (i < la and not a[i].isdigit()) or (j < lb and not b[j].isdigit()):
            ac = _ordnung(a[i] if i < la else "")
            bc = _ordnung(b[j] if j < lb else "")
            if ac != bc:
                return ac - bc
            i += 1
            j += 1
        while i < la and a[i] == "0":
            i += 1
        while j < lb and b[j] == "0":
            j += 1
        while i < la and j < lb and a[i].isdigit() and b[j].isdigit():
            if not erste:
                erste = ord(a[i]) - ord(b[j])
            i += 1
            j += 1
        if i < la and a[i].isdigit():
            return 1
        if j < lb and b[j].isdigit():
            return -1
        if erste:
            return erste
    return 0


def _zerlegen(v: str) -> tuple[int, str, str]:
    v = (v or "").strip()
    epoche = 0
    if ":" in v:
        e, v = v.split(":", 1)
        try:
            epoche = int(e)
        except ValueError:
            epoche = 0
    if "-" in v:
        up, rev = v.rsplit("-", 1)
    else:
        up, rev = v, ""
    return epoche, up, rev


def vergleiche(a: str, b: str) -> int:
    """<0, 0, >0 wie ``dpkg --compare-versions``."""
    ea, ua, ra = _zerlegen(a)
    eb, ub, rb = _zerlegen(b)
    if ea != eb:
        return ea - eb
    r = _verrev(ua, ub)
    if r:
        return r
    return _verrev(ra, rb)


# ── apt-cache: Kandidat, Herkunft, Quellversion ─────────────────────────────

def _run(cmd: list[str], timeout: int = 120, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          env=env or _UMG)


def apt_policy(pakete: list[str]) -> dict[str, dict]:
    """Paket -> {installiert, kandidat, sicherheit, quellen}.

    ``sicherheit`` = der KANDIDAT kommt (auch) aus einer ``*-security``-Quelle.
    Das ist die Unterscheidung, an der der Schalter "reguläre Quelle" haengt:
    ``unattended-upgrades`` ist bei uns auf genau diese Quelle begrenzt.
    """
    erg: dict[str, dict] = {}
    if not pakete:
        return erg
    for i in range(0, len(pakete), 200):
        r = _run(["apt-cache", "policy", "--", *pakete[i:i + 200]])
        akt = None
        version_akt = None
        for z in (r.stdout or "").splitlines():
            if z and not z.startswith(" ") and z.endswith(":"):
                name = z[:-1]
                akt = {"installiert": "", "kandidat": "", "sicherheit": False, "quellen": {}}
                erg[name] = akt
                # apt-cache nennt Pakete der Hauptarchitektur ohne Suffix; fuer
                # Fremdarchitekturen ``libc6:i386``. Beide Schreibweisen merken.
                if ":" not in name:
                    erg.setdefault(name + ":" + _arch(), akt)
                version_akt = None
                continue
            if akt is None:
                continue
            s = z.strip()
            if s.startswith("Installed:"):
                akt["installiert"] = s.split(":", 1)[1].strip()
                if akt["installiert"] == "(none)":
                    akt["installiert"] = ""
            elif s.startswith("Candidate:"):
                akt["kandidat"] = s.split(":", 1)[1].strip()
                if akt["kandidat"] == "(none)":
                    akt["kandidat"] = ""
            else:
                # Versionszeile: " *** <ver> <prio>" (installiert) oder
                # "     <ver> <prio>"; die Herkunftszeilen darunter beginnen mit
                # acht Leerzeichen und der Prioritaet.
                m = re.match(r"^ (?:\*\*\*| {3}) (\S+) (-?\d+)$", z)
                if m:
                    version_akt = m.group(1)
                    akt["quellen"].setdefault(version_akt, [])
                    continue
                m = re.match(r"^\s+(-?\d+)\s+(\S+)\s+(\S+)", z)
                if m and version_akt is not None:
                    akt["quellen"][version_akt].append(m.group(3))
        for akt in erg.values():
            k = akt.get("kandidat")
            akt["sicherheit"] = bool(k) and any(
                "-security" in q for q in akt["quellen"].get(k, []))
    return erg


_ARCH = ""


def _arch() -> str:
    global _ARCH
    if not _ARCH:
        try:
            _ARCH = _run(["dpkg", "--print-architecture"], timeout=10).stdout.strip() or "amd64"
        except Exception:  # noqa: BLE001
            _ARCH = "amd64"
    return _ARCH


def quell_versionen(paare: list[tuple[str, str]]) -> dict[tuple[str, str], str]:
    """(Binaerpaket, Version) -> Version des QUELLpakets.

    Meist identisch; abweichend bei binNMU (``+b1``) und bei Paketen, deren
    Binaerversion einem eigenen Schema folgt – ``apt-cache show`` nennt dann
    ``Source: name (version)``. Verglichen wird gegen den Debian Tracker, und
    der fuehrt Versionen des QUELLpakets.
    """
    erg: dict[tuple[str, str], str] = {}
    if not paare:
        return erg
    for i in range(0, len(paare), 150):
        stueck = paare[i:i + 150]
        r = _run(["apt-cache", "show", "--no-all-versions", "--",
                  *[f"{p.split(':')[0]}={v}" for p, v in stueck]])
        name = ver = quelle_ver = ""
        for z in (r.stdout or "").splitlines() + [""]:
            if not z.strip():
                if name and ver:
                    erg[(name, ver)] = quelle_ver or ver
                name = ver = quelle_ver = ""
                continue
            if z.startswith("Package:"):
                name = z.split(":", 1)[1].strip()
            elif z.startswith("Version:"):
                ver = z.split(":", 1)[1].strip()
            elif z.startswith("Source:"):
                m = re.search(r"\(([^)]+)\)", z)
                if m:
                    quelle_ver = m.group(1).strip()
        for p, v in stueck:
            kurz = p.split(":")[0]
            if (kurz, v) in erg:
                erg[(p, v)] = erg[(kurz, v)]
    return erg


def index_alter() -> float:
    """Zeitpunkt (epoch) der letzten Paketindex-Aktualisierung, 0 = unbekannt."""
    ts = 0.0
    for p in ("/var/lib/apt/periodic/update-success-stamp",
              "/var/lib/apt/periodic/update-stamp"):
        try:
            ts = max(ts, os.stat(p).st_mtime)
        except OSError:
            pass
    try:
        for f in Path("/var/lib/apt/lists").glob("*InRelease"):
            ts = max(ts, f.stat().st_mtime)
    except OSError:
        pass
    return ts


def neustart_noetig() -> bool:
    return os.path.exists(REBOOT_DATEI)


# ── Beheben (nur root, ueber den Broker) ────────────────────────────────────

def _status(pakete: list[str]) -> dict[str, str]:
    r = _run(["dpkg-query", "-W", "-f=${db:Status-Abbrev}\t${Package}:${Architecture}\t${Package}\n",
              "--", *pakete], timeout=60)
    erg: dict[str, str] = {}
    for z in (r.stdout or "").splitlines():
        teile = z.split("\t")
        if len(teile) == 3:
            erg[teile[1]] = teile[0].strip()
            erg.setdefault(teile[2], teile[0].strip())
    return erg


def beheben(pakete: list, nur_sicherheit: bool = True, index: bool = False) -> dict:
    """Hebt die benannten INSTALLIERTEN Pakete auf ihren Kandidaten (root).

    Validiert selbst und vertraut dem Aufrufer nichts an: der Broker ist die
    Grenze, das Backend koennte kompromittiert sein. Je Paket gilt:
      * Name nach Debian-Muster, hoechstens MAX_PAKETE Namen,
      * installiert (``ii``) – ``hi`` (zurueckgehalten) wird NICHT angefasst,
      * es gibt einen neueren Kandidaten,
      * bei ``nur_sicherheit`` kommt dieser Kandidat aus einer Sicherheitsquelle.
    Danach Trockenlauf; plant apt eine Entfernung, wird abgebrochen
    (``--no-remove`` sichert dasselbe noch einmal im echten Lauf).
    ``index=True`` aktualisiert vorher den Paketindex (``apt-get update``).
    """
    erg = {"ok": False, "installiert": [], "uebersprungen": {}, "index": None,
           "fehler": "", "ausgabe": "", "neustart_noetig": False}
    if not isinstance(pakete, list) or len(pakete) > MAX_PAKETE:
        erg["fehler"] = f"Paketliste fehlt oder ist zu lang (hoechstens {MAX_PAKETE})"
        return erg
    namen = []
    for p in pakete:
        if not isinstance(p, str) or not PAKETNAME.match(p):
            erg["fehler"] = f"Ungueltiger Paketname: {str(p)[:60]!r}"
            return erg
        if p not in namen:
            namen.append(p)
    umg = dict(_UMG, DEBIAN_FRONTEND="noninteractive", NEEDRESTART_MODE="l")
    if index:
        r = _run(["apt-get", "-q", "-o", "DPkg::Lock::Timeout=300", "update"], timeout=600, env=umg)
        erg["index"] = r.returncode == 0
        if r.returncode != 0:
            erg["ausgabe"] = (r.stderr or r.stdout or "")[-1500:]
    if not namen:
        erg["ok"] = erg["index"] is not False
        return erg
    status = _status(namen)
    pol = apt_policy(namen)
    ziel = []
    for p in namen:
        st = status.get(p, "")
        if st == "hi":
            erg["uebersprungen"][p] = "zurueckgehalten (hold)"
            continue
        if st != "ii":
            erg["uebersprungen"][p] = "nicht installiert"
            continue
        info = pol.get(p) or {}
        k, inst = info.get("kandidat") or "", info.get("installiert") or ""
        if not k or not inst or vergleiche(k, inst) <= 0:
            erg["uebersprungen"][p] = "kein neuerer Stand im Paketindex"
            continue
        if nur_sicherheit and not info.get("sicherheit"):
            erg["uebersprungen"][p] = "neuer Stand nur in der regulaeren Quelle"
            continue
        ziel.append(p)
    if not ziel:
        erg["ok"] = True
        erg["neustart_noetig"] = neustart_noetig()
        return erg
    grund = ["apt-get", "-q", "-y", "--only-upgrade", "--no-remove",
             "-o", "DPkg::Lock::Timeout=300",
             "-o", "Dpkg::Options::=--force-confdef",
             "-o", "Dpkg::Options::=--force-confold"]
    sim = _run([*grund[:2], "-s", *grund[3:], "install", "--", *ziel], timeout=300, env=umg)
    if sim.returncode != 0 or re.search(r"^Remv ", sim.stdout or "", re.M):
        erg["fehler"] = "Trockenlauf abgelehnt (apt wuerde Pakete entfernen oder scheitert)"
        erg["ausgabe"] = ((sim.stdout or "") + (sim.stderr or ""))[-2000:]
        return erg
    geplant = re.findall(r"^Inst (\S+) (?:\[(\S+)\] )?\((\S+)", sim.stdout or "", re.M)
    r = _run([*grund, "install", "--", *ziel], timeout=1800, env=umg)
    erg["ausgabe"] = ((r.stdout or "")[-1500:] + (r.stderr or "")[-500:])
    if r.returncode != 0:
        erg["fehler"] = f"apt-get endete mit {r.returncode}"
        return erg
    erg["installiert"] = [{"paket": n, "von": alt or "", "auf": neu} for n, alt, neu in geplant]
    erg["ok"] = True
    erg["neustart_noetig"] = neustart_noetig()
    return erg
