#!/usr/bin/env python3
"""Waechter: fehlende pip-Pakete AKTIVER Skills kommen von selbst an (ECHT 2026-10-27).

Vorfall: die Anonymisierung der AI-Maus brachte vier neue `dependencies` in
skills/ai_mouse/skill.json. Auf ECHT war der Skill laengst an – installiert
wurden Skill-Pakete aber nur beim Einschalten. Ergebnis: „Namenserkennung auf
diesem Server nicht eingerichtet". Nach der Nachinstallation blieb die Meldung,
weil der laufende Hilfsprozess seine Faehigkeiten nur beim Start las.

Geprueft wird die WIRKUNG mit Attrappen (pip, Paketliste, Import-Test):
  1. skill_pakete_nachziehen: installiert mit Constraints, die JEDES vorhandene
     Paket genau auf dem Ist-Stand halten; nur-pruefen installiert nichts;
     ein gescheiterter Satz wird nicht wiederholt, ein geaenderter schon;
     Import-Test scheitert -> neue Pakete wieder weg; ein schon vorher roter
     `pip check` ist kein Fehlschlag dieser Installation.
  2. SkillManager.fehlende_pip_aktiver_skills: nur EINGESCHALTETE Skills,
     Vorgabe aus dem Manifest, wenn kein Zustand gespeichert ist.
  3. Der Hilfsprozess der Anonymisierung startet neu, wenn seit seinem Start
     Erkennungs-Pakete dazugekommen sind – und NUR dann.
  4. Regel am Syntaxbaum: der Start-Haken ruft die Skill-Pakete im ELSE-Zweig
     des Neustarts (sonst schoesse der Neustart den pip ab).

``backend.config`` nur als Stub. Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import ast
import asyncio
import os
import sys
import tempfile
import types
from pathlib import Path

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK = FAIL = 0


def check(name, bed, detail=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (" – " + str(detail) if detail else ""))


def abbruch(grund):
    print("ABBRUCH (Exit 2): " + grund)
    sys.exit(2)


# backend.config als Stub – der echte Import schreibt die Live-settings.json.
_cfg_mod = types.ModuleType("backend.config")


class _Cfg:
    zustaende: dict = {}

    def get_skill_states(self):
        return self.zustaende


_cfg_mod.config = _Cfg()
sys.modules["backend.config"] = _cfg_mod

try:
    from backend import abhaengigkeiten as A
    from backend.skills import manager as MGR
    from backend import anonymisieren as AN
except Exception as e:  # noqa: BLE001
    abbruch(f"Module nicht ladbar: {e}")

SK = Path(tempfile.mkdtemp(prefix="jv_skp_"))
A.ZUSTAND = SK / "abh.json"
A.SKILL_ZUSTAND = SK / "skill_pakete.json"
# Eigener Skill-Baum: der echte traegt skills/ai_mouse/requirements.lock, und die
# Abschnitte 1a-1f messen den Weg OHNE Skill-Lock.
A.SKILLS = SK / "skills"
A._melden = lambda art, **d: None


class R:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


stand = {"inst": {}, "pip_rc": 0, "check_vorher": 0, "check_nachher": 0, "neu": {}}
aufrufe: list = []
constraints: list = []
checks = {"n": 0}


def pip_attrappe(*args, timeout=900):
    aufrufe.append(args)
    if args[0] == "check":
        checks["n"] += 1
        return R(stand["check_vorher"] if checks["n"] == 1 else stand["check_nachher"])
    if args[0] == "install" and "-c" in args:
        constraints.append(Path(args[args.index("-c") + 1]).read_text())
        if stand["pip_rc"] == 0:
            stand["inst"].update(stand["neu"])
        return R(stand["pip_rc"], err="ResolutionImpossible" if stand["pip_rc"] else "")
    if args[0] == "uninstall":
        for n in args[2:]:
            stand["inst"].pop(n, None)
    return R(0)


A._pip = pip_attrappe
A.installiert = lambda: dict(stand["inst"])
A._import_test = lambda: (True, "")


def neu_lauf(inst, neu, pip_rc=0, check_vorher=0, check_nachher=0):
    stand.update(inst=dict(inst), neu=dict(neu), pip_rc=pip_rc,
                 check_vorher=check_vorher, check_nachher=check_nachher)
    aufrufe.clear()
    constraints.clear()
    checks["n"] = 0


BASIS = {"numpy": "2.0.2", "torch": "2.10.0+cpu", "pydantic": "2.14.1"}
SPECS = ["presidio-analyzer==2.2.365", "spacy==3.8.18"]

print("\n── 1a. Installation mit Ist-Stand-Constraints")
neu_lauf(BASIS, {"presidio-analyzer": "2.2.365", "spacy": "3.8.18"})
erg = A.skill_pakete_nachziehen({"ai_mouse": SPECS}, installieren=True)
inst_aufrufe = [x for x in aufrufe if x[0] == "install"]
check("Positivkontrolle: genau EIN pip install lief", len(inst_aufrufe) == 1, aufrufe)
if len(inst_aufrufe) != 1:
    abbruch("ohne Installationslauf sind die folgenden Pruefungen trivial")
check("…mit genau den fehlenden Specs", all(s in inst_aufrufe[0] for s in SPECS), inst_aufrufe)
zeilen = set((constraints[0] if constraints else "").split())
check("Constraints halten JEDES vorhandene Paket auf dem Ist-Stand (==)",
      zeilen == {"numpy==2.0.2", "pydantic==2.14.1", "torch==2.10.0+cpu"}, zeilen)
check("…und begrenzen die neuen Pakete NICHT", not any(z.startswith(("spacy", "presidio"))
                                                         for z in zeilen), zeilen)
check("Aenderung gemeldet", erg["geaendert"].get("ai_mouse") ==
      ["presidio-analyzer - -> 2.2.365", "spacy - -> 3.8.18"], erg)
check("kein Fehler", not erg["fehler"], erg)

print("\n── 1b. Nur pruefen (JARVIS_ABH_AUTO=0)")
neu_lauf(BASIS, {"spacy": "3.8.18"})
alt = os.environ.get("JARVIS_ABH_AUTO")
os.environ["JARVIS_ABH_AUTO"] = "0"
try:
    erg = A.skill_pakete_nachziehen({"ai_mouse": SPECS})
finally:
    if alt is None:
        os.environ.pop("JARVIS_ABH_AUTO", None)
    else:
        os.environ["JARVIS_ABH_AUTO"] = alt
check("Schalter aus: KEIN pip install", not any(x[0] == "install" for x in aufrufe), aufrufe)
check("…Fehlendes als offen gemeldet", erg.get("offen") == {"ai_mouse": sorted(SPECS)}, erg)

print("\n── 1c. Gescheiterter Satz wird nicht wiederholt")
neu_lauf(BASIS, {}, pip_rc=1)
erg = A.skill_pakete_nachziehen({"ai_mouse": SPECS}, installieren=True)
check("pip scheitert -> Fehler mit Grund", "ResolutionImpossible" in erg["fehler"].get("ai_mouse", ""),
      erg)
neu_lauf(BASIS, {}, pip_rc=1)
erg = A.skill_pakete_nachziehen({"ai_mouse": SPECS}, installieren=True)
check("zweiter Start mit DENSELBEN Specs: kein pip install, als uebersprungen gemeldet",
      not any(x[0] == "install" for x in aufrufe) and erg["uebersprungen"] == ["ai_mouse"],
      (aufrufe, erg))
neu_lauf(BASIS, {"spacy": "3.8.18", "presidio-analyzer": "2.2.366"})
erg = A.skill_pakete_nachziehen({"ai_mouse": ["presidio-analyzer==2.2.366", "spacy==3.8.18"]},
                                installieren=True)
check("geaendertes Manifest: neuer Versuch, gelingt", bool(erg["geaendert"].get("ai_mouse"))
      and any(x[0] == "install" for x in aufrufe), erg)
neu_lauf(BASIS, {}, pip_rc=0)
erg = A.skill_pakete_nachziehen({"ai_mouse": SPECS}, installieren=True)
check("nach Erfolg ist das Gedaechtnis geleert: alter Satz wird wieder versucht",
      any(x[0] == "install" for x in aufrufe), aufrufe)

print("\n── 1d. Import-Test scheitert -> neue Pakete wieder weg")
A._import_test = lambda: (False, "numpy: ImportError")
neu_lauf(BASIS, {"spacy": "3.8.18"})
erg = A.skill_pakete_nachziehen({"vision": ["spacy==3.8.18"]}, installieren=True)
check("Fehler gemeldet (Import-Test)", "Import-Test" in erg["fehler"].get("vision", ""), erg)
check("…und das neue Paket deinstalliert", "spacy" not in stand["inst"]
      and any(x[0] == "uninstall" for x in aufrufe), (stand["inst"], aufrufe))
check("…Kernpakete unveraendert", all(stand["inst"].get(n) == v for n, v in BASIS.items()),
      stand["inst"])
A._import_test = lambda: (True, "")

print("\n── 1e. Schon vorher roter pip check ist kein Fehlschlag")
neu_lauf(BASIS, {"opencv-python-headless": "4.13.0.92"}, check_vorher=1, check_nachher=1)
erg = A.skill_pakete_nachziehen({"cv": ["opencv-python-headless==4.13.0.92"]}, installieren=True)
check("vorher rot, nachher rot: gilt als installiert", bool(erg["geaendert"].get("cv"))
      and not erg["fehler"], erg)
neu_lauf(BASIS, {"opencv-python-headless": "4.13.0.92"}, check_vorher=0, check_nachher=1)
erg = A.skill_pakete_nachziehen({"cv2": ["opencv-python-headless==4.13.0.92"]}, installieren=True)
check("vorher gruen, nachher rot: Fehler und zurueck", "pip check" in erg["fehler"].get("cv2", "")
      and "opencv-python-headless" not in stand["inst"], erg)

print("\n── 1e2. Zwei Skills, ein Paket: der zweite installiert nichts mehr")
neu_lauf(BASIS, {"opencv-python-headless": "4.13.0.92"})
erg = A.skill_pakete_nachziehen({"ai_mouse": ["opencv-python-headless==4.13.0.92"],
                                 "vision": ["opencv-python-headless>=4.8.0"]}, installieren=True)
inst_aufrufe = [x for x in aufrufe if x[0] == "install"]
check("genau EIN pip install fuer das gemeinsame Paket", len(inst_aufrufe) == 1, inst_aufrufe)
check("…der zweite Skill steht nicht als 'nachinstalliert' da", "vision" not in erg["geaendert"]
      and erg["geaendert"].get("ai_mouse"), erg)
neu_lauf(BASIS, {"de-core-news-md": "3.8.0"})
erg = A.skill_pakete_nachziehen({"x": ["de-core-news-md @ https://beispiel.de/m.whl"]},
                                installieren=True)
neu_lauf(dict(BASIS, **{"de-core-news-md": "3.8.0"}), {})
erg = A.skill_pakete_nachziehen({"x": ["de-core-news-md @ https://beispiel.de/m.whl"]},
                                installieren=True)
check("Spec mit Adresse (name @ url) gilt als vorhanden, wenn installiert",
      not any(x[0] == "install" for x in aufrufe), aufrufe)

print("\n── 1f. Sperre: kein zweiter pip neben einem laufenden Abgleich")
neu_lauf(BASIS, {"spacy": "3.8.18"})
A._sperre.acquire()
try:
    erg = A.skill_pakete_nachziehen({"neu": ["spacy==3.8.18"]}, installieren=True)
finally:
    # Bedingt: eine Sabotage, die die Sperre umgeht, gibt sie am Ende frei.
    if A._sperre.locked():
        A._sperre.release()
check("Sperre belegt: kein pip install", not any(x[0] == "install" for x in aufrufe), aufrufe)

print("\n── 1g. Mit Skill-Lock: nur Fehlendes, mit Hash-Pflicht, ohne Aufloesung")
LOCK_TEXT = """# Kopf
numpy==2.0.2 \\
    --hash=sha256:aaa \\
    --hash=sha256:bbb
    # via -c kern.txt
spacy==3.8.18 \\
    --hash=sha256:ccc
    # via
    #   skill.json
de-core-news-md @ https://beispiel.de/m.whl#sha256=ddd \\
    --hash=sha256:ddd
    # via skill.json
"""
(A.SKILLS / "mitlock").mkdir(parents=True, exist_ok=True)
(A.SKILLS / "mitlock" / "requirements.lock").write_text(LOCK_TEXT)
bl = A.lock_bloecke(LOCK_TEXT)
check("Positivkontrolle: drei Eintraege gelesen (auch 'name @ url')",
      sorted(bl) == ["de-core-news-md", "numpy", "spacy"], sorted(bl))
check("…ein Eintrag traegt ALLE seine Hashes, keine Kommentare",
      bl.get("numpy", "").count("--hash=") == 2 and "#" not in bl.get("numpy", "").replace(
          "--hash=sha256", ""), bl.get("numpy"))
gelesen = {}


def pip_lock(*args, timeout=900):
    aufrufe.append(args)
    if args[0] == "check":
        return R(0)
    if args[0] == "install" and "-r" in args:
        gelesen["text"] = Path(args[args.index("-r") + 1]).read_text()
        stand["inst"].update({"spacy": "3.8.18", "de-core-news-md": "3.8.0"})
    return R(0)


neu_lauf(BASIS, {})
A._pip = pip_lock
erg = A.skill_pakete_nachziehen({"mitlock": ["spacy==3.8.18"]}, installieren=True)
A._pip = pip_attrappe
inst_aufrufe = [x for x in aufrufe if x[0] == "install"]
check("Positivkontrolle: ein pip install lief", len(inst_aufrufe) == 1, aufrufe)
erster = inst_aufrufe[0] if inst_aufrufe else ()
check("…mit --require-hashes und --no-deps", "--require-hashes" in erster
      and "--no-deps" in erster, erster)
check("…ohne Constraints (keine Aufloesung)", "-c" not in erster, erster)
check("…nur die FEHLENDEN Eintraege (spacy, Modell), nicht numpy",
      "spacy==3.8.18" in gelesen.get("text", "") and "de-core-news-md" in gelesen.get("text", "")
      and "numpy" not in gelesen.get("text", ""), gelesen.get("text"))
check("…samt Hash", "--hash=sha256:ccc" in gelesen.get("text", ""), gelesen.get("text"))
check("…Aenderung gemeldet", bool(erg["geaendert"].get("mitlock")), erg)
args, tmp = A.skill_pip_aufruf("ohnelock", ["x==1"], {})
check("ohne Skill-Lock: bisheriger Aufruf", args == ["install", "x==1"] and tmp == "", args)
args, tmp = A.skill_pip_aufruf("mitlock", ["spacy==3.8.18"],
                               {"numpy": "2.0.2", "spacy": "3.8.18", "de-core-news-md": "3.8.0"})
check("mit Skill-Lock und nichts fehlt: kein Aufruf", args == [] and tmp == "", args)

print("\n── 2. Welche Skills zaehlen")


class Loader:
    def discover_skills(self):
        return [
            {"path": "/x/an", "dependencies": ["spacy==3.8.18", "numpy<2.1"]},
            {"path": "/x/aus", "dependencies": ["presidio-analyzer==2.2.365"]},
            {"path": "/x/vorgabe_an", "enabled": True, "dependencies": ["opencv-python-headless"]},
            {"path": "/x/vorgabe_aus", "enabled": False, "dependencies": ["tldextract"]},
            {"path": "/x/komplett", "dependencies": ["numpy"]},
            {"error": "kaputt"},
        ]


sm = MGR.SkillManager.__new__(MGR.SkillManager)
sm.loader = Loader()
sm._installed_packages = lambda: {"numpy"}
_cfg_mod.config.zustaende = {"an": {"enabled": True}, "aus": {"enabled": False},
                             "komplett": {"enabled": True}}
fehlt = sm.fehlende_pip_aktiver_skills()
check("eingeschalteter Skill: nur das Fehlende", fehlt.get("an") == ["spacy==3.8.18"], fehlt)
check("ausgeschalteter Skill bleibt draussen", "aus" not in fehlt, fehlt)
check("ohne Zustand gilt die Manifest-Vorgabe (an)", "vorgabe_an" in fehlt, fehlt)
check("…und (aus)", "vorgabe_aus" not in fehlt, fehlt)
check("vollstaendiger Skill steht nicht in der Liste",
      "komplett" not in fehlt, fehlt)

print("\n── 3. Hilfsprozess startet neu, wenn Pakete dazukommen")


class Proc:
    returncode = None


def helfer_bauen(faehig):
    h = AN._Helfer()
    h.starts = 0

    async def starten():
        h.starts += 1
        h._pakete = AN._pakete_stand()
        h._proc = Proc()
        h._faehig = dict(faehig)

    async def beenden():
        h._proc = None

    h._starten = starten
    h.beenden = beenden
    return h


paket = {"stand": (False, False, False, False)}
AN._pakete_stand = lambda: paket["stand"]


async def ablauf():
    # a) Pakete fehlen beim Start, kommen dazu -> Neustart
    h = helfer_bauen({"personen": False, "gesichter": False})
    await h.faehigkeiten()
    check("Positivkontrolle: erster Aufruf startet den Hilfsprozess", h.starts == 1, h.starts)
    await h.faehigkeiten()
    check("unveraenderter Stand: KEIN Neustart (sonst jede Anfrage ein Start)", h.starts == 1,
          h.starts)
    paket["stand"] = (True, True, True, True)
    await h.faehigkeiten()
    check("Pakete dazugekommen: Hilfsprozess neu gestartet", h.starts == 2, h.starts)
    # b) voll faehig -> nie Neustart, auch bei Standwechsel
    paket["stand"] = (True, True, True, True)
    h2 = helfer_bauen({"personen": True, "gesichter": True})
    await h2.faehigkeiten()
    paket["stand"] = (True, True, True, False)
    await h2.faehigkeiten()
    check("voll faehiger Hilfsprozess bleibt stehen", h2.starts == 1, h2.starts)


asyncio.run(ablauf())

print("\n── 4. Regel: Skill-Pakete nur ohne angesetzten Neustart")
baum = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))
haken = [n for n in ast.walk(baum)
         if isinstance(n, ast.AsyncFunctionDef) and n.name == "startup_abhaengigkeiten"]
check("Positivkontrolle: Start-Haken gefunden", len(haken) == 1, len(haken))
if len(haken) != 1:
    abbruch("ohne den Haken ist die Regel nicht pruefbar")


def ruft(knoten, name):
    return any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == name
               for c in ast.walk(knoten))


treffer = []
for n in ast.walk(haken[0]):
    if isinstance(n, ast.If) and any(ruft(b, "restart_service_delayed") for b in n.body):
        treffer.append(n)
check("Positivkontrolle: Neustart-Zweig gefunden", len(treffer) == 1, len(treffer))
if treffer:
    t = treffer[0]
    im_else = any(isinstance(a, ast.Await) and ruft(a, "_skill_pakete")
                  for b in t.orelse for a in ast.walk(b))
    im_body = any(ruft(b, "_skill_pakete") for b in t.body)
    check("_skill_pakete wird im ELSE-Zweig erwartet (await)", im_else)
    check("…und nicht im Neustart-Zweig", not im_body)
aufrufe_gesamt = sum(1 for c in ast.walk(haken[0]) if isinstance(c, ast.Call)
                     and isinstance(c.func, ast.Name) and c.func.id == "_skill_pakete")
check("…genau EIN Aufruf im Haken", aufrufe_gesamt == 1, aufrufe_gesamt)

print("\n" + "=" * 60)
print(f"Ergebnis: {OK} OK, {FAIL} FAIL")
print("=" * 60)
sys.exit(0 if FAIL == 0 else 1)
