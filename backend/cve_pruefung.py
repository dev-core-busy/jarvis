"""Sicherheitsluecken (CVE) der installierten Pakete pruefen und auf Wunsch beheben.

WAS GEPRUEFT WIRD – alles, was auf DIESEM Server installiert ist, und nur das:
  * Debian-Pakete gegen den Debian Security Tracker (einzige Quelle, Festlegung
    des Betreibers 2026-10-29). Der Tracker kennt fuer jede CVE und jedes
    Release die behebende Version, die Einstufung (``unimportant`` …) und ob
    Debian sie ueber eine Sicherheitsmeldung (DSA) oder erst im Zwischenrelease
    behebt.
  * Python-Pakete der venv (inkl. Skill-Pakete) ueber OSV – der Tracker kennt
    keine PyPI-Pakete. Mitbenutzt wird ``abhaengigkeiten.schwachstellen``.
  * npm-Pakete der WhatsApp-Bridge ueber OSV – NUR, wenn sie installiert ist
    (``node_modules`` vorhanden). Die ``package-lock.json`` liegt im Repo und
    damit auf jedem Server; sie allein heisst nicht, dass etwas laeuft.
  * die Node.js-LAUFZEIT gegen die Luecken-Datenbank der Node.js Security WG
    und deren Release-Plan – NUR, wenn sie nicht aus Debian stammt (NodeSource,
    Tarball); Debians nodejs prueft der Tracker.
  * Pakete, die aus keiner Debian-Quelle dieses Releases stammen, werden
    GENANNT (``bereiche.debian.fremd``) – der Tracker kann sie nicht pruefen.
Was NICHT geprueft wurde, steht mit Grund im Ergebnis (``bereiche``) – eine
fehlende Pruefung darf nicht wie "keine Luecken" aussehen.

⚠ DEBIAN FUEHRT LUECKEN UNTER DEM QUELLPAKET. ``libbrotli1`` hat keinen
Eintrag, ``brotli`` schon. Wer mit dem Binaerpaket sucht, findet nichts – und
die Null sieht wie Entwarnung aus. Verglichen wird deshalb ``${source:Version}``
gegen ``fixed_version`` des Trackers.

⚠ DER KERNEL IST EIN SONDERFALL: ein neuer Kernel ist ein NEUES Binaerpaket
(``linux-image-6.12.113+deb13-amd64``), das alte bleibt installiert. Massgeblich
ist der LAUFENDE Kernel; liegt die Behebung schon installiert daneben, heisst
die Abhilfe "Neustart", nicht "Update". Gehoben wird ueber die Metapakete
(``linux-image-amd64``) – deren QUELLE ist ``linux-signed-amd64`` mit eigener
Versionsform (``6.12.113+1``), verglichen wird deshalb deren BINAERversion.

⚠ EINSTUFUNG: Debian vergibt fuer rund 95 % der trixie-Eintraege KEINE
Einstufung ("not yet assigned"), darunter fast alle mit Sicherheitsmeldung. Die
Schwelle der automatischen Behebung sortiert deshalb nur das aus, was Debian
AUSDRUECKLICH niedrig einstuft; nicht eingestufte Luecken werden immer behoben.
Eine Schwelle "ab hoch" waere eine Funktionssperre (133 von ~67.000 Eintraegen).

⚠ SPEICHER: der Tracker ist ~87 MB JSON; geladen belegt er ~350 MB. Deshalb
laeuft der Debian-Teil in einem EIGENEN Prozess (``python -m
backend.cve_pruefung --debian``) – der Dienst bekommt den Speicher sonst nie
zurueck.

BEHEBEN: Debian ueber die Broker-Op ``cve_beheben`` (``backend/cve_apt.py``:
nur benannte, installierte Pakete, ``--only-upgrade --no-remove``, kein
Aufraeumen, kein Neustart). Python ueber ``abhaengigkeiten.abgleichen`` mit
dessen Regeln (Grenzen, Ausnahmen, Ruecknahme; im Lock-Modus nur melden).
npm wird nur gemeldet. Node.js (als Paket einer Fremdquelle) nur ueber das
Einzel-Update, nie automatisch.
"""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from backend import cve_apt

WURZEL = Path(__file__).resolve().parent.parent
DATEN = Path(os.environ.get("JARVIS_CVE_DATEN", str(WURZEL / "data" / "cve")))
ERGEBNIS = DATEN / "ergebnis.json"
EINSTELLUNGEN = DATEN / "einstellungen.json"
QUITTIERT = DATEN / "quittiert.json"
TRACKER_CACHE = DATEN / "debian_tracker.json.gz"
TRACKER_META = DATEN / "debian_tracker.meta.json"
TRACKER_URL = os.environ.get("JARVIS_CVE_TRACKER",
                             "https://security-tracker.debian.org/tracker/data/json")
TRACKER_LINK = "https://security-tracker.debian.org/tracker/"
# Groesser als jeder bisher gesehene Stand (87 MB entpackt, 14 MB gepackt) –
# ein Deckel gegen eine Antwort, die den Speicher fuellt.
TRACKER_MAX_BYTES = 400 * 1024 * 1024
BRIDGE = WURZEL / "services" / "whatsapp-bridge"
# Node.js-Laufzeit: Luecken-Datenbank der Node.js Security WG (je Eintrag CVE,
# betroffene und behobene semver-Bereiche, Einstufung) und der Release-Plan
# (Ende der Unterstuetzung je Hauptversion). Beide klein (~150 KB / ~3 KB).
NODE_DB_URL = os.environ.get(
    "JARVIS_CVE_NODE_DB",
    "https://raw.githubusercontent.com/nodejs/security-wg/main/vuln/core/index.json")
NODE_PLAN_URL = os.environ.get(
    "JARVIS_CVE_NODE_PLAN",
    "https://raw.githubusercontent.com/nodejs/Release/main/schedule.json")
NODE_DB_CACHE = DATEN / "node_core.json"
NODE_PLAN_CACHE = DATEN / "node_plan.json"
NODE_MAX_BYTES = 20 * 1024 * 1024
NODE_EINSTUFUNGEN = ("low", "medium", "high", "critical")
OSV_BATCH = os.environ.get("JARVIS_ABH_OSV", "https://api.osv.dev/v1/querybatch")
OSV_VULN = os.environ.get("JARVIS_ABH_OSV_VULN", "https://api.osv.dev/v1/vulns/")
# Veroeffentlichungsdatum je Kennung – der Debian-Tracker fuehrt keines, OSV
# schon (fuer CVE-Kennungen das NVD-Datum). Es aendert sich nicht, deshalb
# dauerhaft gecacht; nur Unbekanntes wird nach VEROEFF_NEU_S erneut gefragt.
VEROEFF = DATEN / "veroeffentlicht.json"
VEROEFF_NEU_S = 7 * 86400
VEROEFF_DECKEL_S = 180
VEROEFF_PARALLEL = 8
_DATUM = re.compile(r"^\d{4}-\d{2}-\d{2}")

SCHWELLEN = ("alle", "ab_niedrig", "ab_mittel")
VORGABEN = {"schwelle": "ab_niedrig", "regulaere_quelle": False}
# Debian-Einstufung -> Rang. Fehlt sie ("not yet assigned"), gilt None.
RANG = {"unimportant": 0, "low": 1, "medium": 2, "high": 3}
SCHWELLE_RANG = {"alle": 0, "ab_niedrig": 1, "ab_mittel": 2}
# Diese Klassen kann der Administrator als gesehen markieren: er kann an ihnen
# nichts tun. "behebbar" und "neustart" bleiben stehen, bis sie erledigt sind.
QUITTIERBAR = ("offen", "nicht_im_index", "zurueckgehalten")
# "lock": Python-Paket mit bekannter Behebung auf einem Server im Lock-Modus
# (JARVIS_ABH_LOCK=1). Dort hebt der Server NIE selbst – behoben wird ueber eine
# neue requirements.lock im Repo (deploy/lock_erneuern.py). Als eigene Klasse,
# weil "behebbar" hier eine falsche Zusage waere: auf DEV am 2026-10-29 stand
# "7 behebbar · behebt automatisch · 0 gehoben" ohne jeden Grund da.
KLASSEN = ("behebbar", "neustart", "nicht_im_index", "zurueckgehalten", "lock", "offen",
           "ausgenommen")
_META_KERNEL = re.compile(r"^linux-(image|headers)-(?!\d)[a-z0-9-]+$")
_KERNEL_VERSIONIERT = re.compile(r"^linux-(image|headers|modules|kbuild)-\d")

_sperre = threading.Lock()
_status = {"laeuft": False, "seit": 0.0, "schritt": "", "ausloeser": ""}
_cache = {"mtime": None, "wert": None}


# ── Hilfen ───────────────────────────────────────────────────────────────────

def _lesen(pfad: Path, vorgabe):
    try:
        return json.loads(pfad.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return vorgabe
    except (OSError, ValueError):
        return vorgabe


def _schreiben(pfad: Path, daten) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pfad.with_name(pfad.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(daten, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, pfad)


def release() -> str:
    try:
        for z in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if z.startswith("VERSION_CODENAME="):
                return z.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return ""


def laufender_kernel() -> str:
    """Debian-Version des LAUFENDEN Kernels (``6.12.107-1``), '' = unbekannt."""
    m = re.search(r"Debian (\S+)", os.uname().version)
    return m.group(1) if m else ""


def debian_pakete() -> list[dict]:
    """Installierte Debian-Pakete samt Quellpaket und Quellversion."""
    fmt = ("${db:Status-Abbrev}\t${Package}\t${Architecture}\t${Version}"
           "\t${source:Package}\t${source:Version}\n")
    r = subprocess.run(["dpkg-query", "-W", "-f=" + fmt], capture_output=True, text=True,
                       timeout=60, env={"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"})
    erg = []
    for z in (r.stdout or "").splitlines():
        t = z.split("\t")
        if len(t) != 6:
            continue
        st = t[0].strip()
        # Zweiter Buchstabe = tatsaechlicher Zustand (wie system_packages.py):
        # ``ii``/``hi`` installiert, ``rc`` nicht.
        if len(st) < 2 or st[1] != "i":
            continue
        erg.append({"paket": t[1], "arch": t[2], "version": t[3], "quelle": t[4] or t[1],
                    "quell_version": t[5] or t[3], "status": st})
    return erg


def _apt_name(p: dict, native: str) -> str:
    return p["paket"] if p["arch"] in ("all", native) else f"{p['paket']}:{p['arch']}"


# ── Debian Tracker ───────────────────────────────────────────────────────────

def tracker_holen() -> dict:
    """Laedt den Tracker, wenn er sich geaendert hat (If-Modified-Since).

    Rueckgabe: {ok, stand, hinweis}. Scheitert der Abruf und liegt ein
    frueherer Stand vor, wird dieser benutzt – mit Hinweis, nicht still.
    """
    meta = _lesen(TRACKER_META, {})
    kopf = {"Accept-Encoding": "gzip", "User-Agent": "jarvis-cve-pruefung"}
    if TRACKER_CACHE.is_file() and meta.get("last_modified"):
        kopf["If-Modified-Since"] = meta["last_modified"]
    try:
        anf = urllib.request.Request(TRACKER_URL, headers=kopf)
        with urllib.request.urlopen(anf, timeout=180) as a:  # nosec B310 – feste https-Adresse
            roh = a.read(TRACKER_MAX_BYTES + 1)
            if len(roh) > TRACKER_MAX_BYTES:
                raise ValueError("Antwort des Trackers ist unplausibel gross")
            if (a.headers.get("Content-Encoding") or "").lower() != "gzip":
                roh = gzip.compress(roh, compresslevel=6)
            DATEN.mkdir(parents=True, exist_ok=True)
            tmp = TRACKER_CACHE.with_name(TRACKER_CACHE.name + ".tmp")
            tmp.write_bytes(roh)
            os.replace(tmp, TRACKER_CACHE)
            meta = {"last_modified": a.headers.get("Last-Modified") or "",
                    "geholt": time.time()}
            _schreiben(TRACKER_META, meta)
        return {"ok": True, "stand": meta.get("last_modified", ""), "hinweis": ""}
    except urllib.error.HTTPError as e:
        if e.code == 304:
            meta["geprueft"] = time.time()
            _schreiben(TRACKER_META, meta)
            return {"ok": True, "stand": meta.get("last_modified", ""), "hinweis": ""}
        fehler = f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        fehler = f"{type(e).__name__}: {e}"
    if TRACKER_CACHE.is_file():
        return {"ok": True, "stand": meta.get("last_modified", ""),
                "hinweis": f"Tracker nicht erreichbar ({fehler}) – gespeicherter Stand benutzt"}
    return {"ok": False, "stand": "", "hinweis": f"Tracker nicht erreichbar ({fehler})"}


def tracker_auszug(quellen: set[str], rel: str) -> dict:
    """Nur die Eintraege der installierten Quellpakete fuer dieses Release.

    ``anderswo`` haelt fest, in welchen ANDEREN Debian-Releases die Luecke
    behoben ist (Release -> Version). Fuer einen offenen Befund ist das die
    einzige Auskunft, ob es ueberhaupt eine Behebung gibt – ohne sie sieht
    "offen" wie "niemand hat etwas" aus (7zip, 2026-10-29: in trixie 13 offen,
    11 davon in forky/sid behoben).
    """
    with gzip.open(TRACKER_CACHE, "rt", encoding="utf-8") as f:
        alles = json.load(f)
    aus: dict = {}
    for q in quellen:
        for cve, e in (alles.get(q) or {}).items():
            rels = e.get("releases") or {}
            r = rels.get(rel)
            if r:
                # fixed_version "0" heisst "nie betroffen" – keine Behebung.
                anderswo = {n: str(o.get("fixed_version"))
                            for n, o in rels.items()
                            if n != rel and o.get("status") == "resolved"
                            and str(o.get("fixed_version") or "0") != "0"}
                aus.setdefault(q, {})[cve] = {"r": r, "text": (e.get("description") or "")[:240],
                                              "anderswo": anderswo}
    return aus


def _anderswo_gruppen(anderswo: dict) -> list[dict]:
    """Release -> Version zu [{version, releases}], hoechste Version zuerst."""
    je: dict[str, list[str]] = {}
    for n, v in anderswo.items():
        je.setdefault(v, []).append(n)
    return [{"version": v, "releases": sorted(je[v])}
            for v in sorted(je, key=_vschluessel, reverse=True)]


# ── Debian bewerten (rein, testbar) ──────────────────────────────────────────

def debian_bewerten(pakete: list[dict], auszug: dict, rel: str, kernel: str = "") -> list[dict]:
    """Befunde je (Quellpaket, CVE) – OHNE Paketindex (der kommt danach).

    Klassen hier: ``fix`` (Debian hat behoben, installiert ist aelter),
    ``neustart`` (Kernel: Behebung installiert, laeuft noch nicht) und
    ``offen`` (in diesem Release keine Behebung).
    """
    gruppen: dict[str, list[dict]] = {}
    for p in pakete:
        gruppen.setdefault(p["quelle"], []).append(p)
    befunde = []
    for quelle in sorted(gruppen):
        bins = gruppen[quelle]
        ist_kernel = quelle == "linux" and bool(kernel)
        for cve in sorted(auszug.get(quelle) or {}):
            e = auszug[quelle][cve]
            r = e["r"]
            status = r.get("status") or ""
            fv = r.get("fixed_version") or ""
            einst = (r.get("urgency") or "").rstrip("*").strip()
            if einst not in RANG:
                einst = ""
            repos = r.get("repositories") or {}
            sich = repos.get(f"{rel}-security") or ""
            b = {"bereich": "debian", "quelle": quelle, "cve": cve, "einstufung": einst,
                 "fix": "", "aus_sicherheitsmeldung": False, "zwischenrelease": False,
                 # Zwei Felder, nicht eines: ``nodsa`` ist die Begruendung
                 # ("Only affects Windows NTFS …"), ``nodsa_reason`` die Art
                 # ("ignored" = behebt Debian hier nicht, "postponed" =
                 # verschoben, "" = ohne Sicherheitsmeldung). Frueher stand
                 # die Art an Stelle des Textes, die Begruendung fiel weg.
                 "nodsa": str(r.get("nodsa") or ""),
                 "nodsa_grund": str(r.get("nodsa_reason") or ""),
                 "text": e.get("text") or "", "kernel": ist_kernel}
            if status == "resolved":
                # fixed_version "0" (nie betroffen) braucht KEINEN eigenen Zweig:
                # jede Version ist >= 0, der Vergleich unten verwirft es ohnehin.
                # Die Gegenprobe hat die doppelte Bedingung als stumm gezeigt.
                if not fv:
                    continue
                if ist_kernel:
                    if cve_apt.vergleiche(kernel, fv) >= 0:
                        continue
                    neu = [p for p in bins if cve_apt.vergleiche(p["quell_version"], fv) >= 0]
                    b["pakete"] = sorted({p["paket"] for p in neu}) or ["linux"]
                    b["version"] = kernel
                    b["klasse"] = "neustart" if neu else "fix"
                else:
                    alt = [p for p in bins if cve_apt.vergleiche(p["quell_version"], fv) < 0]
                    if not alt:
                        continue
                    b["pakete"] = sorted({p["paket"] for p in alt})
                    b["version"] = min((p["quell_version"] for p in alt),
                                       key=_vschluessel)
                    b["klasse"] = "fix"
                b["fix"] = fv
                b["aus_sicherheitsmeldung"] = bool(sich) and cve_apt.vergleiche(sich, fv) >= 0
                b["zwischenrelease"] = bool(r.get("next_point_update"))
            elif status in ("open", "undetermined"):
                b["pakete"] = sorted({p["paket"] for p in bins})
                b["version"] = kernel if ist_kernel else bins[0]["quell_version"]
                b["klasse"] = "offen"
                # Auch ein offener Eintrag kann fuers naechste Zwischenrelease
                # eingeplant sein (Tracker: next-point-update.txt).
                b["zwischenrelease"] = bool(r.get("next_point_update"))
                b["anderswo"] = _anderswo_gruppen(e.get("anderswo") or {})
            else:
                continue
            befunde.append(b)
    return befunde


class _vschluessel:
    """Sortierschluessel nach Debian-Versionsordnung (fuer ``min``)."""

    def __init__(self, v):
        self.v = v

    def __lt__(self, o):
        return cve_apt.vergleiche(self.v, o.v) < 0


def fremde_herkunft(info: dict, rel: str) -> bool:
    """Stammt der INSTALLIERTE Stand nicht aus einer Debian-Quelle dieses Releases?

    ⚠ AUF DEV GEMESSEN (2026-10-29): ``nodejs 24.22.2-1nodesource1`` kommt von
    NodeSource, traegt aber denselben Quellpaketnamen wie Debians nodejs 20 –
    ohne diese Pruefung bekam es zehn Debian-Luecken angehaengt, die fuer
    dieses Paket nicht gelten. Entschieden wird an der SUITE der Herkunft
    (``trixie``, ``trixie-security``, ``trixie-updates``, ``trixie-backports``),
    nicht am Rechnernamen – ein Spiegelserver heisst beliebig.
    Ein installierter Stand OHNE Herkunftszeile (nur ``/var/lib/dpkg/status``)
    ist der Regelfall eines veralteten Debian-Pakets und zaehlt NICHT als
    fremd, solange das Paket ueberhaupt in einer Release-Suite vorkommt.
    """
    q = info.get("quellen") or {}
    eigene = q.get(info.get("installiert") or "", [])
    passt = lambda suiten: any(x.split("/")[0].startswith(rel) for x in suiten)  # noqa: E731
    if eigene:
        return not passt(eigene)
    alle = [x for v in q.values() for x in v]
    return not passt(alle)


def herkunft_pruefen(befunde: list[dict], pakete: list[dict], rel: str) -> list[str]:
    """Nimmt Binaerpakete fremder Herkunft aus den Befunden; liefert ihre Namen.

    Ein Befund ohne verbleibendes Paket faellt weg – er betraf nur Fremdes.

    ⚠ GEFRAGT WERDEN ALLE INSTALLIERTEN PAKETE, nicht nur die mit Befund. Bis
    2026-10-29 stand hier nur, was der Tracker kannte – ein Fremdpaket, dessen
    Name in Debian nicht vorkommt (``google-chrome-stable``, ``sentinelagent``
    auf ECHT), bekam nie einen Befund und tauchte deshalb auch in der Liste
    "nicht ueber Debian pruefbar" nie auf: es sah aus wie "keine Luecken".
    Kosten gemessen: ``apt-cache policy`` ueber 2331 Pakete 1,7 s (DEV).
    Ohne Policy-Auskunft (apt-cache ohne Eintrag) wird nichts behauptet – das
    Paket gilt weder als fremd noch wird sein Befund entfernt.
    """
    native = cve_apt._arch()
    nach_name = {p["paket"]: p for p in pakete}
    # Versionierte Kernelpakete fallen aus dem Archiv, sobald ein neuerer da
    # ist (DEV: linux-image-6.12.73+deb13-amd64). Sie sind Debian, und fuer
    # den Kernel ist ohnehin der LAUFENDE massgeblich (debian_bewerten).
    namen = sorted(n for n in nach_name if not _KERNEL_VERSIONIERT.match(n))
    pol = cve_apt.apt_policy([_apt_name(nach_name[n], native) for n in namen])
    fremd = set()
    for n in namen:
        info = pol.get(_apt_name(nach_name[n], native))
        if info and fremde_herkunft(info, rel):
            fremd.add(n)
    if not fremd:
        return []
    behalten = []
    for b in befunde:
        rest = [n for n in b["pakete"] if n not in fremd]
        if rest or not b["pakete"]:
            b["pakete"] = rest
            behalten.append(b)
    befunde[:] = behalten
    return sorted(fremd)


def debian_kandidaten(befunde: list[dict], pakete: list[dict]) -> None:
    """Klasse ``fix`` -> behebbar / nicht_im_index / zurueckgehalten (am Paketindex)."""
    native = cve_apt._arch()
    nach_name = {p["paket"]: p for p in pakete}
    metas = [p for p in pakete if _META_KERNEL.match(p["paket"])]
    fragen: set[str] = set()
    for b in befunde:
        if b["klasse"] != "fix":
            continue
        if b["kernel"]:
            fragen.update(_apt_name(p, native) for p in metas)
        else:
            fragen.update(_apt_name(nach_name[n], native) for n in b["pakete"] if n in nach_name)
    pol = cve_apt.apt_policy(sorted(fragen))
    paare = sorted({(n, i["kandidat"]) for n, i in pol.items()
                    if i.get("kandidat") and ":" not in n})
    qv = cve_apt.quell_versionen(paare)
    for b in befunde:
        if b["klasse"] != "fix":
            continue
        if b["kernel"]:
            ziel = [p for p in metas]
            ok = bool(ziel) and all(
                (pol.get(_apt_name(p, native)) or {}).get("kandidat")
                and cve_apt.vergleiche(pol[_apt_name(p, native)]["kandidat"], b["fix"]) >= 0
                for p in ziel if p["paket"].startswith("linux-image-"))
            b["beheben_mit"] = [_apt_name(p, native) for p in ziel]
        else:
            ziel = [nach_name[n] for n in b["pakete"] if n in nach_name]
            ok = bool(ziel)
            for p in ziel:
                k = (pol.get(_apt_name(p, native)) or {}).get("kandidat") or ""
                kq = qv.get((p["paket"], k), k)
                if not k or cve_apt.vergleiche(kq, b["fix"]) < 0:
                    ok = False
            b["beheben_mit"] = [_apt_name(p, native) for p in ziel]
        b["aus_sicherheitsquelle"] = bool(b["beheben_mit"]) and all(
            (pol.get(n) or {}).get("sicherheit") for n in b["beheben_mit"])
        b["kandidat"] = ", ".join(sorted({(pol.get(n) or {}).get("kandidat") or "–"
                                          for n in b["beheben_mit"]}))
        if any(nach_name.get(n.split(":")[0], {}).get("status") == "hi" for n in b["beheben_mit"]):
            b["klasse"] = "zurueckgehalten"
        else:
            b["klasse"] = "behebbar" if ok else "nicht_im_index"


def _debian_lauf() -> dict:
    """Der Debian-Teil – laeuft im EIGENEN Prozess (Speicher, siehe Kopf)."""
    t0 = time.time()
    rel = release()
    info = {"geprueft": False, "grund": "", "release": rel, "pakete": 0, "quellen": 0,
            "tracker_stand": "", "tracker_hinweis": "", "index_ts": cve_apt.index_alter(),
            "kernel": laufender_kernel(), "neustart_noetig": cve_apt.neustart_noetig()}
    if not rel:
        info["grund"] = "Kein Debian-System erkannt (/etc/os-release ohne VERSION_CODENAME)"
        return {"info": info, "befunde": []}
    pakete = debian_pakete()
    info["pakete"] = len(pakete)
    if not pakete:
        info["grund"] = "dpkg-query hat keine Pakete geliefert"
        return {"info": info, "befunde": []}
    tr = tracker_holen()
    info["tracker_stand"], info["tracker_hinweis"] = tr["stand"], tr["hinweis"]
    if not tr["ok"]:
        info["grund"] = tr["hinweis"]
        return {"info": info, "befunde": []}
    quellen = {p["quelle"] for p in pakete}
    info["quellen"] = len(quellen)
    auszug = tracker_auszug(quellen, rel)
    befunde = debian_bewerten(pakete, auszug, rel, info["kernel"])
    # Fremde Herkunft VOR der Kandidatensuche abziehen – und nennen: ein Paket,
    # das nicht geprueft werden konnte, darf nicht wie "ohne Luecken" aussehen.
    info["fremd"] = herkunft_pruefen(befunde, pakete, rel)
    debian_kandidaten(befunde, pakete)
    info["geprueft"] = True
    info["dauer_s"] = round(time.time() - t0, 1)
    return {"info": info, "befunde": befunde}


def _debian_im_prozess() -> dict:
    r = subprocess.run([sys.executable, "-m", "backend.cve_pruefung", "--debian"],
                       capture_output=True, text=True, timeout=900, cwd=str(WURZEL),
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "").strip()[-400:] or f"Exit {r.returncode}")
    return json.loads(r.stdout)


# ── Python und npm (OSV) ─────────────────────────────────────────────────────

def python_pruefen() -> dict:
    try:
        from backend import abhaengigkeiten as abh
        inst = abh.installiert()
        funde = abh.schwachstellen(inst)
        lock = abh.lock_modus()
    except Exception as e:  # noqa: BLE001
        return {"info": {"geprueft": False, "grund": f"{type(e).__name__}: {e}"}, "befunde": []}
    # OSV fuehrt dieselbe Luecke oft doppelt (GHSA- und PYSEC-Eintrag zur selben
    # CVE) – ungebuendelt zaehlte die Anzeige jede solche Luecke doppelt und
    # vergab dieselbe ID zweimal. Gilt ein Eintrag als bewertet, gilt es die Luecke.
    je: dict[tuple, dict] = {}
    for f in funde:
        cves = [a for a in f.get("aliase") or [] if a.startswith("CVE-")]
        k = (f["paket"], f["version"], cves[0] if cves else f["id"])
        if k in je:
            _vereinen(je[k], f, "behoben_in")
            je[k]["ausgenommen"] = bool(je[k].get("ausgenommen") or f.get("ausgenommen"))
        else:
            je[k] = dict(f, aliase=sorted(f.get("aliase") or []))
    befunde = []
    for (_p, _v, cve), f in je.items():
        befunde.append({
            "bereich": "python", "quelle": f["paket"], "pakete": [f["paket"]],
            "cve": cve, "aliase": f["aliase"],
            "version": f["version"], "fix": f.get("behoben_in") or "", "einstufung": "",
            "klasse": "ausgenommen" if f.get("ausgenommen")
                      else (("lock" if lock else "behebbar") if f.get("behoben_in") else "offen"),
            "text": "", "kernel": False})
    return {"info": {"geprueft": True, "grund": "", "lock_modus": lock,
                     "stand": python_stand(inst)}, "befunde": befunde}


def python_stand(inst: dict[str, str]) -> str:
    """Fingerabdruck der installierten Python-Pakete (Name + Version).

    Steht im Ergebnis, damit ``nach_paketwechsel`` erkennt, dass seit der
    Pruefung Pakete gewechselt haben – ueber DIESELBE Quelle
    (``abhaengigkeiten.installiert``) erzeugt wie verglichen."""
    roh = "\n".join(f"{n}=={v}" for n, v in sorted(inst.items()))
    return hashlib.sha256(roh.encode("utf-8")).hexdigest()[:16]


def _vereinen(ziel: dict, f: dict, fix_feld: str) -> None:
    """Zweiten OSV-Eintrag derselben Luecke einarbeiten: Aliase vereinen, die
    hoehere behebende Version gilt (erst sie behebt beide Eintraege)."""
    ziel["aliase"] = sorted(set(ziel.get("aliase") or []) | set(f.get("aliase") or []))
    a, b = ziel.get(fix_feld) or "", f.get(fix_feld) or ""
    if b and (not a or cve_apt.vergleiche(b, a) > 0):
        ziel[fix_feld] = b


def _npm_fix(vuln: dict, name: str) -> str:
    for aff in vuln.get("affected") or []:
        if (aff.get("package") or {}).get("name") != name:
            continue
        for rg in aff.get("ranges") or []:
            for ev in rg.get("events") or []:
                if ev.get("fixed"):
                    return str(ev["fixed"])
    return ""


def npm_pruefen() -> dict:
    lock = BRIDGE / "package-lock.json"
    if not (BRIDGE / "node_modules").is_dir():
        # Ohne Bridge gibt es nichts zu pruefen – das ist keine Luecke in der
        # Pruefung, sondern ein fehlender Bereich. pruefen() laesst ihn weg,
        # statt ihn als "nicht geprueft" anzuzeigen (ohne Informationswert).
        return {"info": {"geprueft": False, "entfaellt": True,
                         "grund": "WhatsApp-Bridge nicht installiert"}, "befunde": []}
    try:
        daten = json.loads(lock.read_text(encoding="utf-8"))
        pakete = []
        for pfad, e in (daten.get("packages") or {}).items():
            if not pfad.startswith("node_modules/") or not e.get("version"):
                continue
            pakete.append((pfad.rsplit("node_modules/", 1)[1], e["version"]))
        pakete = sorted(set(pakete))
        je: dict[tuple, dict] = {}  # dieselbe Doppelung wie bei Python
        for i in range(0, len(pakete), 500):
            stueck = pakete[i:i + 500]
            anf = urllib.request.Request(OSV_BATCH, data=json.dumps({"queries": [
                {"package": {"name": n, "ecosystem": "npm"}, "version": v} for n, v in stueck]}).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(anf, timeout=60) as a:  # nosec B310
                antw = json.loads(a.read() or b"{}")
            for (n, v), res in zip(stueck, antw.get("results") or []):
                for x in res.get("vulns") or []:
                    try:
                        with urllib.request.urlopen(OSV_VULN + x["id"], timeout=30) as a:  # nosec B310
                            vuln = json.loads(a.read() or b"{}")
                    except Exception:  # noqa: BLE001
                        vuln = {}
                    aliase = sorted(set(vuln.get("aliases") or []) | {x["id"]})
                    cves = [a for a in aliase if a.startswith("CVE-")]
                    fix = _npm_fix(vuln, n)
                    neu = {"bereich": "npm", "quelle": n, "pakete": [n],
                           "cve": cves[0] if cves else x["id"], "aliase": aliase,
                           "version": v, "fix": fix, "einstufung": "",
                           "text": (vuln.get("summary") or "")[:240], "kernel": False}
                    k = (n, v, neu["cve"])
                    if k in je:
                        _vereinen(je[k], neu, "fix")
                    else:
                        je[k] = neu
        befunde = [dict(b, klasse="behebbar" if b["fix"] else "offen") for b in je.values()]
        return {"info": {"geprueft": True, "grund": "", "pakete": len(pakete)}, "befunde": befunde}
    except Exception as e:  # noqa: BLE001
        return {"info": {"geprueft": False, "grund": f"{type(e).__name__}: {e}"}, "befunde": []}


# ── Node.js-Laufzeit ─────────────────────────────────────────────────────────
#
# ⚠ AUF DEV UND ECHT GEMESSEN (2026-10-29): ``nodejs 24.22.2-1nodesource1``
# stammt aus NodeSource. Der Debian-Tracker fuehrt unter dem Quellpaket
# ``nodejs`` nur Debians nodejs 20 – seine Befunde gelten fuer dieses Paket
# nicht und werden entfernt (herkunft_pruefen). Ohne diesen Bereich war die
# Laufzeit, auf der die WhatsApp-Bridge laeuft, also GAR NICHT geprueft und
# nur als "nicht ueber Debian pruefbar" genannt.
#
# Stammt nodejs aus Debian, prueft es der Tracker – dann entfaellt der Bereich.

_NODE_V = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")
_NODE_VERGLEICH = re.compile(r"^(<=|>=|<|>|=|\^|~)?\s*v?(\d+|[xX*])(?:\.(\d+|[xX*]))?(?:\.(\d+|[xX*]))?$")


def _node_v(text: str) -> tuple[int, int, int] | None:
    """``24.22.2`` / ``v24.22.2`` / ``24.22.2-1nodesource1`` -> (24, 22, 2)."""
    m = _NODE_V.match(re.sub(r"^\d+:", "", str(text or "").strip()))
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _node_vergleich(teil: str, v: tuple) -> bool | None:
    """Ein Vergleich (``^24.22.1``, ``22.x``, ``>= 4.8.2``, ``<= 4``) gegen v.

    ``None`` = nicht deutbar. Teilversionen vergleichen nur die genannten
    Stellen – ``<= 4`` heisst "Hauptversion hoechstens 4" (semver: < 5.0.0).
    """
    m = _NODE_VERGLEICH.match(teil.strip())
    if not m:
        return None
    op = m.group(1) or "="
    stellen = []
    for g in m.group(2, 3, 4):
        if g is None or not g.isdigit():
            break
        stellen.append(int(g))
    k = len(stellen)
    p = tuple(stellen)
    if op == "=":
        return v[:k] == p
    if not k:
        return None if op != "=" else True
    if op in ("^", "~"):
        unten = p + (0,) * (3 - k)
        if v < unten:
            return False
        if op == "~":
            # ~1 = 1.x, ~1.2 und ~1.2.3 = 1.2.x
            return v[:min(k, 2)] == p[:min(k, 2)]
        # Caret: fest bleibt die erste genannte Stelle ungleich 0
        # (^1.2.3 = 1.x, ^0.2.3 = 0.2.x, ^0.0.3 = genau 0.0.3).
        if p[0] or k == 1:
            return v[0] == p[0]
        if p[1] or k == 2:
            return v[:2] == p[:2]
        return v == unten
    return {"<": v[:k] < p, "<=": v[:k] <= p, ">": v[:k] > p, ">=": v[:k] >= p}[op]


def node_im_bereich(ausdruck: str, v: tuple) -> bool | None:
    """semver-Bereich der Security WG (``22.x || ^24.22.1``, ``>=4.0.0 <4.8.2``).

    ODER ueber ``||``, UND ueber Leerraum innerhalb einer Alternative.
    ``None`` = nicht deutbar – nie zu "nicht betroffen" umgedeutet.
    """
    alternativen = [a.strip() for a in str(ausdruck or "").split("||") if a.strip()]
    if not alternativen:
        return None
    # ALLE Alternativen deuten, bevor eine entscheidet: ein kaputter Teil
    # hinter einem Treffer heisst, dass der Eintrag nicht verstanden ist –
    # er gehoert dann als "nicht auswertbar" genannt (Waechter-Fund).
    treffer = False
    for alt in alternativen:
        # ">= 4.8.2" ist EIN Vergleich: Operator und Version zusammenziehen.
        teile = re.findall(r"(?:<=|>=|<|>|=|\^|~)?\s*v?[\dxX*]+(?:\.[\dxX*]+){0,2}", alt)
        if not teile or re.sub(r"\s+", "", "".join(teile)) != re.sub(r"\s+", "", alt):
            return None
        werte = [_node_vergleich(t, v) for t in teile]
        if None in werte:
            return None
        treffer = treffer or all(werte)
    return treffer


def _node_untergrenzen(ausdruck: str) -> list[tuple[int, int, int]]:
    """Untere Grenzen der behebenden Alternativen (``^24.22.1`` -> (24, 22, 1))."""
    erg = []
    for alt in str(ausdruck or "").split("||"):
        m = re.match(r"^\s*(?:\^|~|>=|=)?\s*v?(\d+)\.(\d+)\.(\d+)", alt)
        if m:
            erg.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
    return sorted(set(erg))


def _v_text(v: tuple) -> str:
    return ".".join(str(x) for x in v)


def node_bewerten(version: str, db: dict, release_plan: dict, heute: str) -> dict:
    """Befunde fuer EINE Node.js-Version – rein, ohne Netz und Paketindex.

    Rueckgabe: {befunde, undeutbar, ende, hinweis}. Ein Befund traegt
    ``fix`` (behebende Version DERSELBEN Hauptversion) oder ``fix_andere``
    (behoben nur in anderen Hauptversionen). Die Klasse setzt node_pruefen.

    ⚠ DAS ENDE DER UNTERSTUETZUNG IST EIN EIGENER BEFUND, nicht nur ein
    Hinweis: die Security WG nennt in ``vulnerable`` nur die Hauptversionen,
    die sie noch betreut (``22.x || 24.x || 26.x``). Eine Version nach ihrem
    Ende bekommt fuer neue Luecken also KEINEN Eintrag mehr – ohne diesen
    Befund saehe sie mit jedem Monat sauberer aus.
    """
    v = _node_v(version)
    if v is None:
        raise ValueError(f"Node.js-Version nicht lesbar: {version!r}")
    je: dict[str, dict] = {}
    undeutbar = []
    for nr in sorted(db, key=lambda k: (len(str(k)), str(k))):
        e = db[nr] if isinstance(db[nr], dict) else {}
        cves = sorted(c for c in e.get("cve") or [] if isinstance(c, str) and c)
        kennung = cves[0] if cves else f"nodejs-core-{nr}"
        betroffen = node_im_bereich(e.get("vulnerable") or "", v)
        behoben = node_im_bereich(e["patched"], v) if e.get("patched") else False
        if betroffen is None or behoben is None:
            undeutbar.append(kennung)
            continue
        if not betroffen or behoben:
            continue
        grenzen = _node_untergrenzen(e.get("patched") or "")
        gleich = [g for g in grenzen if g[0] == v[0] and g > v]
        andere = [g for g in grenzen if g[0] > v[0]]
        sev = str(e.get("severity") or "").lower()
        ref = str(e.get("ref") or "")
        neu = {"bereich": "node", "quelle": "nodejs", "pakete": [], "cve": kennung,
               "aliase": cves, "version": _v_text(v),
               "fix": _v_text(min(gleich)) if gleich else "",
               "fix_andere": ", ".join(_v_text(g) for g in andere),
               "einstufung": sev if sev in NODE_EINSTUFUNGEN else "",
               "text": str(e.get("description") or e.get("overview") or "")[:240],
               "ref": ref if ref.startswith("https://") else "", "kernel": False}
        if kennung in je:
            _vereinen(je[kennung], neu, "fix")
        else:
            je[kennung] = neu
    befunde = list(je.values())
    plan_eintrag = release_plan.get(f"v{v[0]}") if isinstance(release_plan, dict) else None
    ende = str((plan_eintrag or {}).get("end") or "")
    hinweis = ""
    if not release_plan:
        hinweis = "Release-Plan von Node.js nicht verfügbar – Ende der Unterstützung nicht geprüft"
    elif not ende:
        hinweis = (f"Node.js {v[0]} steht nicht im Release-Plan – ob diese Hauptversion "
                   "noch Sicherheitsupdates erhält, ist unbekannt")
    elif ende < heute:
        nachfolger = sorted(int(k[1:]) for k, w in release_plan.items()
                            if re.fullmatch(r"v\d+", k) and isinstance(w, dict)
                            and str(w.get("end") or "") >= heute
                            and "" < str(w.get("lts") or "") <= heute)
        befunde.append({
            "bereich": "node", "quelle": "nodejs", "pakete": [], "cve": f"nodejs-{v[0]}-eol",
            "aliase": [], "version": _v_text(v), "fix": "",
            "fix_andere": ", ".join(f"{n}.x" for n in nachfolger if n > v[0]),
            "einstufung": "", "ref": "https://nodejs.org/en/about/previous-releases",
            "text": (f"Node.js {v[0]} erhält seit {ende} keine Sicherheitsupdates mehr. "
                     "Neue Lücken werden für diese Hauptversion nicht mehr veröffentlicht "
                     "und fehlen deshalb auch in dieser Prüfung."),
            "kernel": False, "eol": True})
    return {"befunde": befunde, "undeutbar": undeutbar, "ende": ende, "hinweis": hinweis}


def _node_quelle_holen(url: str, cache: Path) -> tuple[dict | None, str]:
    """JSON-Quelle holen; scheitert es, den gespeicherten Stand benutzen – laut."""
    try:
        anf = urllib.request.Request(url, headers={"User-Agent": "jarvis-cve-pruefung"})
        with urllib.request.urlopen(anf, timeout=60) as a:  # nosec B310 – feste https-Adresse
            roh = a.read(NODE_MAX_BYTES + 1)
        if len(roh) > NODE_MAX_BYTES:
            raise ValueError("Antwort ist unplausibel gross")
        daten = json.loads(roh)
        if not isinstance(daten, dict) or not daten:
            raise ValueError("Antwort ist kein gefuelltes JSON-Objekt")
        _schreiben(cache, daten)
        return daten, ""
    except Exception as e:  # noqa: BLE001
        fehler = f"{type(e).__name__}: {e}"[:200]
    alt = _lesen(cache, None)
    if isinstance(alt, dict) and alt:
        return alt, f"{url} nicht erreichbar ({fehler}) – gespeicherter Stand benutzt"
    return None, f"{url} nicht erreichbar ({fehler})"


def node_installiert(rel: str) -> dict | None:
    """Welche Node.js-Laufzeit liegt hier? ``None`` = keine.

    Zuerst das Debian-Paket ``nodejs`` (aus Debian ODER einer Fremdquelle wie
    NodeSource), sonst ein ``node`` ausserhalb der Paketverwaltung
    (``/usr/local/bin``, Tarball). ``debian`` ist ``None``, wenn apt-cache
    keine Auskunft gibt – dann wird geprueft, statt Debian zu unterstellen.
    """
    umg = {"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"}
    r = subprocess.run(["dpkg-query", "-W", "-f=${db:Status-Abbrev}\t${Version}", "--", "nodejs"],
                       capture_output=True, text=True, timeout=30, env=umg)
    st, _, ver = (r.stdout or "").partition("\t")
    st = st.strip()
    if r.returncode == 0 and len(st) >= 2 and st[1] == "i" and ver.strip():
        info = cve_apt.apt_policy(["nodejs"]).get("nodejs")
        return {"paket": "nodejs", "version": ver.strip(), "status": st,
                "kandidat": (info or {}).get("kandidat") or "",
                "debian": (not fremde_herkunft(info, rel)) if info else None}
    pfad = shutil.which("node", path="/usr/local/bin:/usr/bin:/bin")
    if not pfad:
        return None
    r = subprocess.run([pfad, "--version"], capture_output=True, text=True, timeout=30, env=umg)
    return {"paket": "", "pfad": pfad, "version": (r.stdout or "").strip(), "status": "",
            "kandidat": "", "debian": False}


def node_pruefen() -> dict:
    try:
        inst = node_installiert(release())
        if not inst:
            return {"info": {"geprueft": False, "entfaellt": True,
                             "grund": "Node.js nicht installiert"}, "befunde": []}
        if inst["debian"]:
            return {"info": {"geprueft": False, "entfaellt": True,
                             "grund": "Node.js stammt aus Debian und wird dort geprüft"},
                    "befunde": []}
        info = {"geprueft": False, "grund": "", "version": inst["version"],
                "paket": inst["paket"], "pfad": inst.get("pfad", ""), "hinweis": ""}
        if _node_v(inst["version"]) is None:
            info["grund"] = f"Node.js-Version nicht lesbar: {inst['version']!r}"[:200]
            return {"info": info, "befunde": []}
        db, h_db = _node_quelle_holen(NODE_DB_URL, NODE_DB_CACHE)
        if db is None:
            info["grund"] = "Lücken-Datenbank von Node.js " + h_db
            return {"info": info, "befunde": []}
        plan_, h_plan = _node_quelle_holen(NODE_PLAN_URL, NODE_PLAN_CACHE)
        bew = node_bewerten(inst["version"], db, plan_ or {}, dt.date.today().isoformat())
        befunde = bew["befunde"]
        kand = _node_v(inst["kandidat"])
        for b in befunde:
            if inst["paket"]:
                b["pakete"] = [inst["paket"]]
            if not b["fix"]:
                b["klasse"] = "offen"
            elif not inst["paket"]:
                # Ohne Paketverwaltung hebt hier niemand – wie bei npm gilt
                # "Update verfuegbar" als Tatsache, nicht als Zusage.
                b["klasse"] = "behebbar"
            elif inst["status"] == "hi":
                b["klasse"] = "zurueckgehalten"
            else:
                ok = kand is not None and kand >= _node_v(b["fix"])
                b["klasse"] = "behebbar" if ok else "nicht_im_index"
                b["kandidat"] = inst["kandidat"] or "–"
                if ok:
                    b["beheben_mit"] = [inst["paket"]]
                    b["aus_sicherheitsquelle"] = False
                    b["aus_fremdquelle"] = True
        hinweise = [h for h in (h_db, h_plan if plan_ else "", bew["hinweis"]) if h]
        if bew["undeutbar"]:
            hinweise.append(f"{len(bew['undeutbar'])} Einträge der Lücken-Datenbank nicht "
                            "auswertbar: " + ", ".join(bew["undeutbar"][:5]))
        info.update(geprueft=True, eintraege=len(db), unterstuetzt_bis=bew["ende"],
                    hinweis=" · ".join(hinweise))
        return {"info": info, "befunde": befunde}
    except Exception as e:  # noqa: BLE001
        return {"info": {"geprueft": False, "grund": f"{type(e).__name__}: {e}"[:300]},
                "befunde": []}


# ── Veroeffentlichungsdatum (OSV) ────────────────────────────────────────────

def _osv_datum(kennung: str) -> str | None:
    """``JJJJ-MM-TT`` aus OSV; ``""`` = OSV kennt die Kennung (noch) nicht oder
    nennt kein Datum; ``None`` = Abruf gescheitert (nicht cachen).

    Bei CVE-Kennungen zuerst ``DEBIAN-CVE-…``: auf DEV am 2026-10-29 fehlten
    517 von 2706 CVEs unter der reinen Kennung (404), ihr Debian-Eintrag trug
    das Datum – dasselbe wie die NVD (gegengeprueft an CVE-2022-47111 und
    CVE-2026-100229). Die reine Kennung bleibt Rueckfall fuer PyPI/npm.
    """
    kandidaten = ([f"DEBIAN-{kennung}"] if kennung.startswith("CVE-") else []) + [kennung]
    for k in kandidaten:
        try:
            with urllib.request.urlopen(OSV_VULN + k, timeout=20) as a:  # nosec B310
                d = json.loads(a.read() or b"{}")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            return None
        except Exception:  # noqa: BLE001
            return None
        m = _DATUM.match(str(d.get("published") or ""))
        if m:
            return m.group(0)
    return ""


def veroeffentlichung_ergaenzen(befunde: list[dict], holen=None) -> dict:
    """Setzt ``veroeffentlicht`` an jedem Befund (``""`` = unbekannt).

    Gefragt wird nur, was der Cache nicht kennt; ein gescheiterter Abruf wird
    NICHT gemerkt (sonst bliebe das Datum eine Woche lang leer). Ein harter
    Zeitdeckel haelt den Lauf begrenzt – was nicht drankam, folgt beim
    naechsten Lauf. Rueckgabe: Zahlen fuer ``bereiche``.
    """
    from concurrent.futures import ThreadPoolExecutor, wait
    holen = holen or _osv_datum
    cache = _lesen(VEROEFF, {})
    if not isinstance(cache, dict):
        cache = {}
    jetzt = time.time()
    ids = sorted({b["cve"] for b in befunde if b.get("cve")})
    offen = [k for k in ids
             if not (isinstance(cache.get(k), dict)
                     and (cache[k].get("d") or jetzt - float(cache[k].get("t") or 0) < VEROEFF_NEU_S))]
    gescheitert = 0
    if offen:
        pool = ThreadPoolExecutor(max_workers=VEROEFF_PARALLEL)
        auftraege = {pool.submit(holen, k): k for k in offen}
        fertig, _rest = wait(auftraege, timeout=VEROEFF_DECKEL_S)
        # Nicht auf Nachzuegler warten: ausstehende Auftraege verwerfen.
        pool.shutdown(wait=False, cancel_futures=True)
        for f in fertig:
            d = f.result() if not f.exception() else None
            if d is None:
                gescheitert += 1
                continue
            cache[auftraege[f]] = {"d": d, "t": jetzt}
        _schreiben(VEROEFF, cache)
    for b in befunde:
        e = cache.get(b.get("cve")) if b.get("cve") else None
        b["veroeffentlicht"] = (e.get("d") or "") if isinstance(e, dict) else ""
    return {"gefragt": len(offen), "gescheitert": gescheitert,
            "ohne_datum": sum(1 for b in befunde if not b["veroeffentlicht"])}


# ── Pruefen, Plan, Beheben ───────────────────────────────────────────────────

def schluessel(b: dict) -> str:
    return f"{b['bereich']}:{b['quelle']}:{b['cve']}:{b['klasse']}"


def pruefen() -> dict:
    t0 = time.time()
    bereiche: dict = {}
    befunde: list = []
    try:
        deb = _debian_im_prozess()
    except Exception as e:  # noqa: BLE001
        deb = {"info": {"geprueft": False, "grund": f"Debian-Pruefung gescheitert: {e}"},
               "befunde": []}
    node = node_pruefen()
    for name, teil in (("debian", deb), ("python", python_pruefen()), ("npm", npm_pruefen()),
                       ("node", node)):
        if teil["info"].get("entfaellt"):
            continue
        bereiche[name] = teil["info"]
        befunde.extend(teil["befunde"])
    # Was der Node-Bereich geprueft hat, ist nicht mehr "nicht ueber Debian
    # pruefbar" – sonst stuende nodejs dort UND haette Befunde daneben.
    deb_info = bereiche.get("debian") or {}
    np_ = node["info"].get("paket")
    if node["info"].get("geprueft") and np_ and np_ in (deb_info.get("fremd") or []):
        deb_info["fremd"] = [n for n in deb_info["fremd"] if n != np_]
        deb_info["fremd_geprueft"] = [np_]
    for b in befunde:
        b["id"] = schluessel(b)
        # npm und Node.js ohne Paketverwaltung hebt hier niemand – auch
        # "behebbar" laesst sich dort nur zur Kenntnis nehmen.
        b["quittierbar"] = (b["klasse"] in QUITTIERBAR or b["bereich"] == "npm"
                            or (b["bereich"] == "node" and not b.get("beheben_mit")))
    try:
        veroeff = veroeffentlichung_ergaenzen(befunde)
    except Exception as e:  # noqa: BLE001 – ein fehlendes Datum darf die Pruefung nicht kippen
        veroeff = {"fehler": f"{type(e).__name__}: {e}"}
        for b in befunde:
            b.setdefault("veroeffentlicht", "")
    zaehler = {k: 0 for k in KLASSEN}
    for b in befunde:
        zaehler[b["klasse"]] = zaehler.get(b["klasse"], 0) + 1
    jetzt = time.time()
    return {"version": 1, "ts": jetzt,
            "erzeugt_am": dt.datetime.fromtimestamp(jetzt).astimezone().isoformat(timespec="seconds"),
            "host": socket.gethostname(), "dauer_s": round(jetzt - t0, 1),
            "bereiche": bereiche, "befunde": befunde, "zaehler": zaehler, "behebung": None,
            "veroeffentlichung": veroeff}


def einstellungen() -> dict:
    d = _lesen(EINSTELLUNGEN, {})
    erg = dict(VORGABEN)
    if d.get("schwelle") in SCHWELLEN:
        erg["schwelle"] = d["schwelle"]
    if isinstance(d.get("regulaere_quelle"), bool):
        erg["regulaere_quelle"] = d["regulaere_quelle"]
    return erg


def einstellungen_setzen(neu: dict) -> dict:
    erg = einstellungen()
    if "schwelle" in neu:
        if neu["schwelle"] not in SCHWELLEN:
            raise ValueError("schwelle muss einer von " + ", ".join(SCHWELLEN) + " sein")
        erg["schwelle"] = neu["schwelle"]
    if "regulaere_quelle" in neu:
        if not isinstance(neu["regulaere_quelle"], bool):
            raise ValueError("regulaere_quelle muss true/false sein")
        erg["regulaere_quelle"] = neu["regulaere_quelle"]
    _schreiben(EINSTELLUNGEN, erg)
    return erg


def erreicht_schwelle(einstufung: str, schwelle: str) -> bool:
    """Nicht eingestuft (``""``) erreicht JEDE Schwelle – siehe Kopf."""
    if einstufung not in RANG:
        return True
    return RANG[einstufung] >= SCHWELLE_RANG.get(schwelle, 1)


def plan(erg: dict, einst: dict, schwelle: str | None = None) -> dict:
    """Was ein Behebungslauf mit diesen Einstellungen anfassen wuerde."""
    schwelle = schwelle if schwelle in SCHWELLEN else einst["schwelle"]
    pakete: set[str] = set()
    index = False
    python = False
    nur_regulaer = 0
    node_von_hand = 0
    for b in erg.get("befunde") or []:
        if b["bereich"] == "debian" and erreicht_schwelle(b.get("einstufung", ""), schwelle):
            if b["klasse"] == "behebbar":
                if b.get("aus_sicherheitsquelle") or einst["regulaere_quelle"]:
                    pakete.update(b.get("beheben_mit") or [])
                else:
                    nur_regulaer += 1
            elif b["klasse"] == "nicht_im_index":
                index = True
        elif b["bereich"] == "python" and b["klasse"] == "behebbar":
            # Im Lock-Modus gibt es kein "behebbar" fuer Python (Klasse "lock",
            # python_pruefen) – die Entscheidung steht an EINER Stelle.
            python = True
        elif b["bereich"] == "node" and b["klasse"] == "behebbar":
            # Bewusst NICHT automatisch: der Schalter "regulaere Quelle" meint
            # Debian, eine Fremdquelle wie NodeSource haengt nicht daran. Das
            # Einzel-Update (Knopf an der nodejs-Zeile) hebt es ausdruecklich.
            node_von_hand += 1
    return {"schwelle": schwelle, "debian": sorted(pakete), "index": index,
            "python": python, "nur_regulaere_quelle": nur_regulaer,
            "node_von_hand": node_von_hand}


def _broker_beheben(pakete: list[str], nur_sicherheit: bool, index: bool, user: str) -> dict:
    """Ruft die Broker-Op. ``timeout`` im Op-Argument (nicht der Anfrage-Deckel
    von 900 s) bestimmt die Wartezeit, weil ``cve_beheben`` in ``LANGE_OPS``
    steht – apt-get update + install duerfen zusammen bis zu 2700 s brauchen.
    Der Aufruf-``timeout`` (3000) ist trotzdem noetig: der Client setzt daraus
    den SOCKET-Deckel, und ohne Ausgabezeilen liefe der nach 960 s ab."""
    from backend import broker_client
    res = broker_client.call_sync("cve_beheben",
                                  {"pakete": pakete, "nur_sicherheit": nur_sicherheit,
                                   "index": index, "timeout": 2900},
                                  user=user or "cve-pruefung", timeout=3000)
    if not res.get("ok"):
        return {"ok": False, "fehler": str(res.get("error") or res.get("stderr") or "Broker-Fehler")}
    return res.get("result") or {"ok": False, "fehler": "Broker ohne Ergebnis"}


def _python_beheben() -> dict:
    from backend import abhaengigkeiten as abh
    vorher = abh.zustand().get("geaendert") or []
    e = abh.abgleichen(installieren=True)
    neu = e.get("geaendert") or []
    erg = {"ok": bool(e.get("ok")), "geaendert": neu, "fehler": e.get("fehler") or "",
           "zurueckgesetzt": e.get("zurueckgesetzt") or [], "neustart": False}
    # Dieselbe Schranke wie der taegliche Lauf (main.startup_abhaengigkeiten):
    # nur bei einer ANDEREN Aenderung neu starten, sonst Neustart-Schleife.
    if neu and neu != vorher and not erg["zurueckgesetzt"]:
        erg["neustart"] = True
    return erg


def lauf(beheben: bool = False, schwelle: str | None = None, ausloeser: str = "manuell",
         von: str = "") -> dict:
    """Ein vollstaendiger Lauf (blockierend – aus einem Thread rufen)."""
    if not _sperre.acquire(blocking=False):
        return {"ok": False, "fehler": "Es läuft bereits eine Prüfung."}
    _status.update(laeuft=True, seit=time.time(), schritt="pruefen", ausloeser=ausloeser)
    python_neustart = False
    try:
        vorher = {b["id"] for b in (zustand_ergebnis() or {}).get("befunde") or []
                  if b["klasse"] == "behebbar"}
        erg = pruefen()
        behebung = None
        if beheben:
            einst = einstellungen()
            p = plan(erg, einst, schwelle)
            behebung = {"plan": p, "debian": [], "python": None}
            if p["debian"] or p["index"]:
                _status["schritt"] = "beheben"
                res = _broker_beheben(p["debian"], not einst["regulaere_quelle"], p["index"], von)
                behebung["debian"].append(res)
                if p["index"] and res.get("ok"):
                    # Der frische Index kann weitere Luecken behebbar machen.
                    _status["schritt"] = "pruefen"
                    zwischen = pruefen()
                    p2 = plan(zwischen, einst, schwelle)
                    rest = [n for n in p2["debian"] if n not in p["debian"]]
                    if rest:
                        _status["schritt"] = "beheben"
                        behebung["debian"].append(
                            _broker_beheben(rest, not einst["regulaere_quelle"], False, von))
            if p["python"]:
                _status["schritt"] = "beheben"
                behebung["python"] = _python_beheben()
                python_neustart = behebung["python"]["neustart"]
            _status["schritt"] = "pruefen"
            erg = pruefen()
            erg["behebung"] = behebung
        erg.update(ok=True, ausloeser=ausloeser, von=von, beheben=bool(beheben))
        _speichern(erg)
        _melden(erg, vorher)
    except Exception as e:  # noqa: BLE001
        erg = {"ok": False, "fehler": f"{type(e).__name__}: {e}"}
    finally:
        _status.update(laeuft=False, schritt="")
        _sperre.release()
    if python_neustart:
        from backend.update_manager import restart_service_delayed
        restart_service_delayed(delay_sec=5.0,
                                context="Python-Pakete nach CVE-Prüfung gehoben")
    return erg


def einzeln_pakete(erg: dict | None, quelle: str) -> list[str]:
    """Binaerpakete, die ein Update EINES Quellpakets anfasst (Debian, Node.js).

    Je Quellpaket, nicht je Binaerpaket: ``libbrotli1`` ohne ``brotli`` zu
    heben, liesse Teile desselben Pakets auf verschiedenen Versionen stehen.
    Nur was das letzte Ergebnis als behebbar fuehrt – der Knopf kann nichts
    anstossen, was die Pruefung nicht gesehen hat.
    """
    return sorted({n for b in (erg or {}).get("befunde") or []
                   if b["bereich"] in ("debian", "node") and b["quelle"] == quelle
                   and b["klasse"] == "behebbar" for n in b.get("beheben_mit") or []})


def lauf_einzeln(quelle: str, von: str = "") -> dict:
    """Ein Quellpaket von Hand aktualisieren, danach neu pruefen.

    Bewusst AUCH aus der regulaeren Quelle (Vorgabe 2026-10-29): der Klick ist
    eine einzelne, ausdrueckliche Entscheidung, die Rueckfrage nennt die
    Quelle. Der Schalter in den Einstellungen gilt fuer die Automatik und den
    Sammelknopf.
    """
    if not _sperre.acquire(blocking=False):
        return {"ok": False, "fehler": "Es läuft bereits eine Prüfung."}
    _status.update(laeuft=True, seit=time.time(), schritt="beheben", ausloeser="einzeln")
    try:
        alt = zustand_ergebnis()
        vorher = {b["id"] for b in (alt or {}).get("befunde") or [] if b["klasse"] == "behebbar"}
        pakete = einzeln_pakete(alt, quelle)
        if not pakete:
            return {"ok": False, "fehler": "Für dieses Paket liegt kein Update vor – bitte neu prüfen."}
        res = _broker_beheben(pakete, False, False, von)
        _status["schritt"] = "pruefen"
        erg = pruefen()
        erg["behebung"] = {"plan": {"einzeln": quelle, "debian": pakete}, "debian": [res],
                           "python": None}
        erg.update(ok=True, ausloeser="einzeln", von=von, beheben=True)
        _speichern(erg)
        _melden(erg, vorher)
        return erg
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "fehler": f"{type(e).__name__}: {e}"}
    finally:
        _status.update(laeuft=False, schritt="")
        _sperre.release()


def _speichern(erg: dict) -> None:
    _schreiben(ERGEBNIS, erg)
    # Quittungen fuer Befunde, die es nicht mehr gibt, abraeumen – sonst waechst
    # die Datei endlos, und eine CVE, die spaeter in anderer Klasse
    # wiederkommt, bleibt ohnehin sichtbar (die Klasse steht im Schluessel).
    q = quittiert()
    ids = {b["id"] for b in erg.get("befunde") or []}
    rest = {k: v for k, v in q.items() if k in ids}
    if rest != q:
        _schreiben(QUITTIERT, rest)


def _melden(erg: dict, vorher_behebbar: set) -> None:
    """Eintrag im Sicherheitsprotokoll – nur, wenn etwas Neues oder Behobenes da ist."""
    neu = sorted(b["id"] for b in erg.get("befunde") or []
                 if b["klasse"] == "behebbar" and b["id"] not in vorher_behebbar)
    beh = erg.get("behebung") or {}
    installiert = [f"{i['paket']} {i['auf']}" for r in beh.get("debian") or []
                   for i in (r.get("installiert") or [])]
    py = (beh.get("python") or {}).get("geaendert") or []
    if not (neu or installiert or py):
        return
    try:
        from backend import sicherheits_log
        sicherheits_log.ereignis(
            "cve_pruefung", benutzer=str(erg.get("von") or ""),
            ergebnis="behoben" if (installiert or py) else "gefunden",
            ausloeser=erg.get("ausloeser"), neu_behebbar=neu[:40], installiert=installiert[:60],
            python=py[:40], zaehler=erg.get("zaehler"))
    except Exception:  # noqa: BLE001
        pass


# ── Abfragen fuer API und Badge ─────────────────────────────────────────────

def zustand_ergebnis() -> dict | None:
    # Schluessel aus mtime (ns), Groesse UND Inode: zwei Schreibvorgaenge im
    # selben Zeittakt haben dieselbe mtime – nur daran gemerkt, lieferte der
    # Cache den alten Stand (vom Waechter gefunden). ``os.replace`` gibt jeder
    # neuen Fassung eine neue Inode.
    try:
        st = ERGEBNIS.stat()
    except OSError:
        return None
    # Der Stempel der site-packages gehoert in den Schluessel: ein Paketwechsel
    # benennt dessen dist-info-Verzeichnis um und aendert damit die mtime des
    # Elternverzeichnisses – ohne ihn bliebe die Angleichung bis zur naechsten
    # Pruefung beim alten Stand stehen.
    m = (st.st_mtime_ns, st.st_size, st.st_ino, _site_stempel())
    if _cache["mtime"] != m:
        erg = kernel_nachfuehren(_lesen(ERGEBNIS, None), laufender_kernel())
        _cache.update(mtime=m, wert=python_nachfuehren(erg, python_installiert()))
    return _cache["wert"]


def _site_stempel() -> tuple:
    stempel = []
    for p in sys.path:
        if p.endswith(("site-packages", "dist-packages")):
            try:
                stempel.append((p, os.stat(p).st_mtime_ns))
            except OSError:
                pass
    return tuple(stempel)


def _py_norm(name: str) -> str:
    """Wie ``abhaengigkeiten._norm`` – mit diesem Namen stehen die Befunde da."""
    return re.sub(r"[-_.]+", "-", name).lower()


def python_installiert() -> dict[str, str] | None:
    """Normierter Name -> Version der LAUFENDEN Umgebung, ohne pip-Aufruf.

    ``None`` heisst "nicht ermittelbar" – dann wird nichts angeglichen."""
    try:
        from importlib import metadata
        dists = list(metadata.distributions())
    except Exception:  # noqa: BLE001
        return None
    inst = {}
    for d in dists:
        try:
            name = d.metadata.get("Name")
            if name:
                # Erster Treffer gewinnt – in sys.path-Reihenfolge ist das die
                # Fassung, die ein Import tatsaechlich laedt.
                inst.setdefault(_py_norm(name), d.version)
        except Exception:  # noqa: BLE001 – ein kaputtes dist-info kippt nicht alle
            continue
    return inst or None


def _py_behoben(installiert: str, fix: str) -> bool:
    if not fix:
        return False
    try:
        from packaging.version import Version
        return Version(installiert) >= Version(fix)
    except Exception:  # noqa: BLE001 – unlesbare Fassung: nichts behaupten
        return False


def python_nachfuehren(erg: dict | None, inst: dict[str, str] | None) -> dict | None:
    """Gespeichertes Ergebnis an die JETZT installierten Python-Pakete angleichen.

    ⚠ AUF ECHT GEMESSEN (2026-10-29): Pruefung um 13:16:11, Lock-Install um
    13:17:31–48 (setuptools 74.1.3 -> 81.0.0, sentence-transformers 3.4.1 ->
    5.7.0, torch, transformers) – das Paket-Fenster zeigte danach weiter vier
    Pakete mit Luecken, die alle behoben waren. Dieselbe Klasse wie
    ``kernel_nachfuehren``: Befunde, deren Behebung die installierte Fassung
    schon traegt, fallen beim LESEN weg; die Datei bleibt unberuehrt.

    Bewusst NUR bei nachgewiesener Behebung (installiert >= fix). Ein Befund
    ohne Behebung oder ein nicht mehr gefundenes Paket bleibt stehen, bis neu
    geprueft ist – ob die neue Fassung betroffen ist, weiss hier niemand (den
    Neulauf stoesst ``nach_paketwechsel`` an).
    """
    if not erg or not inst:
        return erg
    rest, weg = [], set()
    for b in erg.get("befunde") or []:
        if b.get("bereich") == "python":
            v = inst.get(_py_norm(b.get("quelle") or ""))
            if v and v != b.get("version") and _py_behoben(v, b.get("fix") or ""):
                weg.add(f"{b.get('quelle')} {b.get('version')} → {v}")
                continue
        rest.append(b)
    if not weg:
        return erg
    zaehler = {k: 0 for k in KLASSEN}
    for b in rest:
        zaehler[b["klasse"]] = zaehler.get(b["klasse"], 0) + 1
    py = dict((erg.get("bereiche") or {}).get("python") or {}, nachgefuehrt=sorted(weg))
    return dict(erg, befunde=rest, zaehler=zaehler,
                bereiche=dict(erg.get("bereiche") or {}, python=py))


def nach_paketwechsel() -> bool:
    """Neu pruefen (ohne Behebung), wenn die Python-Pakete seit der letzten
    Pruefung gewechselt haben. Blockierend – aus einem Thread rufen.

    Aufgerufen nach dem Paket-Abgleich (main.startup_abhaengigkeiten): der
    Lock-Install hebt Pakete und startet neu, aber niemand prueft danach – die
    Angleichung beim Lesen deckt nur nachgewiesen Behobenes ab, nicht neue
    oder weggefallene Funde. Nie geprueft -> keine Pruefung aus eigenem
    Antrieb (die Funktion hat dann niemand benutzt). Ein Ergebnis OHNE Stand
    (vor dieser Aenderung) gilt als gewechselt: unbekannt ist nicht gleich.
    """
    erg = _lesen(ERGEBNIS, None)
    if not erg or _status["laeuft"]:
        return False
    from backend import abhaengigkeiten as abh
    jetzt = python_stand(abh.installiert())
    if ((erg.get("bereiche") or {}).get("python") or {}).get("stand") == jetzt:
        return False
    lauf(beheben=False, ausloeser="paketwechsel")
    return True


def kernel_nachfuehren(erg: dict | None, kernel: str) -> dict | None:
    """Gespeichertes Ergebnis an den JETZT laufenden Kernel angleichen.

    ⚠ AUF ECHT GEMESSEN (2026-10-29): Pruefung um 09:41 unter 6.12.111-1,
    Neustart um 10:51 auf 6.12.113-1 – die Anzeige stand weiter auf
    "Neustart noetig: 672", weil nach einem Neustart niemand neu prueft und
    die Klasse im gespeicherten Ergebnis eingefroren ist. Der Neustart ist
    aber genau die Abhilfe dieser Klasse. Kernel-Befunde, deren Behebung der
    laufende Kernel schon traegt, fallen deshalb beim LESEN weg; die Datei
    bleibt unberuehrt (der naechste Lauf schreibt ohnehin neu).
    """
    if not erg or not kernel:
        return erg
    deb = (erg.get("bereiche") or {}).get("debian") or {}
    if not deb.get("kernel") or deb["kernel"] == kernel:
        return erg
    befunde = [b for b in erg.get("befunde") or []
               if not (b.get("kernel") and b.get("fix")
                       and cve_apt.vergleiche(kernel, b["fix"]) >= 0)]
    zaehler = {k: 0 for k in KLASSEN}
    for b in befunde:
        zaehler[b["klasse"]] = zaehler.get(b["klasse"], 0) + 1
    deb = dict(deb, kernel=kernel, kernel_bei_pruefung=deb["kernel"],
               neustart_noetig=cve_apt.neustart_noetig())
    return dict(erg, befunde=befunde, zaehler=zaehler,
                bereiche=dict(erg.get("bereiche") or {}, debian=deb))


def quittiert() -> dict:
    d = _lesen(QUITTIERT, {})
    return d if isinstance(d, dict) else {}


def quittieren(ids: list | None = None, alle: bool = False) -> int:
    erg = zustand_ergebnis() or {}
    erlaubt = {b["id"] for b in erg.get("befunde") or [] if b.get("quittierbar")}
    if alle:
        ziel = erlaubt
    else:
        if not isinstance(ids, list):
            raise ValueError("ids muss eine Liste sein")
        ziel = {i for i in ids if isinstance(i, str) and i in erlaubt}
    q = quittiert()
    jetzt = int(time.time())
    for i in ziel:
        q.setdefault(i, jetzt)
    _schreiben(QUITTIERT, q)
    return len(ziel)


def status() -> dict:
    return dict(_status)


def auftrag_payload(d) -> dict:
    """Geprueftes Payload eines Pruefauftrags. Nur ein echtes ``True`` behebt."""
    if not isinstance(d, dict):
        raise ValueError("Optionen der CVE-Prüfung fehlen")
    sw = d.get("schwelle") or ""
    if sw not in ("",) + SCHWELLEN:
        raise ValueError("schwelle muss leer (= Vorgabe) oder einer von "
                         + ", ".join(SCHWELLEN) + " sein")
    return {"beheben": d.get("beheben") is True, "schwelle": sw}


def kurzbericht(erg: dict) -> str:
    """Eine Zeile fuer ``last_result`` der Auftragsliste."""
    if not erg.get("ok"):
        return "Fehler: " + str(erg.get("fehler") or "unbekannt")
    z = erg.get("zaehler") or {}
    teile = [f"{z.get('behebbar', 0)} behebbar", f"{z.get('neustart', 0)} Neustart",
             f"{z.get('offen', 0)} ohne Update"]
    if z.get("lock"):
        teile.append(f"{z['lock']} Python nur über die Lock-Datei")
    beh = erg.get("behebung") or {}
    n = sum(len(r.get("installiert") or []) for r in beh.get("debian") or [])
    py = len((beh.get("python") or {}).get("geaendert") or [])
    if erg.get("beheben"):
        teile.append(f"{n} Debian-Paket(e) und {py} Python-Paket(e) gehoben")
        # WARUM nichts gehoben wurde, gehoert in die Zeile – sonst steht dort
        # "behebbar" neben "0 gehoben" und niemand weiss, was zu tun ist.
        pl = beh.get("plan") or {}
        if pl.get("nur_regulaere_quelle"):
            teile.append(f"{pl['nur_regulaere_quelle']} nur in der regulären Quelle "
                         "(in den Einstellungen nicht freigegeben)")
        if pl.get("node_von_hand"):
            teile.append(f"{pl['node_von_hand']} Node.js nur von Hand "
                         "(Paketquelle außerhalb von Debian)")
        fehl = [r.get("fehler") for r in beh.get("debian") or [] if r.get("fehler")]
        if fehl:
            teile.append("Fehler: " + "; ".join(fehl)[:200])
    nicht = [k for k, v in (erg.get("bereiche") or {}).items() if not v.get("geprueft")]
    if nicht:
        teile.append("nicht geprüft: " + ", ".join(nicht))
    return " · ".join(teile)


def zustand() -> dict:
    erg = zustand_ergebnis()
    einst = einstellungen()
    return {"ergebnis": erg, "laeuft": _status["laeuft"], "schritt": _status["schritt"],
            "einstellungen": einst, "quittiert": sorted(quittiert()),
            "plan": plan(erg, einst) if erg else None}


def badge() -> dict:
    """Zahnrad-Badge: Pakete, die eine Handlung (oder Kenntnisnahme) brauchen.

    Gezaehlt wird je PAKET (Quellpaket bzw. pip-/npm-Name), nicht je CVE – ein
    Kernel mit 300 CVEs ist EINE Aufgabe. Quittierte Befunde zaehlen nicht mit;
    "behebbar" und "neustart" lassen sich nicht quittieren.
    """
    erg = zustand_ergebnis() or {}
    q = quittiert()
    je: dict[tuple, dict] = {}
    for b in erg.get("befunde") or []:
        if b["klasse"] == "ausgenommen" or b["id"] in q:
            continue
        k = (b["bereich"], b["quelle"])
        e = je.setdefault(k, {"art": "cve", "bereich": b["bereich"], "titel": b["quelle"],
                              "zaehler": {}, "ts": int(erg.get("ts") or 0)})
        e["zaehler"][b["klasse"]] = e["zaehler"].get(b["klasse"], 0) + 1
    rang = {"behebbar": 0, "neustart": 1, "nicht_im_index": 2, "zurueckgehalten": 3,
            "lock": 4, "offen": 5}
    posten = sorted(je.values(), key=lambda e: (min(rang.get(k, 9) for k in e["zaehler"]),
                                                e["titel"]))
    return {"anzahl": len(posten), "posten": posten}


if __name__ == "__main__":
    if sys.argv[1:] == ["--debian"]:
        json.dump(_debian_lauf(), sys.stdout, ensure_ascii=False)
        sys.exit(0)
    print("Aufruf: python -m backend.cve_pruefung --debian", file=sys.stderr)
    sys.exit(2)
