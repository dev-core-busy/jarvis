#!/usr/bin/env python3
"""Waechter: Nebenprozesse und die Hash-Kette des Sicherheitsprotokolls (BSI M2).

WARUM (BSI-Abgleich 2026-10-26): auf DEV und ECHT war die Kette gebrochen. Am
21.10. lief ``python -m backend.abhaengigkeiten`` von Hand – ein Prozess ohne
``schluessel_setzen`` – und haengte Zeilen OHNE ``mac`` an eine Kette, die
laengst Pruefmerkmale trug. Dazu meldete ``python -m backend.sicherheits_log
pruefen`` seit Einfuehrung des Merkmals bei JEDER Zeile "Schluessel fehlt":
der Befehl hat nie einen Schluessel gesetzt, und die Live-Probe M1/M2 war
damit dauerhaft rot, ohne etwas ueber die Kette zu sagen.

Geprueft wird in ECHTEN Nebenprozessen (eigener Modulzustand, wie im Betrieb),
im Sandkasten (``DATEI`` ist relativ zum Arbeitsverzeichnis):
  1. Nebenprozess ohne Schluessel schreibt NICHT in eine Kette mit Merkmal –
     und meldet es; eine Kette ohne Merkmal (frische Installation) bleibt
     beschreibbar.
  2. Nebenprozess mit Schluessel in der Ablage (Klartext und verpackt mit
     Hauptschluessel) schreibt pruefbare Zeilen.
  3. Hat ein anderer Prozess angehaengt, verankert der Dienst neu (kein
     "Kette unterbrochen").
  4. ``secret_key.nur_lesen`` erzeugt nie, schreibt nie, liefert nie Ersatz.
  5. ``pruefen`` als Befehl: ohne Schluessel Exit 2 statt Scheinbrueche, mit
     Schluessel ein echtes Ergebnis.

Exit 0 = gruen, 1 = Fehler, 2 = konnte nicht laufen.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

OK = FAIL = 0


def check(name, bed, info=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + str(info)[:300] + "]") if info != "" else ""))


def abbruch(grund):
    print("ABBRUCH (konnte nicht laufen): " + grund)
    sys.exit(2)


TMP = Path(tempfile.mkdtemp(prefix="sl_kette_"))
# Nebenprozesse mit dem Interpreter des Dienstes (venv): nur dort gibt es
# python-dotenv, und ohne es ignoriert auch config.py die .env.
PY = str(ROOT / "venv" / "bin" / "python") if (ROOT / "venv" / "bin" / "python").exists() \
    else sys.executable
NICHT_GEPRUEFT = []
FREMD_HAUPT = TMP / "kein-hauptschluessel.key"     # existiert nie


def umgebung(**extra):
    """Umgebung eines Nebenprozesses: kein SECRET_KEY, kein Credential, kein
    Hauptschluessel – ausser ein Fall setzt ihn ausdruecklich."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("SECRET_KEY", "CREDENTIALS_DIRECTORY", "JARVIS_GEHEIMNIS_DATEI")}
    env.update({"PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1",
                "JARVIS_GEHEIMNIS_DATEI": str(FREMD_HAUPT)})
    env.update(extra)
    return env


def neben(wurzel: Path, code: str, **env):
    """Python-Code als eigener Prozess mit Arbeitsverzeichnis ``wurzel``."""
    r = subprocess.run([PY, "-c", code], cwd=str(wurzel), capture_output=True,
                       text=True, timeout=120, env=umgebung(**env))
    return r


def sandkasten(name: str) -> Path:
    w = TMP / name
    (w / "data" / "logs").mkdir(parents=True)
    return w


def zeilen(w: Path) -> list:
    p = w / "data" / "logs" / "sicherheit.jsonl"
    return [json.loads(z) for z in p.read_text().splitlines() if z.strip()] if p.exists() else []


SCHREIBE = ("from backend import sicherheits_log as sl\n"
            "import json\n"
            "sl.ereignis('abhaengigkeiten', ergebnis='geaendert')\n"
            "print('ZUSTAND', json.dumps(sl.zustand()['fehler']))\n"
            "print('DATEI', sl.DATEI.resolve())\n")

DIENST = ("from backend import sicherheits_log as sl\n"
          "sl.schluessel_setzen(%r)\n"
          "for i in range(%d): sl.ereignis('dienst_start', ergebnis=str(i))\n")

PRUEFE = ("from backend import sicherheits_log as sl\n"
          "import json\n"
          "sl.schluessel_setzen(%r)\n"
          "print('KETTE', json.dumps(sl.pruefen()))\n")


def kette(w: Path, geheimnis: str) -> dict:
    r = neben(w, PRUEFE % geheimnis)
    for z in r.stdout.splitlines():
        if z.startswith("KETTE "):
            return json.loads(z[6:])
    return {"ok": None, "fehler": (r.stdout + r.stderr)[-300:]}


def ausfuehren(w: Path, code: str, **env) -> subprocess.CompletedProcess:
    r = neben(w, code, **env)
    if r.returncode != 0:
        abbruch("Nebenprozess scheiterte: " + (r.stdout + r.stderr)[-400:])
    return r


# ═════════════════════════════════════════════════════════════════════════════
print("[0] Positivkontrollen des Messaufbaus")
w0 = sandkasten("p0")
r = ausfuehren(w0, DIENST % ("geheim-dienst", 2))
z = zeilen(w0)
if len(z) != 2 or not all(e.get("mac") for e in z):
    abbruch("Dienst-Nachbau schreibt keine Zeilen mit Merkmal: %r" % z)
check("Dienst-Nachbau schreibt Zeilen mit Merkmal (im Sandkasten)", True)
k = kette(w0, "geheim-dienst")
if k.get("ok") is not True:
    abbruch("Kette des Dienst-Nachbaus prueft nicht gruen: %r" % k)
check("pruefen() mit dem Schluessel des Dienstes: gruen", True)
check("mit FALSCHEM Schluessel erkennt pruefen() die Zeilen als veraendert",
      kette(w0, "anderer").get("ok") is False)
r = ausfuehren(w0, SCHREIBE)
datei = next((x[6:] for x in r.stdout.splitlines() if x.startswith("DATEI ")), "")
if not datei.startswith(str(TMP)):
    abbruch("Nebenprozess schreibt nicht in den Sandkasten: %r" % datei)
check("Nebenprozess schreibt in den Sandkasten", True)

# ═════════════════════════════════════════════════════════════════════════════
print("\n[1] Nebenprozess OHNE Schluessel")
w1 = sandkasten("ohne")
ausfuehren(w1, DIENST % ("geheim-1", 3))
vorher = (w1 / "data" / "logs" / "sicherheit.jsonl").read_bytes()
r = ausfuehren(w1, SCHREIBE)
nachher = (w1 / "data" / "logs" / "sicherheit.jsonl").read_bytes()
check("haengt an eine Kette MIT Merkmal nichts an (Datei byte-gleich)", vorher == nachher,
      "%d -> %d Byte" % (len(vorher), len(nachher)))
zst = next((json.loads(x[8:]) for x in r.stdout.splitlines() if x.startswith("ZUSTAND ")), {})
check("zaehlt den Fall (zustand: ohne_schluessel = 1)", zst.get("ohne_schluessel") == 1, zst)
check("sagt es im Journal und nennt den Weg (als_dienst.sh)",
      "nur im Journal" in r.stdout and "als_dienst.sh" in r.stdout, r.stdout[-300:])
check("die Kette bleibt gruen", kette(w1, "geheim-1").get("ok") is True)

w1b = sandkasten("frisch")
ausfuehren(w1b, SCHREIBE)
ausfuehren(w1b, SCHREIBE)
z = zeilen(w1b)
check("Kette OHNE Merkmal (frische Installation): weiter beschreibbar",
      len(z) == 2 and not any(e.get("mac") for e in z), z)
check("…und pruefbar", kette(w1b, "").get("ok") is True)

# ═════════════════════════════════════════════════════════════════════════════
print("\n[2] Nebenprozess MIT Schluessel in der Ablage")
w2 = sandkasten("klartext")
(w2 / "data" / ".secret_key").write_text("geheim-2\n")
ausfuehren(w2, DIENST % ("geheim-2", 2))
ausfuehren(w2, SCHREIBE)
z = zeilen(w2)
check("Klartext-Ablage: Zeile mit Merkmal angehaengt", len(z) == 3 and z[-1].get("mac") == 1, z[-1:])
check("Klartext-Ablage: Kette gruen", kette(w2, "geheim-2").get("ok") is True, kette(w2, "geheim-2"))

if neben(TMP, "import dotenv").returncode != 0:
    NICHT_GEPRUEFT.append(".env-Vorrang (python-dotenv fehlt im Interpreter %s)" % PY)
else:
    w2e = sandkasten("env")
    (w2e / ".env").write_text("SECRET_KEY=geheim-env\n")
    (w2e / "data" / ".secret_key").write_text("ganz-anderer-wert\n")
    ausfuehren(w2e, DIENST % ("geheim-env", 1))
    ausfuehren(w2e, SCHREIBE)
    check(".env neben data/ sticht data/.secret_key (wie config.py)",
          kette(w2e, "geheim-env").get("ok") is True and len(zeilen(w2e)) == 2,
          kette(w2e, "geheim-env"))

try:
    from cryptography.fernet import Fernet
except Exception as e:  # noqa: BLE001
    abbruch("cryptography fehlt: %s" % e)
w3 = sandkasten("verpackt")
haupt = Fernet.generate_key()
(w3 / "haupt.key").write_bytes(haupt)
(w3 / "data" / ".secret_key").write_text(
    "JGK1:" + Fernet(haupt).encrypt(b"geheim-3").decode("ascii"))
ausfuehren(w3, DIENST % ("geheim-3", 2))
vorher = (w3 / "data" / "logs" / "sicherheit.jsonl").read_bytes()
ausfuehren(w3, SCHREIBE)
check("verpackt, OHNE Hauptschluessel: nichts angehaengt (kein fluechtiger Ersatz)",
      (w3 / "data" / "logs" / "sicherheit.jsonl").read_bytes() == vorher)
ausfuehren(w3, SCHREIBE, JARVIS_GEHEIMNIS_DATEI=str(w3 / "haupt.key"))
z = zeilen(w3)
check("verpackt, MIT Hauptschluessel (wie als_dienst.sh): Zeile mit Merkmal",
      len(z) == 3 and z[-1].get("mac") == 1, len(z))
check("…und die Kette ist gruen", kette(w3, "geheim-3").get("ok") is True, kette(w3, "geheim-3"))

# ═════════════════════════════════════════════════════════════════════════════
print("\n[3] Fremder Anhang waehrend der Dienst laeuft")
w4 = sandkasten("fremd")
(w4 / "data" / ".secret_key").write_text("geheim-4\n")
r = ausfuehren(w4, "import subprocess, sys\n"
               "from backend import sicherheits_log as sl\n"
               "sl.schluessel_setzen('geheim-4')\n"
               "sl.ereignis('dienst_start')\n"
               "subprocess.run([sys.executable, '-c', %r], check=True)\n"
               "sl.ereignis('anmeldung')\n" % SCHREIBE)
z = zeilen(w4)
check("drei Zeilen (Dienst, Nebenprozess, Dienst)", len(z) == 3, len(z))
check("die Dienstzeile nach dem fremden Anhang knuepft an DESSEN Hash an",
      len(z) == 3 and z[2].get("prev") == z[1].get("hash"))
check("Kette gruen (kein 'Kette unterbrochen')", kette(w4, "geheim-4").get("ok") is True,
      kette(w4, "geheim-4"))

# ═════════════════════════════════════════════════════════════════════════════
print("\n[4] secret_key.nur_lesen: liest, erzeugt nie")
w5 = sandkasten("nurlesen")
NL = ("from pathlib import Path\nfrom backend import secret_key as s\n"
      "print('WERT', repr(s.nur_lesen(%r, Path('data/.secret_key'))))\n")


def nur_lesen(env_wert, **env):
    r = ausfuehren(w5, NL % env_wert, **env)
    return next((x[5:] for x in r.stdout.splitlines() if x.startswith("WERT ")), "?")


check("ohne Datei: None", nur_lesen("") == "None")
check("…und es entsteht KEINE Datei", not (w5 / "data" / ".secret_key").exists())
(w5 / "data" / ".secret_key").write_text("change-me-to-a-random-string")
check("Platzhalter in der Datei: None", nur_lesen("") == "None")
check("…Datei unveraendert", (w5 / "data" / ".secret_key").read_text() == "change-me-to-a-random-string")
check("gesetzter Umgebungswert gewinnt", nur_lesen("aus-env") == "'aus-env'")
(w5 / "data" / ".secret_key").write_text("JGK1:kaputt")
check("verpackt ohne Hauptschluessel: None", nur_lesen("") == "None")
(w5 / "haupt.key").write_bytes(haupt)
check("verpackt mit FREMDEM Hauptschluessel (passt nicht): None",
      nur_lesen("", JARVIS_GEHEIMNIS_DATEI=str(w5 / "haupt.key")) == "None")

# ═════════════════════════════════════════════════════════════════════════════
print("\n[5] python -m backend.sicherheits_log pruefen")
CLI = [PY, "-m", "backend.sicherheits_log", "pruefen"]
r = subprocess.run(CLI, cwd=str(w1), capture_output=True, text=True, timeout=120, env=umgebung())
check("ohne Schluessel bei Kette mit Merkmal: Exit 2", r.returncode == 2, (r.returncode, r.stdout[-200:]))
check("…mit Grund und Weg, ohne Scheinbrueche",
      "als_dienst.sh" in r.stdout and "brueche" not in r.stdout, r.stdout[-200:])
r = subprocess.run(CLI, cwd=str(w2), capture_output=True, text=True, timeout=120, env=umgebung())
try:
    erg = json.loads(r.stdout)
except Exception:  # noqa: BLE001
    erg = {}
check("mit Schluessel in der Ablage: Exit 0 und ok", r.returncode == 0 and erg.get("ok") is True,
      (r.returncode, r.stdout[-200:]))
r = subprocess.run(CLI, cwd=str(w1b), capture_output=True, text=True, timeout=120, env=umgebung())
check("Kette ganz ohne Merkmal: pruefbar ohne Schluessel (Exit 0)", r.returncode == 0,
      (r.returncode, r.stdout[-200:]))

shutil.rmtree(TMP, ignore_errors=True)
print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (OK, FAIL))
for n in NICHT_GEPRUEFT:
    print("NICHT GEPRUEFT: " + n)
sys.exit(1 if FAIL else (2 if NICHT_GEPRUEFT else 0))
