#!/usr/bin/env python3
"""Waechter: kein Import ohne Deklaration.

DER ANLASS (2026-08-12): Der PDF-Anhang im Chat war auf ECHT tot, weil der Code
``import pypdf`` machte und pypdf in KEINER requirements.txt stand. Auf DEV war
es zufaellig mitinstalliert, auf ECHT nicht – das venv dort wurde mehrfach
ausgeduennt. Der Fehler war damit fuer jeden, der auf DEV testet, unsichtbar.

Diese Klasse von Abweichung kann an jeder anderen Stelle genauso schlummern.
Der Test sammelt deshalb ALLE Importe unter ``backend/`` und ``skills/`` und
verlangt fuer jeden Fremdimport eine Deklaration – in ``requirements.txt`` oder
im Manifest eines Skills (``dependencies``/``optional_dependencies``).

WICHTIG, und der Grund, warum der pypdf-Fall so lange lief: ein Import in einem
``try``/``except ImportError`` gilt hier NICHT als entschuldigt. Genau dort stand
pypdf. Optional heisst "darf fehlen", nicht "muss nirgends stehen" – wo eine
Funktion ohne das Paket ausfaellt, gehoert es in ein Manifest, damit die
Installation es kennt.

Der Test braucht keine installierten Pakete: er liest Quelltext (ast) und
Textdateien. Er laeuft damit lokal wie auf jedem Server.

Lauf:  python3 tests/test_dependency_declarations.py
"""
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ok = 0
fehler = 0


def pruefe(was, bedingung, detail=""):
    global ok, fehler
    if bedingung:
        ok += 1
        print(f"  \033[32m✓\033[0m {was}")
    else:
        fehler += 1
        print(f"  \033[31m✗\033[0m {was}" + (f"\n      {detail}" if detail else ""))


def abschnitt(t):
    print(f"\n\033[1m{t}\033[0m")


# ── Modulname → Verteilungsname ──────────────────────────────────────────────
# Nur die Faelle, in denen beides auseinanderfaellt. Alles andere wird direkt
# verglichen. Bewusst eine Tabelle im Test und nicht `packages_distributions()`:
# jene Auskunft gibt es nur fuer INSTALLIERTE Pakete – der Test muss aber genau
# das finden, was NICHT installiert ist.
ALIAS = {
    "PIL": "pillow",
    "cv2": "opencv-python-headless",
    "fitz": "pymupdf",
    "yaml": "pyyaml",
    "dateutil": "python-dateutil",
    "sklearn": "scikit-learn",
    "faiss": "faiss-cpu",
    "dotenv": "python-dotenv",
    "jwt": "pyjwt",
    "bs4": "beautifulsoup4",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "pam": "python-pam",
    "multipart": "python-multipart",
    "google": "google-genai",
    "googleapiclient": "google-api-python-client",
    "google_auth_httplib2": "google-auth-httplib2",
    "google_auth_oauthlib": "google-auth-oauthlib",
    "apscheduler": "apscheduler",
    "edge_tts": "edge-tts",
    "sentence_transformers": "sentence-transformers",
    "face_recognition": "face-recognition",
    "faster_whisper": "faster-whisper",
    "pytesseract": "pytesseract",
    "pdf2image": "pdf2image",
    "sse_starlette": "sse-starlette",
    "wsgidav": "wsgidav",
    "hdbcli": "hdbcli",
    "pyrfc": "pyrfc",
    "telegram": "python-telegram-bot",
    "serial": "pyserial",
    "usb": "pyusb",
    "magic": "python-magic",
    "Xlib": "python3-xlib",
    "OpenSSL": "pyopenssl",
    "zoneinfo": "",          # stdlib ab 3.9
}

# Ausdrueckliche, begruendete Ausnahmen. Jede Zeile nennt den Grund – eine
# Sammelfreigabe waere das Ende des Waechters.
AUSNAHMEN = {
    # Optionale Beschleuniger/Alternativen, die der Code nur benutzt, WENN sie
    # da sind, und deren Fehlen keine Funktion abschaltet:
    "uvloop": "optionaler Event-Loop von uvicorn[standard], kein eigener Aufruf",
    "setproctitle": "optional in uvicorn[standard]",
    "torch": ("kommt mit sentence-transformers; ein eigener Eintrag in der\n              requirements.txt wuerde die CUDA-Variante zurueckholen, die am\n              2026-07-19 auf ECHT bewusst gegen torch+cpu getauscht wurde"),
}


def stdlib() -> set:
    namen = set(sys.stdlib_module_names)
    namen.update({"__future__"})
    return namen


def lokale_module() -> set:
    """Alles, was im Repo selbst liegt (Paket-Ordner oder Modul-Datei)."""
    namen = set()
    for p in ROOT.iterdir():
        if p.is_dir() and (p / "__init__.py").exists():
            namen.add(p.name)
        elif p.is_dir() and p.name in {"backend", "skills", "tests", "deploy", "services"}:
            namen.add(p.name)
        elif p.suffix == ".py":
            namen.add(p.stem)
    # Module INNERHALB von backend/ und der Skills werden auch flach importiert
    for unter in (ROOT / "backend", ROOT / "backend" / "tools", ROOT / "backend" / "broker"):
        if unter.is_dir():
            for p in unter.iterdir():
                if p.suffix == ".py":
                    namen.add(p.stem)
                elif p.is_dir() and (p / "__init__.py").exists():
                    namen.add(p.name)
    for p in (ROOT / "skills").glob("*/"):
        namen.add(p.name)
        # Ein Skill importiert seine Nachbardateien flach ("import camera_manager").
        for datei in p.glob("*.py"):
            namen.add(datei.stem)
        for unter in p.iterdir():
            if unter.is_dir() and (unter / "__init__.py").exists():
                namen.add(unter.name)
    return namen


def normalisiere(name: str) -> str:
    """PEP-503: Gross/klein und -_. sind gleichwertig."""
    return re.sub(r"[-_.]+", "-", name).lower()


def deklarationen() -> tuple[set, dict]:
    """(alle deklarierten Verteilungen, {Skillname: {Verteilungen}})."""
    alle = set()
    req = ROOT / "requirements.txt"
    for zeile in req.read_text(encoding="utf-8").splitlines():
        z = zeile.split("#")[0].strip()
        if not z or z.startswith("-"):
            continue
        alle.add(normalisiere(re.split(r"[<>=!\[; ]", z)[0]))

    je_skill = {}
    # Fremd-/importierte Skills bringen statt eines Manifests eine eigene
    # requirements.txt mit (z. B. skills/jarvis-vision). Die zaehlt genauso:
    # entscheidend ist, dass die Abhaengigkeit IRGENDWO steht.
    for eigen in (ROOT / "skills").glob("*/requirements.txt"):
        menge = set()
        for zeile in eigen.read_text(encoding="utf-8", errors="replace").splitlines():
            z = zeile.split("#")[0].strip()
            if z and not z.startswith("-"):
                menge.add(normalisiere(re.split(r"[<>=!\[; ]", z)[0]))
        je_skill.setdefault(eigen.parent.name, set()).update(menge)
        alle |= menge

    for manifest in (ROOT / "skills").glob("*/skill.json"):
        try:
            daten = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception:
            continue
        menge = set()
        for feld in ("dependencies", "optional_dependencies"):
            for eintrag in daten.get(feld, []) or []:
                menge.add(normalisiere(re.split(r"[<>=!\[; ]", str(eintrag))[0]))
        je_skill.setdefault(manifest.parent.name, set()).update(menge)
        alle |= menge
    return alle, je_skill


def importe(datei: Path) -> set:
    """Oberste Modulnamen aller Importe einer Datei (auch verschachtelte)."""
    try:
        baum = ast.parse(datei.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return set()
    raus = set()
    for knoten in ast.walk(baum):
        if isinstance(knoten, ast.Import):
            for a in knoten.names:
                raus.add(a.name.split(".")[0])
        elif isinstance(knoten, ast.ImportFrom):
            if knoten.level:                 # relativer Import -> lokal
                continue
            if knoten.module:
                raus.add(knoten.module.split(".")[0])
    return raus


def main() -> int:
    STD = stdlib()
    LOKAL = lokale_module()
    DEKL, JE_SKILL = deklarationen()

    dateien = [p for p in ROOT.glob("backend/**/*.py")]
    dateien += [p for p in ROOT.glob("skills/**/*.py")]
    dateien = [p for p in dateien if "__pycache__" not in p.parts and "venv" not in p.parts]

    abschnitt("1) Grundlage")
    pruefe(f"{len(dateien)} Python-Dateien gefunden", len(dateien) > 50, str(len(dateien)))
    pruefe(f"{len(DEKL)} Verteilungen deklariert (requirements + Manifeste)", len(DEKL) > 20)

    fehlend = {}          # Modul -> Dateien
    nur_skill = {}        # Modul -> Verteilung (nur im Manifest, nicht requirements)
    req_only, _ = deklarationen()
    req_namen = set()
    for zeile in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        z = zeile.split("#")[0].strip()
        if z and not z.startswith("-"):
            req_namen.add(normalisiere(re.split(r"[<>=!\[; ]", z)[0]))

    for datei in dateien:
        for modul in importe(datei):
            if modul in STD or modul in LOKAL or modul in AUSNAHMEN:
                continue
            vert = normalisiere(ALIAS.get(modul, modul))
            if not vert:                     # per Alias als stdlib markiert
                continue
            if vert in DEKL:
                if vert not in req_namen and datei.parts[-3:][0] != "skills":
                    nur_skill.setdefault(modul, vert)
                continue
            fehlend.setdefault(modul, []).append(datei.relative_to(ROOT).as_posix())

    abschnitt("2) Jeder Fremdimport ist deklariert")
    if fehlend:
        for modul, orte in sorted(fehlend.items()):
            print(f"      \033[31m{modul}\033[0m -> {', '.join(orte[:3])}"
                  + (f" (+{len(orte)-3} weitere)" if len(orte) > 3 else ""))
    pruefe("keine undeklarierten Importe", not fehlend,
           f"{len(fehlend)} Modul(e): {', '.join(sorted(fehlend))}" if fehlend else "")

    abschnitt("3) Der konkrete Rueckfall von 2026-08-12")
    quelle = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    pruefe("backend/main.py importiert pypdf nicht", "import pypdf" not in quelle
           and "from pypdf" not in quelle)
    pruefe("pypdf ist nirgends im Backend importiert",
           "pypdf" not in {m for d in dateien if d.parts[-2] != "skills" for m in importe(d)})

    abschnitt("4) Hinweise (kein Fehler)")
    if nur_skill:
        print("   Nur ueber ein Skill-Manifest gedeckt – faellt aus, wenn der Skill")
        print("   nie installiert wurde. Das ist zulaessig, wenn die Funktion dann")
        print("   sauber abschaltet:")
        for modul, vert in sorted(nur_skill.items()):
            print(f"     - {modul} (als {vert})")
    else:
        print("   keine")

    print(f"\n{ok} ok, {fehler} Fehler ({ok + fehler} Pruefungen)")
    return 1 if fehler else 0


if __name__ == "__main__":
    sys.exit(main())
