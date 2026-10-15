"""Python-Abhaengigkeiten des laufenden Servers aktuell und frei von bekannten Luecken halten.

DER BEFUND (BSI M6, ECHT gemessen 2026-10-06): der Update-Weg holte nur den
CODE. ``requirements.txt`` hob Untergrenzen an (mcp, python-dotenv) – auf ECHT
lief trotzdem mcp 1.25.0 und python-dotenv 1.0.1, und die venv trug 42 bekannte
Schwachstellen in 15 Paketen. Die Sicherheits-CI sah davon nichts: sie prueft
eine FRISCH aufgeloeste Umgebung, nicht die eines Bestandsservers.

WAS DIESES MODUL TUT (beim Dienststart und danach taeglich):

1. ``requirements.txt`` gegen die installierten Pakete pruefen – fehlt etwas
   oder liegt es UNTER der Grenze, wird genau das nachinstalliert.
   ⚠ NIE HERABSTUFEN (auf DEV gemessen 2026-10-06): requirements.txt pinnt
   z. B. ``google-genai==1.5.0``, installiert ist 1.72.0. Ein blindes
   ``pip install -r requirements.txt`` haette es zurueckgestuft. Ein Paket
   UEBER seiner Grenze wird deshalb nur gemeldet und per Constraint
   festgehalten.
2. Die installierten Pakete bei OSV (der Datenbank hinter pip-audit) abfragen.
   Fuer jede Schwachstelle mit Behebung: auf die KLEINSTE behebende Version
   heben – zusammen mit ``-r requirements.txt``, damit die Grenzen dort
   (numpy<2.1, mcp<2, sentence-transformers<4 …) gelten. Bewertete Ausnahmen
   aus ``deploy/security/pip_audit_ausnahmen.txt`` bleiben stehen, solange
   ihr Pruefdatum nicht abgelaufen ist.
3. Danach ``pip check`` und ein Import-Test der Kernpakete. Scheitert eines
   davon, werden die geaenderten Pakete auf ihre vorige Version
   zurueckgesetzt – lieber eine bekannte Luecke als ein Dienst, der nicht
   startet.
4. Hat sich etwas geaendert: Eintrag im Sicherheitsprotokoll, Zustand in
   ``data/logs/abhaengigkeiten.json``, Neustart des Dienstes (die neuen
   Bibliotheken wirken erst im neuen Prozess).

BEWUSST NICHT: torch (CPU-Variante mit lokalem Suffix, kommt nicht von PyPI –
ein Heben holte die CUDA-Variante zurueck, ~6 GB), und keine Hauptversions-
Spruenge ueber Grenzen hinweg, die requirements.txt setzt.

Abschalten: ``JARVIS_ABH_AUTO=0`` (nur pruefen und melden, nichts installieren).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import InvalidVersion, Version

WURZEL = Path(__file__).resolve().parent.parent
REQUIREMENTS = WURZEL / "requirements.txt"
AUSNAHMEN = WURZEL / "deploy" / "security" / "pip_audit_ausnahmen.txt"
ZUSTAND = Path(os.environ.get("JARVIS_ABH_ZUSTAND", str(WURZEL / "data" / "logs" / "abhaengigkeiten.json")))
PYTHON = os.environ.get("JARVIS_ABH_PYTHON", sys.executable)
OSV_URL = os.environ.get("JARVIS_ABH_OSV", "https://api.osv.dev/v1/querybatch")
OSV_VULN_URL = os.environ.get("JARVIS_ABH_OSV_VULN", "https://api.osv.dev/v1/vulns/")
NIE_HEBEN = {"torch", "pip", "setuptools", "wheel"}
# Kernpakete fuer den Import-Test nach einer Aenderung (Importname)
IMPORT_TEST = ("fastapi", "starlette", "uvicorn", "httpx", "requests", "cryptography",
               "mcp", "ldap3", "pyotp", "pdfplumber", "docx", "openpyxl", "pptx",
               "faiss", "sentence_transformers", "numpy", "jwt", "aiohttp", "urllib3")

_sperre = threading.Lock()


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _pip(*args: str, timeout: int = 900) -> subprocess.CompletedProcess:
    umg = dict(os.environ, PIP_DISABLE_PIP_VERSION_CHECK="1", PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([PYTHON, "-m", "pip", *args], capture_output=True, text=True,
                          timeout=timeout, cwd=str(WURZEL), env=umg)


def installiert() -> dict[str, str]:
    """Normierter Paketname -> Version der laufenden Umgebung."""
    r = _pip("list", "--format=json", timeout=120)
    if r.returncode != 0:
        raise RuntimeError("pip list: " + (r.stderr or r.stdout)[-300:])
    return {_norm(p["name"]): p["version"] for p in json.loads(r.stdout or "[]")}


def anforderungen() -> list[Requirement]:
    erg = []
    for z in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        z = z.split("#", 1)[0].strip()
        if not z or z.startswith("-"):
            continue
        try:
            erg.append(Requirement(z))
        except Exception:  # noqa: BLE001
            continue
    return erg


def _nur_grenze(rq: Requirement) -> str:
    """Name + Versionsgrenze ohne Extras/Marker (so verlangt es eine Constraints-Datei)."""
    return rq.name + str(rq.specifier)


def einordnen(inst: dict[str, str]) -> dict[str, list]:
    """Jede Anforderung einordnen: fehlt / zu_alt (unter der Grenze) / zu_neu
    (ueber der Grenze – wird NIE herabgestuft) / ok."""
    erg = {"fehlt": [], "zu_alt": [], "zu_neu": [], "ok": []}
    for rq in anforderungen():
        if rq.marker is not None and not rq.marker.evaluate():
            continue
        v = inst.get(_norm(rq.name))
        if v is None:
            erg["fehlt"].append(rq)
            continue
        try:
            ver = Version(v)
        except InvalidVersion:
            erg["ok"].append(rq)
            continue
        if not rq.specifier or rq.specifier.contains(ver, prereleases=True):
            erg["ok"].append(rq)
            continue
        # Unter- oder ueberschritten? Eine Version ist "zu neu", wenn sie eine
        # Grenze mit <, <=, == oder ~= nach OBEN verletzt.
        zu_neu = False
        for sp in rq.specifier:
            if sp.contains(ver, prereleases=True):
                continue
            try:
                grenze = Version(sp.version.replace(".*", ""))
            except InvalidVersion:
                continue
            if sp.operator in ("<", "<=", "==", "~=", "===") and ver > grenze:
                zu_neu = True
        (erg["zu_neu"] if zu_neu else erg["zu_alt"]).append(rq)
    return erg


def unerfuellt(inst: dict[str, str]) -> list[str]:
    """Anforderungen, die NACHZUINSTALLIEREN sind (fehlt oder unter der Grenze)."""
    e = einordnen(inst)
    return ([str(r) for r in e["fehlt"]]
            + [f"{r} (installiert {inst.get(_norm(r.name))})" for r in e["zu_alt"]])


def _constraints(inst: dict[str, str]) -> str:
    """Grenzen fuer jeden pip-Lauf: die aus requirements.txt – ausser bei Paketen,
    die schon UEBER ihrer Grenze stehen: die werden auf den Ist-Stand genagelt."""
    e = einordnen(inst)
    zeilen = [_nur_grenze(r) for r in e["ok"] + e["fehlt"] + e["zu_alt"] if r.specifier]
    zeilen += [f"{r.name}=={inst[_norm(r.name)]}" for r in e["zu_neu"]]
    # NIE HERABSTUFEN, auch nicht transitiv: auf DEV zog eine Hebung passlib
    # nach, und pip stufte bcrypt 5.0.0 -> 4.3.0 zurueck (2026-10-06). Jedes
    # installierte Paket ohne eigene Grenze bekommt "nicht unter dem Ist-Stand";
    # lokale Versionen (torch 2.10.0+cpu) werden genau festgehalten.
    eigene = {_norm(r.name) for r in e["ok"] + e["fehlt"] + e["zu_alt"] + e["zu_neu"]}
    for n, v in sorted(inst.items()):
        if n in eigene:
            continue
        zeilen.append(f"{n}=={v}" if "+" in v else f"{n}>={v}")
    return "\n".join(zeilen) + "\n"


def ausnahmen(heute: dt.date | None = None) -> set[str]:
    """Gueltige (nicht abgelaufene) Ausnahme-IDs aus der bewerteten Liste."""
    heute = heute or dt.date.today()
    ids = set()
    if not AUSNAHMEN.is_file():
        return ids
    for z in AUSNAHMEN.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*([A-Z][A-Z0-9]*-[0-9A-Za-z-]+)\s+(\d{4}-\d{2}-\d{2})\s+#", z)
        if m:
            try:
                if dt.date.fromisoformat(m.group(2)) >= heute:
                    ids.add(m.group(1))
            except ValueError:
                pass
    return ids


def _post(url: str, daten: dict) -> dict:
    r = urllib.request.Request(url, data=json.dumps(daten).encode(),
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=30) as a:  # nosec B310 – feste https-Adresse
        return json.loads(a.read() or b"{}")


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as a:  # nosec B310 – feste https-Adresse
        return json.loads(a.read() or b"{}")


def _behebende_version(vuln: dict, paket: str, v_inst: Version) -> Version | None:
    """Kleinste Version > installiert, die diese Schwachstelle laut OSV behebt."""
    kandidaten = []
    for aff in vuln.get("affected") or []:
        if _norm((aff.get("package") or {}).get("name", "")) != paket:
            continue
        for rg in aff.get("ranges") or []:
            if rg.get("type") != "ECOSYSTEM":
                continue
            for ev in rg.get("events") or []:
                f = ev.get("fixed")
                if f:
                    try:
                        fv = Version(f)
                    except InvalidVersion:
                        continue
                    if fv > v_inst and not fv.is_prerelease:
                        kandidaten.append(fv)
    return min(kandidaten) if kandidaten else None


def schwachstellen(inst: dict[str, str], erlaubt: set[str] | None = None) -> list[dict]:
    """Bekannte Schwachstellen der installierten Pakete (OSV).

    Je Fund: paket, version, id, aliase, behoben_in (str oder None),
    ausgenommen (bool – bewertet in pip_audit_ausnahmen.txt)."""
    erlaubt = ausnahmen() if erlaubt is None else erlaubt
    pakete = sorted(inst.items())
    erg = []
    for i in range(0, len(pakete), 500):
        stueck = pakete[i:i + 500]
        antwort = _post(OSV_URL, {"queries": [
            {"package": {"name": n, "ecosystem": "PyPI"}, "version": v} for n, v in stueck]})
        for (name, ver), res in zip(stueck, antwort.get("results") or []):
            ids = [x.get("id") for x in (res.get("vulns") or []) if x.get("id")]
            for vid in ids:
                try:
                    vuln = _get(OSV_VULN_URL + vid)
                except Exception:  # noqa: BLE001
                    vuln = {"id": vid}
                aliase = set(vuln.get("aliases") or []) | {vid}
                try:
                    fix = _behebende_version(vuln, name, Version(ver))
                except InvalidVersion:
                    fix = None
                erg.append({"paket": name, "version": ver, "id": vid, "aliase": sorted(aliase),
                            "behoben_in": str(fix) if fix else None,
                            "ausgenommen": bool(aliase & erlaubt)})
    return erg


def _ziele(funde: list[dict]) -> dict[str, str]:
    """Paket -> zu installierende Version (groesste der kleinsten Behebungen)."""
    ziele: dict[str, Version] = {}
    for f in funde:
        if f["ausgenommen"] or not f["behoben_in"] or f["paket"] in NIE_HEBEN:
            continue
        v = Version(f["behoben_in"])
        if f["paket"] not in ziele or v > ziele[f["paket"]]:
            ziele[f["paket"]] = v
    return {k: str(v) for k, v in ziele.items()}


def _import_test() -> tuple[bool, str]:
    code = ("import importlib,sys\nfehl=[]\n"
            f"for m in {list(IMPORT_TEST)!r}:\n"
            "    try:\n        importlib.import_module(m)\n"
            "    except ModuleNotFoundError as e:\n"
            "        if e.name != m: fehl.append(m+': '+str(e))\n"
            "    except Exception as e:\n        fehl.append(m+': '+repr(e)[:200])\n"
            "print('\\n'.join(fehl)); sys.exit(1 if fehl else 0)\n")
    r = subprocess.run([PYTHON, "-c", code], capture_output=True, text=True, timeout=600,
                       cwd=str(WURZEL))
    return r.returncode == 0, (r.stdout + r.stderr).strip()[-600:]


def _zuruecksetzen(vorher: dict[str, str], nachher: dict[str, str]) -> list[str]:
    alt = [f"{n}=={v}" for n, v in vorher.items() if nachher.get(n) != v and n not in NIE_HEBEN]
    neu = [n for n in nachher if n not in vorher]
    if alt:
        _pip("install", "--no-deps", *alt)
    if neu:
        _pip("uninstall", "-y", *neu)
    return alt + [f"-{n}" for n in neu]


def _speichern(zustand: dict) -> None:
    try:
        ZUSTAND.parent.mkdir(parents=True, exist_ok=True)
        tmp = ZUSTAND.with_suffix(".tmp")
        tmp.write_text(json.dumps(zustand, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, ZUSTAND)
    except OSError:
        pass


def _melden(art: str, **details) -> None:
    try:
        from backend import sicherheits_log
        sicherheits_log.ereignis(art, **details)
    except Exception:  # noqa: BLE001
        pass


def abgleichen(installieren: bool | None = None) -> dict:
    """Ein Lauf. Rueckgabe/Zustand: geaendert (Liste), offen (Funde ohne Behebung
    oder mit gescheiterter Hebung), ausgenommen, fehler, zurueckgesetzt."""
    if installieren is None:
        installieren = os.environ.get("JARVIS_ABH_AUTO", "1") != "0"
    if not _sperre.acquire(blocking=False):
        return {"ok": False, "fehler": "laeuft bereits"}
    erg: dict = {"zeit": time.strftime("%Y-%m-%dT%H:%M:%S"), "geaendert": [], "offen": [],
                 "ausgenommen": [], "fehler": "", "zurueckgesetzt": [], "installieren": installieren}
    try:
        vorher = installiert()
        fehl = unerfuellt(vorher)
        erg["unerfuellt"] = fehl
        erg["ueber_grenze"] = [f"{r} (installiert {vorher.get(_norm(r.name))})"
                               for r in einordnen(vorher)["zu_neu"]]
        try:
            funde = schwachstellen(vorher)
        except Exception as e:  # noqa: BLE001 – OSV nicht erreichbar: nur requirements
            funde = []
            erg["fehler"] = f"OSV nicht erreichbar: {e}"
        ziele = _ziele(funde)
        erg["ausgenommen"] = sorted({f["id"] for f in funde if f["ausgenommen"]})
        if installieren and (fehl or ziele):
            import tempfile
            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as cf:
                cf.write(_constraints(vorher))
            try:
                basis = [str(r) for r in einordnen(vorher)["fehlt"] + einordnen(vorher)["zu_alt"]]
                hebungen = [f"{n}=={v}" for n, v in ziele.items()]
                r = _pip("install", "-c", cf.name, *basis, *hebungen)
                if r.returncode != 0 and hebungen:
                    # Gemeinsam unloesbar (eine Hebung widerspricht einer Grenze):
                    # erst das Fehlende allein, dann jede Hebung einzeln
                    if basis:
                        _pip("install", "-c", cf.name, *basis)
                    for h in hebungen:
                        ri = _pip("install", "-c", cf.name, h)
                        if ri.returncode != 0:
                            erg["offen"].append({"paket": h.split("==")[0], "ziel": h.split("==")[1],
                                                 "grund": (ri.stderr or ri.stdout).strip()[-200:]})
                elif r.returncode != 0:
                    erg["fehler"] = ("pip install: " + (r.stderr or r.stdout).strip()[-300:])
            finally:
                os.unlink(cf.name)
            nachher = installiert()
            pc = _pip("check", timeout=120)
            imp_ok, imp_txt = _import_test()
            if pc.returncode != 0 or not imp_ok:
                erg["zurueckgesetzt"] = _zuruecksetzen(vorher, nachher)
                erg["fehler"] = ("Zurueckgesetzt – " + ("pip check: " + pc.stdout.strip()[-300:]
                                 if pc.returncode != 0 else "Import-Test: " + imp_txt))
                nachher = installiert()
            erg["geaendert"] = sorted(f"{n} {vorher.get(n, '-')} -> {v}"
                                      for n, v in nachher.items() if vorher.get(n) != v)
            danach = schwachstellen(nachher) if funde else []
        else:
            danach = funde
        erg["offen"] += [{"paket": f["paket"], "version": f["version"], "id": f["id"],
                          "behoben_in": f["behoben_in"]}
                         for f in danach if not f["ausgenommen"]]
        erg["unerfuellt_danach"] = unerfuellt(installiert()) if erg["geaendert"] else fehl
        erg["ok"] = not erg["fehler"]
    except Exception as e:  # noqa: BLE001
        erg["ok"] = False
        erg["fehler"] = f"{type(e).__name__}: {e}"
    finally:
        _sperre.release()
    _speichern(erg)
    if erg.get("geaendert") or erg.get("zurueckgesetzt"):
        _melden("abhaengigkeiten", ergebnis="geaendert" if erg.get("geaendert") else "zurueckgesetzt",
                geaendert=erg.get("geaendert")[:40], zurueckgesetzt=erg.get("zurueckgesetzt")[:40],
                offen=len(erg.get("offen") or []))
    return erg


def zustand() -> dict:
    try:
        return json.loads(ZUSTAND.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


if __name__ == "__main__":
    # Von Hand / per Wartung:  venv/bin/python -m backend.abhaengigkeiten [--nur-pruefen]
    _e = abgleichen(installieren="--nur-pruefen" not in sys.argv)
    print(json.dumps(_e, indent=1, ensure_ascii=False))
    sys.exit(0 if _e.get("ok") else 1)
