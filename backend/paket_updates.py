"""Offene Paket-Updates anzeigen, alle einspielen, betroffene Dienste neu starten.

WARUM (gemessen auf ECHT am 24.11.2026): unattended-upgrades spielt bewusst
nur die Sicherheitsquelle ein (``apt_upgrades.py``). Alles andere bleibt
liegen – auf ECHT neun Pakete der Punktausgabe 13.8, darunter OpenSSL
3.5.7 -> 3.5.9, das der HTTPS-Dienst selbst laedt. Die Oberflaeche konnte bis
dahin nur Sicherheitsupdates einspielen oder einzelne Pakete mit CVE heben;
eine Liste aller offenen Updates gab es nicht.

GRENZEN (dieselben wie ``cve_apt.beheben``, aus demselben Grund):
  * nur VORHANDENE Pakete heben (``apt-get upgrade``), ``--no-remove`` und
    vorher ein Trockenlauf – plant apt eine Entfernung, laeuft nichts;
  * kein ``autoremove`` (es entfernte Abhaengigkeiten des Agenten);
  * ``NEEDRESTART_MODE=l``: needrestart LISTET nur, es startet nichts neu;
  * bei Konfigurationskonflikten bleibt die lokale Datei (``--force-confold``).

NACH DEM EINSPIELEN wird die AIDE-Pruefung angestossen; ihr Nachlauf
(``aide_abgleich.py``) uebernimmt den neuen Stand nur, wenn jede Aenderung
erklaert ist.

NEUSTART EINES DIENSTES nur fuer einen Dienst, den needrestart IN DIESEM
AUGENBLICK nennt, und nie fuer die Sperrliste ``_NIE_NEUSTARTEN``: dbus und
logind legen das System lahm, lightdm beendet die Desktop-Sitzung, ueber die
die Desktop-Steuerung laeuft, und ein Oneshot wie ``apt-daily-upgrade`` wuerde
dabei einen Update-Lauf ausloesen (alle drei nennt needrestart auf DEV).

Laeuft als root ueber den Broker (Ops ``paket_updates_status``,
``paket_updates_einspielen``, ``dienst_neustart``), nur Standardbibliothek.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_UMG = {"LANG": "C", "LC_ALL": "C", "LANGUAGE": "C",
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin"}
APT_GET = "/usr/bin/apt-get"
NEEDRESTART = "/usr/sbin/needrestart"
REBOOT_DATEI = "/var/run/reboot-required"
INDEX_TIMEOUT = 600
EINSPIEL_TIMEOUT = 2400

_INST = re.compile(r"^Inst (?P<name>\S+)(?: \[(?P<von>[^\]]*)\])? \((?P<nach>\S+) (?P<quelle>[^\[]*?)\s*\[[^\]]*\]\)")
_REMV = re.compile(r"^Remv (\S+)")
_DIENST = re.compile(r"^[A-Za-z0-9@._:-]{1,120}\.service$")
_NIE_NEUSTARTEN = re.compile(
    r"^(?:dbus|dbus-broker|systemd-[^.]+|user@[^.]*|user-runtime-dir@[^.]*|getty@[^.]*"
    r"|serial-getty@[^.]*|autovt@[^.]*|lightdm|gdm3?|sddm|display-manager|emergency|rescue"
    r"|apt-daily|apt-daily-upgrade|unattended-upgrades|dailyaidecheck|dailyaidecheck-buildcache"
    r")\.service$")
# Diese beiden beenden den Aufrufer mit – der Neustart kommt verzoegert,
# damit die Antwort noch zurueckgeht.
_SELBST = ("jarvis.service", "jarvis-broker.service")


def _run(cmd: list[str], timeout: int = 120, env: dict | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env or _UMG)
    except subprocess.TimeoutExpired as ex:
        return subprocess.CompletedProcess(cmd, 124, ex.stdout or "", "Zeitdeckel %d s erreicht" % timeout)
    except OSError as ex:
        return subprocess.CompletedProcess(cmd, 127, "", str(ex))


def plan_lesen(text: str) -> dict:
    """``apt-get -s upgrade`` (LANG=C) -> Pakete, Entfernungen, zurueckgehaltene."""
    pakete, entfernt, zurueck = [], [], []
    im_zurueck = False
    for zeile in (text or "").splitlines():
        if zeile.startswith("The following packages have been kept back"):
            im_zurueck = True
            continue
        if im_zurueck:
            if zeile.startswith(" "):
                zurueck.extend(zeile.split())
                continue
            im_zurueck = False
        m = _INST.match(zeile)
        if m:
            quelle = m.group("quelle").strip()
            pakete.append({"name": m.group("name"), "von": m.group("von") or "",
                           "nach": m.group("nach"), "quelle": quelle,
                           "sicherheit": "-security" in quelle or "Debian-Security" in quelle,
                           "neu": m.group("von") is None})
            continue
        m = _REMV.match(zeile)
        if m:
            entfernt.append(m.group(1))
    return {"pakete": pakete, "entfernt": entfernt, "zurueckgehalten": zurueck}


def needrestart_lesen(text: str) -> dict:
    """``needrestart -b -r l`` -> Kernelstand und Dienste mit altem Stand."""
    erg = {"kernel_aktuell": "", "kernel_neu": "", "kernel_neustart": False, "dienste": []}
    for zeile in (text or "").splitlines():
        k, _, v = zeile.partition(": ")
        v = v.strip()
        if k == "NEEDRESTART-KCUR":
            erg["kernel_aktuell"] = v
        elif k == "NEEDRESTART-KEXP":
            erg["kernel_neu"] = v
        elif k == "NEEDRESTART-KSTA":
            # 0 unbekannt, 1 aktuell, 2 ABI-gleicher, 3 neuer Kernel installiert
            erg["kernel_neustart"] = v in ("2", "3")
        elif k == "NEEDRESTART-SVC" and _DIENST.match(v) and v not in erg["dienste"]:
            erg["dienste"].append(v)
    return erg


def neustartbar(dienst: str) -> tuple[bool, str]:
    """Darf die Oberflaeche diesen Dienst neu starten? (Grund bei Nein)"""
    if not _DIENST.match(dienst or ""):
        return False, "kein gueltiger Dienstname"
    if _NIE_NEUSTARTEN.match(dienst):
        return False, "nur mit einem Neustart des Servers"
    return True, ""


def _neustart_info() -> dict:
    if not Path(NEEDRESTART).exists():
        return {"verfuegbar": False, "dienste": [], "kernel_neustart": False}
    r = _run([NEEDRESTART, "-b", "-r", "l"], timeout=90)
    erg = needrestart_lesen(r.stdout)
    erg["verfuegbar"] = r.returncode == 0
    erg["dienste"] = [{"name": d, "neustartbar": neustartbar(d)[0], "grund": neustartbar(d)[1]}
                      for d in erg["dienste"]]
    return erg


def _plan() -> tuple[dict, str]:
    r = _run([APT_GET, "-s", "-q", "-o", "Debug::NoLocking=1", "upgrade"], timeout=180)
    if r.returncode != 0:
        return {"pakete": [], "entfernt": [], "zurueckgehalten": []}, (r.stderr or r.stdout or "")[-600:]
    return plan_lesen(r.stdout), ""


def status() -> dict:
    """Offene Updates, Dienste mit altem Stand, Neustartbedarf (aendert nichts)."""
    from backend import cve_apt
    plan, fehler = _plan()
    return {"ok": not fehler, "fehler": fehler, **plan,
            "index_alter": cve_apt.index_alter(),
            "neustart": _neustart_info(),
            "server_neustart": Path(REBOOT_DATEI).exists()}


def _versionen(namen: list[str]) -> dict:
    if not namen:
        return {}
    r = _run(["dpkg-query", "-W", "-f=${Package}\t${Version}\n", *namen], timeout=60)
    erg = {}
    for z in (r.stdout or "").splitlines():
        teile = z.split("\t")
        if len(teile) == 2:
            erg[teile[0]] = teile[1]
    return erg


def _news(ausgabe: str) -> str:
    """Die NEWS-Eintraege, die apt-listchanges ausgibt – nur, wenn es welche gibt.

    Die Statuszeile "apt-listchanges: Reading changelogs..." steht in JEDER
    Ausgabe; wer an ihr schneidet, zeigt den Fortschritt von dpkg als
    "Hinweise" (auf DEV am 24.11.2026 so gesehen). Echte Eintraege stehen unter
    der Ueberschrift "apt-listchanges: News" und enden vor der Ausgabe von
    dpkg ("(Reading database").
    """
    i = ausgabe.find("apt-listchanges: News")
    if i < 0:
        return ""
    ende = ausgabe.find("(Reading database", i)
    return ausgabe[i:ende if ende > 0 else i + 4000][:4000].strip()


def einspielen() -> dict:
    """Alle offenen Updates einspielen (Grenzen siehe Modul-Docstring)."""
    from backend import aide_abgleich
    steps = []

    def step(name, ok, detail=""):
        steps.append({"name": name, "ok": bool(ok), "detail": (detail or "")[:400]})

    umg = dict(_UMG, DEBIAN_FRONTEND="noninteractive", NEEDRESTART_MODE="l",
               APT_LISTCHANGES_FRONTEND="text")
    r = _run([APT_GET, "-q", "-o", "DPkg::Lock::Timeout=300", "update"], timeout=INDEX_TIMEOUT, env=umg)
    step("Paketindex aktualisiert", r.returncode == 0, (r.stderr or r.stdout or "")[-300:])
    plan, fehler = _plan()
    if fehler:
        step("Trockenlauf", False, fehler)
        return {"ok": False, "steps": steps, "status": status()}
    if plan["entfernt"]:
        step("Trockenlauf: apt wuerde Pakete ENTFERNEN – abgebrochen", False, ", ".join(plan["entfernt"][:20]))
        return {"ok": False, "steps": steps, "status": status()}
    if not plan["pakete"]:
        step("Keine offenen Updates", True)
        return {"ok": True, "steps": steps, "eingespielt": [], "status": status()}
    namen = [p["name"] for p in plan["pakete"]]
    vorher = _versionen(namen)
    step("Trockenlauf: %d Paket(e), nichts wird entfernt" % len(namen), True)
    r = _run([APT_GET, "-y", "-q", "-o", "DPkg::Lock::Timeout=300",
              "-o", "Dpkg::Options::=--force-confdef", "-o", "Dpkg::Options::=--force-confold",
              "--no-remove", "upgrade"], timeout=EINSPIEL_TIMEOUT, env=umg)
    ausgabe = (r.stdout or "") + (r.stderr or "")
    nachher = _versionen(namen)
    eingespielt = [{"name": n, "von": vorher.get(n, ""), "nach": nachher.get(n, "")}
                   for n in namen if nachher.get(n) and nachher.get(n) != vorher.get(n)]
    step("%d von %d Paket(en) eingespielt" % (len(eingespielt), len(namen)), r.returncode == 0,
         ausgabe[-400:] if r.returncode != 0 else "")
    if eingespielt:
        a = aide_abgleich.pruefung_starten()
        step("AIDE-Pruefung angestossen – der Abgleich laeuft danach von selbst"
             if a.get("ok") else "AIDE-Pruefung nicht angestossen", a.get("ok"),
             a.get("fehler") or a.get("hinweis") or "")
    return {"ok": r.returncode == 0, "steps": steps, "eingespielt": eingespielt,
            "hinweise": _news(ausgabe), "ausgabe": ausgabe[-2000:], "status": status()}


def dienst_neustart(dienst: str) -> dict:
    """Einen Dienst neu starten, den needrestart JETZT nennt (Grenzen oben)."""
    ok, grund = neustartbar(dienst)
    if not ok:
        return {"ok": False, "fehler": "%s: %s" % (dienst, grund)}
    genannt = [d["name"] for d in _neustart_info().get("dienste", [])]
    if dienst not in genannt:
        return {"ok": False, "fehler": "%s laeuft nicht mehr mit altem Stand – nichts zu tun" % dienst}
    r = _run(["systemctl", "show", "-p", "Type", "--value", dienst], timeout=20)
    if (r.stdout or "").strip() == "oneshot":
        return {"ok": False, "fehler": "%s ist ein einmaliger Auftrag – ein Neustart wuerde ihn ausloesen" % dienst}
    if dienst in _SELBST:
        # Verzoegert, damit die Antwort an den Aufrufer noch zurueckgeht
        r = _run(["systemd-run", "--on-active=3", "--unit=jarvis-neustart-%s" % dienst.split(".")[0],
                  "--collect", "/usr/bin/systemctl", "restart", dienst], timeout=30)
        return {"ok": r.returncode == 0, "verzoegert": True, "dienst": dienst,
                "fehler": "" if r.returncode == 0 else (r.stderr or r.stdout or "")[-300:]}
    r = _run(["systemctl", "restart", dienst], timeout=180)
    return {"ok": r.returncode == 0, "dienst": dienst,
            "fehler": "" if r.returncode == 0 else (r.stderr or r.stdout or "")[-300:]}
