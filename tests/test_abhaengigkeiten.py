#!/usr/bin/env python3
"""Waechter: backend/abhaengigkeiten.py – Python-Pakete eines Servers nachziehen (BSI M6).

Geprueft wird die ENTSCHEIDUNG, nicht pip selbst (die echte Installation ist auf
DEV und ECHT gemessen, 2026-10-06):

  1. Einordnung je Anforderung: fehlt / unter der Grenze / UEBER der Grenze / ok.
     Ein Paket ueber seiner Grenze (requirements pinnt google-genai==1.5.0,
     installiert ist 1.72.0) wird NIE herabgestuft.
  2. Constraints: Grenzen aus requirements.txt; ueber-Grenze-Pakete auf den
     Ist-Stand genagelt; jedes andere installierte Paket "nicht darunter"
     (DEV: eine Hebung stufte bcrypt 5.0.0 -> 4.3.0 zurueck); lokale Versionen
     (torch +cpu) exakt.
  3. Ziele aus Schwachstellen: kleinste behebende Version je Fund, groesste je
     Paket; ausgenommene Funde, Funde ohne Behebung und torch/pip/setuptools
     werden nicht gehoben.
  4. OSV-Auswertung: nur ECOSYSTEM-Bereiche des richtigen Pakets, nur Versionen
     ueber der installierten, keine Vorabversionen.
  5. Ausnahmeliste: abgelaufene Eintraege gelten nicht mehr.
  6. Ablauf mit Attrappen (pip/OSV): Hebung, Import-Test scheitert -> geaenderte
     Pakete zurueck; ohne Installation-Schalter wird nichts installiert.

``backend.config`` wird nicht importiert. Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import datetime as dt
import sys
import tempfile
from pathlib import Path

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


try:
    from backend import abhaengigkeiten as A
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: Modul nicht ladbar: {e}")
    sys.exit(2)

SK = Path(tempfile.mkdtemp(prefix="jv_abh_"))
REQ = SK / "requirements.txt"
REQ.write_text("""# Kommentar
google-genai==1.5.0
numpy<2.1
mcp>=1.28.1,<2   # Grenze
python-dotenv>=1.2.2
uvicorn[standard]==0.34.0
fehltnoch>=1.0
""")
A.REQUIREMENTS = REQ

print("\n── 1. Einordnung")
inst = {"google-genai": "1.72.0", "numpy": "2.0.2", "mcp": "1.25.0", "python-dotenv": "1.2.4",
        "uvicorn": "0.34.0", "bcrypt": "5.0.0", "torch": "2.10.0+cpu", "pyjwt": "2.12.1"}
e = A.einordnen(inst)
namen = {k: sorted(r.name for r in v) for k, v in e.items()}
check("Positivkontrolle: 6 Anforderungen gelesen (Kommentar/Extras verkraftet)",
      sum(len(v) for v in e.values()) == 6, namen)
check("ueber der Grenze: google-genai (1.72.0 > ==1.5.0)", namen["zu_neu"] == ["google-genai"], namen)
check("unter der Grenze: mcp", namen["zu_alt"] == ["mcp"], namen)
check("fehlt: fehltnoch", namen["fehlt"] == ["fehltnoch"], namen)
check("ok: numpy, python-dotenv, uvicorn (Extras egal)",
      namen["ok"] == ["numpy", "python-dotenv", "uvicorn"], namen)
un = A.unerfuellt(inst)
check("nachzuinstallieren: nur fehlt + zu_alt – NICHT google-genai",
      len(un) == 2 and not any("google" in u for u in un), un)

print("\n── 2. Constraints")
c = A._constraints(inst).splitlines()
check("Grenzen aus requirements.txt (ohne Extras)",
      "numpy<2.1" in c and any(z.startswith("mcp") and "<2" in z for z in c) and "uvicorn==0.34.0" in c, c)
check("ueber-Grenze-Paket auf Ist-Stand genagelt (kein Herabstufen)",
      "google-genai==1.72.0" in c and "google-genai==1.5.0" not in c, c)
check("andere installierte Pakete: nicht unter dem Ist-Stand (bcrypt-Fall)",
      "bcrypt>=5.0.0" in c and "pyjwt>=2.12.1" in c, c)
check("lokale Version exakt (torch +cpu)", "torch==2.10.0+cpu" in c, c)
check("kein Eintrag doppelt", len(c) == len(set(z.split("<")[0].split(">")[0].split("=")[0] for z in c)), c)

print("\n── 3. Ziele aus Funden")
funde = [
    {"paket": "pyjwt", "version": "2.12.1", "id": "A", "behoben_in": "2.13.0", "ausgenommen": False},
    {"paket": "pyjwt", "version": "2.12.1", "id": "B", "behoben_in": "2.15.0", "ausgenommen": False},
    {"paket": "transformers", "version": "4.57.6", "id": "C", "behoben_in": "5.3.0", "ausgenommen": True},
    {"paket": "chromadb", "version": "0.6.3", "id": "D", "behoben_in": None, "ausgenommen": False},
    {"paket": "torch", "version": "2.10.0+cpu", "id": "E", "behoben_in": "2.13.0", "ausgenommen": False},
    {"paket": "pip", "version": "25.1", "id": "F", "behoben_in": "26.1", "ausgenommen": False},
]
z = A._ziele(funde)
check("je Paket die groesste der kleinsten Behebungen (pyjwt 2.15.0)", z.get("pyjwt") == "2.15.0", z)
check("ausgenommen / ohne Behebung / torch / pip werden nicht gehoben", set(z) == {"pyjwt"}, z)

print("\n── 4. OSV-Auswertung")
Version = A.Version  # dieselbe Klasse wie im Modul (packaging oder pip._vendor)
vuln = {"affected": [
    {"package": {"name": "PyJWT"}, "ranges": [
        {"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "2.13.0"}]},
        {"type": "ECOSYSTEM", "events": [{"introduced": "2.14.0"}, {"fixed": "2.14.5"}]},
        {"type": "GIT", "events": [{"fixed": "abcdef"}]}]},
    {"package": {"name": "anderes"}, "ranges": [{"type": "ECOSYSTEM", "events": [{"fixed": "2.12.5"}]}]},
    {"package": {"name": "pyjwt"}, "ranges": [{"type": "ECOSYSTEM", "events": [{"fixed": "3.0.0rc1"}]}]},
]}
fv = A._behebende_version(vuln, "pyjwt", Version("2.12.1"))
check("kleinste behebende Version ueber der installierten (2.13.0)", str(fv) == "2.13.0", fv)
check("…fremdes Paket, GIT-Bereich, Vorabversion ignoriert",
      str(A._behebende_version(vuln, "pyjwt", Version("2.13.0"))) == "2.14.5")
check("…nichts mehr ueber der hoechsten Behebung -> None",
      A._behebende_version(vuln, "pyjwt", Version("2.14.5")) is None)

print("\n── 5. Ausnahmeliste")
AL = SK / "ausnahmen.txt"
AL.write_text("PYSEC-1  2026-12-31  # gilt\nPYSEC-2  2026-01-01  # abgelaufen\nPYSEC-3  # ohne Datum\n")
A.AUSNAHMEN = AL
a = A.ausnahmen(dt.date(2026, 6, 1))
check("gueltig nur der nicht abgelaufene Eintrag mit Datum", a == {"PYSEC-1"}, a)
A.AUSNAHMEN = ROOT / "deploy" / "security" / "pip_audit_ausnahmen.txt"
check("echte Liste: mindestens eine gueltige Ausnahme", len(A.ausnahmen(dt.date(2026, 10, 6))) > 0)

print("\n── 6. Ablauf mit Attrappen")
A.ZUSTAND = SK / "zustand.json"
zustand = {"inst": {"pyjwt": "2.12.1", "bcrypt": "5.0.0", "numpy": "2.0.2", "mcp": "1.28.1",
                    "python-dotenv": "1.2.2", "uvicorn": "0.34.0", "google-genai": "1.72.0",
                    "fehltnoch": "1.0"}}
aufrufe = []


class R:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def pip_attrappe(*args, timeout=900):
    aufrufe.append(args)
    if args[0] == "install" and "--no-deps" not in args:
        for a_ in args:
            if a_.startswith("pyjwt=="):
                zustand["inst"]["pyjwt"] = a_.split("==")[1]
    if args[0] == "install" and "--no-deps" in args:
        for a_ in args[2:]:
            n, v = a_.split("==")
            zustand["inst"][n] = v
    return R(0)


A.installiert = lambda: dict(zustand["inst"])
A._pip = pip_attrappe
A.schwachstellen = lambda inst, erlaubt=None: (
    [{"paket": "pyjwt", "version": inst["pyjwt"], "id": "X", "aliase": ["X"],
      "behoben_in": "2.15.0", "ausgenommen": False}] if inst["pyjwt"] != "2.15.0" else [])
A._import_test = lambda: (True, "")
REQ.write_text("numpy<2.1\nmcp>=1.28.1,<2\n")
erg = A.abgleichen(installieren=True)
inst_aufruf = [x for x in aufrufe if x[0] == "install"]
check("Hebung installiert mit Constraints (-c) und pyjwt==2.15.0",
      inst_aufruf and inst_aufruf[0][1] == "-c" and "pyjwt==2.15.0" in inst_aufruf[0], inst_aufruf)
check("…nie ein blankes -r requirements.txt", not any("-r" in x for x in aufrufe), aufrufe)
check("geaendert gemeldet", erg.get("geaendert") == ["pyjwt 2.12.1 -> 2.15.0"], erg.get("geaendert"))
check("danach nichts offen, ok", erg.get("ok") and not erg.get("offen"), erg)
check("Zustand geschrieben", A.zustand().get("geaendert") == ["pyjwt 2.12.1 -> 2.15.0"])

zustand["inst"]["pyjwt"] = "2.12.1"
aufrufe.clear()
A._import_test = lambda: (False, "jwt: ImportError")
erg = A.abgleichen(installieren=True)
check("Import-Test scheitert -> geaenderte Pakete zurueck (--no-deps pyjwt==2.12.1)",
      any(x[:2] == ("install", "--no-deps") and "pyjwt==2.12.1" in x for x in aufrufe)
      and zustand["inst"]["pyjwt"] == "2.12.1", aufrufe)
check("…als Fehler gemeldet, Liste zurueckgesetzt", not erg.get("ok") and erg.get("zurueckgesetzt")
      and "Import-Test" in erg.get("fehler", ""), erg)

aufrufe.clear()
A._import_test = lambda: (True, "")
erg = A.abgleichen(installieren=False)
check("nur pruefen: KEIN pip install, Fund als offen gemeldet",
      not any(x[0] == "install" for x in aufrufe) and erg.get("offen"), (aufrufe, erg.get("offen")))

print("\n── 7. Lock-Modus (JARVIS_ABH_LOCK=1)")
import os  # noqa: E402

echte = A.lock_versionen((ROOT / "requirements.lock").read_text(encoding="utf-8"))
check("Positivkontrolle: echte requirements.lock gelesen (>= 100 Pakete, torch +cpu)",
      len(echte) >= 100 and echte.get("torch", "").endswith("+cpu"), (len(echte), echte.get("torch")))

LK = SK / "requirements.lock"
soll = {f"paket{i:02d}": "1.0" for i in range(20)}
soll.update({"google-genai": "1.5.0", "torch": "2.10.0+cpu", "pyjwt": "2.12.1", "numpy": "2.0.2"})
LK.write_text("# kopf\n" + "".join(
    f"{n}=={v} \\\n    --hash=sha256:{'a' * 64}\n    # via x\n" for n, v in soll.items()))
check("lock_versionen liest Eintraege samt Fortsetzungszeilen und +cpu",
      A.lock_versionen(LK.read_text()) == soll, A.lock_versionen(LK.read_text()))

ist = dict(soll, **{"google-genai": "1.72.0", "torch": "2.12.0+cpu", "dlib": "20.0.0"})
del ist["paket00"]
ist["paket01"] = "0.9"
ab = {n: (i, s) for n, i, s in A.lock_abweichungen(ist, soll)}
check("Abweichungen: fehlt, aelter UND neuer (auch torch) – kein Herabstufungsverbot",
      ab == {"paket00": (None, "1.0"), "paket01": ("0.9", "1.0"),
             "google-genai": ("1.72.0", "1.5.0"), "torch": ("2.12.0+cpu", "2.10.0+cpu")}, ab)
check("…Paket ausserhalb der Lock (dlib, Skill) zaehlt nicht", "dlib" not in ab, ab)

A.LOCK = LK
os.environ.pop("JARVIS_ABH_LOCK", None)
check("ohne Schalter KEIN Lock-Modus (Vorgabe aus – ECHT holt master selbst)", not A.lock_modus())
os.environ["JARVIS_ABH_LOCK"] = "1"
check("mit Schalter und Lock-Datei: Lock-Modus", A.lock_modus())
A.LOCK = SK / "gibtsnicht.lock"
check("mit Schalter, aber ohne Lock-Datei: kein Lock-Modus", not A.lock_modus())
A.LOCK = LK

zustand["inst"] = dict(ist)
aufrufe.clear()


def pip_lock(*args, timeout=900):
    aufrufe.append(args)
    if args[0] == "install" and "-r" in args:
        zustand["inst"].update(soll)          # pip bringt alles auf den Lock-Stand
    if args[0] == "install" and "--no-deps" in args:
        for a_ in args[2:]:
            if "==" in a_:
                n, v = a_.split("==")
                zustand["inst"][n] = v
    return R(0)


A._pip = pip_lock
A._import_test = lambda: (True, "")
A.schwachstellen = lambda inst, erlaubt=None: (
    [{"paket": "pyjwt", "version": inst["pyjwt"], "id": "X", "aliase": ["X"],
      "behoben_in": "2.15.0", "ausgenommen": False}])
A.ZUSTAND = SK / "zustand_lock.json"
erg = A.abgleichen(installieren=True)
inst_lock = [x for x in aufrufe if x[0] == "install"]
check("genau EIN pip install, aus der Lock mit --require-hashes und CPU-Index",
      len(inst_lock) == 1 and "--require-hashes" in inst_lock[0] and "-r" in inst_lock[0]
      and str(LK) in inst_lock[0] and A.TORCH_INDEX in inst_lock[0], inst_lock)
check("…ohne Constraints (-c) und ohne Einzel-Hebung des Fundes (pyjwt==2.15.0)",
      not any("-c" in x or "pyjwt==2.15.0" in x for x in inst_lock), inst_lock)
check("geaendert: Herabstufung google-genai und torch gemeldet",
      "google-genai 1.72.0 -> 1.5.0" in erg.get("geaendert", [])
      and "torch 2.12.0+cpu -> 2.10.0+cpu" in erg.get("geaendert", []), erg.get("geaendert"))
check("Skill-Paket ausserhalb der Lock bleibt (dlib)",
      zustand["inst"].get("dlib") == "20.0.0" and not any(x[0] == "uninstall" for x in aufrufe), aufrufe)
check("Fund nur GEMELDET, mit Weg ueber die Lock",
      any(o.get("paket") == "pyjwt" and "lock_erneuern" in o.get("weg", "") for o in erg.get("offen", [])),
      erg.get("offen"))
check("danach keine Lock-Abweichung, Modus 'lock'",
      erg.get("lock_abweichungen_danach") == [] and erg.get("modus") == "lock", erg)
check("Zustand im Lock-Modus GESCHRIEBEN (kein Ruecksprung vor _speichern)",
      A.zustand().get("modus") == "lock" and A.zustand().get("geaendert") == erg.get("geaendert"),
      A.zustand())

zustand["inst"] = dict(ist)
aufrufe.clear()
erg = A.abgleichen(installieren=False)
check("nur pruefen: KEIN pip install, Abweichungen gemeldet",
      not any(x[0] == "install" for x in aufrufe) and len(erg.get("lock_abweichungen", [])) == 4,
      (aufrufe, erg.get("lock_abweichungen")))

zustand["inst"] = dict(ist)
aufrufe.clear()
A._import_test = lambda: (False, "torch: ImportError")
erg = A.abgleichen(installieren=True)
rueck = [x for x in aufrufe if x[:2] == ("install", "--no-deps")]
check("Import-Test scheitert -> Ruecknahme INKLUSIVE torch, vom CPU-Index",
      rueck and "torch==2.12.0+cpu" in rueck[0] and A.TORCH_INDEX in rueck[0]
      and zustand["inst"].get("torch") == "2.12.0+cpu", rueck)
check("…und google-genai zurueck auf 1.72.0", zustand["inst"].get("google-genai") == "1.72.0",
      zustand["inst"].get("google-genai"))
check("…als Fehler gemeldet", not erg.get("ok") and "Import-Test" in erg.get("fehler", ""), erg)
os.environ.pop("JARVIS_ABH_LOCK", None)

print("\n── 8. Import-Test benennt einen Absturz (SIGILL auf DEV, faiss 1.14.2)")
import importlib  # noqa: E402
A = importlib.reload(A)          # echte Funktionen statt der Attrappen von oben
(SK / "jv_absturz.py").write_text("import os, signal\nos.kill(os.getpid(), signal.SIGABRT)\n")
A.IMPORT_TEST = ("json", "jv_absturz", "csv")
A.PYTHON = sys.executable
_pp = os.environ.get("PYTHONPATH")
os.environ["PYTHONPATH"] = str(SK)
try:
    ok_, txt = A._import_test()
finally:
    if _pp is None:
        os.environ.pop("PYTHONPATH", None)
    else:
        os.environ["PYTHONPATH"] = _pp
check("Absturz per Signal: gescheitert UND das Modul benannt (nicht leer)",
      not ok_ and "jv_absturz" in txt and "Signal" in txt, txt)
A.IMPORT_TEST = ("json", "csv")
ok_, txt = A._import_test()
check("Gegenkontrolle: ohne Absturz besteht der Import-Test, keine Ansage-Zeilen im Text",
      ok_ and "@" not in txt, (ok_, txt))

print("\n" + "=" * 60)
print(f"Ergebnis: {OK} OK, {FAIL} FAIL")
print("=" * 60)
sys.exit(1 if FAIL else 0)
