#!/usr/bin/env python3
"""Waechter: das Docker-Kennwort liegt gesalzen und teuer gehasht in auth_state.json.

DER BEFUND (2026-10-29): ``data/auth_state.json`` trug das Web-Kennwort im
Docker-Modus als UNGESALZENES SHA-256. Wer die Datei las (Sicherung, kopiertes
Volume ``jarvis-data``), rechnete ein uebliches Kennwort per Woerterbuch in
Sekunden zurueck; gleiche Kennwoerter hatten gleiche Hashes.

Gemessen:
A. ``standard_zugang.kennwort_hash/kennwort_pruefen`` AUSGEFUEHRT: Salz, richtige
   und falsche Kennwoerter, Altwert (SHA-256) gilt und wird als veraltet
   gemeldet, unbekannte Formen fail-closed, ueberzogene Parameter werden
   abgelehnt, OHNE dass gerechnet wird (eine Attrappe zaehlt die Aufrufe).
B. ``main.py`` am Syntaxbaum: Anmeldung prueft ueber ``kennwort_pruefen`` und
   schreibt einen Altwert nach gelungener Anmeldung neu; der Kennwortwechsel
   speichert ueber ``kennwort_hash``; in beiden Funktionen kein ``sha256``.

JARVIS_TEST_STANDARD_ZUGANG / JARVIS_TEST_MAIN zeigen fuer die Gegenprobe auf
veraenderte Kopien. Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
import ast
import hashlib
import importlib.util
import os
import re
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
SZ_PFAD = Path(os.environ.get("JARVIS_TEST_STANDARD_ZUGANG") or WURZEL / "backend" / "standard_zugang.py")
MAIN_PFAD = Path(os.environ.get("JARVIS_TEST_MAIN") or WURZEL / "backend" / "main.py")

_ok = _fail = 0


def check(name, bed, info=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print(f"  OK   {name}")
    else:
        _fail += 1
        print(f"  FAIL {name}" + (f"  [{info}]" if info != "" else ""))


def abbruch(grund):
    print(f"ABBRUCH: {grund}")
    sys.exit(2)


# ── Positivkontrollen ───────────────────────────────────────────────────────
try:
    spec = importlib.util.spec_from_file_location("standard_zugang_probe", SZ_PFAD)
    sz = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sz)
except Exception as e:  # noqa: BLE001 – jeder Ladefehler heisst "konnte nicht laufen"
    abbruch(f"{SZ_PFAD} nicht ladbar: {e}")
if not (callable(getattr(sz, "kennwort_hash", None)) and callable(getattr(sz, "kennwort_pruefen", None))):
    abbruch("kennwort_hash/kennwort_pruefen fehlen in standard_zugang")
try:
    BAUM = ast.parse(MAIN_PFAD.read_text(encoding="utf-8"))
except (OSError, SyntaxError) as e:
    abbruch(f"{MAIN_PFAD} nicht lesbar: {e}")
FUNK = {n.name: n for n in ast.walk(BAUM) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
for name in ("authenticate_linux_user", "change_password"):
    if name not in FUNK:
        abbruch(f"Funktion {name} nicht in main.py")

PW = "Probe-Kennwort-7a"
print("[A] Hash und Pruefung (ausgefuehrt)")
h1 = sz.kennwort_hash(PW)
h2 = sz.kennwort_hash(PW)
form = re.fullmatch(r"scrypt\$(\d+)\$(\d+)\$(\d+)\$([A-Za-z0-9+/=]+)\$([A-Za-z0-9+/=]+)", h1 or "")
check("Speicherform scrypt$N$r$p$salz$hash", form is not None, h1[:40])
check("Kosten: N >= 2^14 und r >= 8",
      form is not None and int(form.group(1)) >= 2 ** 14 and int(form.group(2)) >= 8,
      form.groups()[:3] if form else None)
check("Salz: zwei Hashes desselben Kennworts unterscheiden sich", h1 != h2)
check("Hash enthaelt weder das Kennwort noch sein SHA-256",
      PW not in h1 and hashlib.sha256(PW.encode()).hexdigest() not in h1)
check("richtiges Kennwort: (True, False)", sz.kennwort_pruefen(PW, h1) == (True, False),
      sz.kennwort_pruefen(PW, h1))
check("falsches Kennwort: (False, False)", sz.kennwort_pruefen(PW + "x", h1) == (False, False))
check("Gross/Klein zaehlt", sz.kennwort_pruefen(PW.upper(), h1) == (False, False))

alt = hashlib.sha256(PW.encode()).hexdigest()
check("Altwert SHA-256 passt und gilt als veraltet: (True, True)",
      sz.kennwort_pruefen(PW, alt) == (True, True), sz.kennwort_pruefen(PW, alt))
check("Altwert mit falschem Kennwort: (False, False)", sz.kennwort_pruefen("anders", alt) == (False, False))

kaputt = ["", "x", None, 42, "scrypt$", "scrypt$abc", alt.upper(), alt[:-1],
          h1.replace("scrypt$", "scrypt$$"), h1 + "$zusatz"]
schlecht = [repr(k)[:30] for k in kaputt if sz.kennwort_pruefen(PW, k) != (False, False)]
check("unbekannte/kaputte Formen fail-closed (%d Faelle)" % len(kaputt), not schlecht, schlecht)

# Ueberzogene Parameter: abgelehnt, OHNE zu rechnen (sonst legt ein manipulierter
# Eintrag den Dienst ueber Speicher/Zeit lahm). Die Attrappe zaehlt Aufrufe.
echt = sz._scrypt
aufrufe = []
sz._scrypt = lambda *a, **k: aufrufe.append(a[2:5]) or echt(*a, **k)
salz_hash = h1.split("$")[4:] if form else ["", ""]
ueberzogen = [f"scrypt${2 ** 20}$8$1${salz_hash[0]}${salz_hash[1]}",
              f"scrypt${2 ** 15}$64$1${salz_hash[0]}${salz_hash[1]}",
              f"scrypt${2 ** 15}$8$16${salz_hash[0]}${salz_hash[1]}",
              f"scrypt$3000$8$1${salz_hash[0]}${salz_hash[1]}"]
erg = [sz.kennwort_pruefen(PW, u) for u in ueberzogen]
check("ueberzogene/ungueltige Parameter: abgelehnt", all(e == (False, False) for e in erg), erg)
check("... und ohne einen einzigen scrypt-Lauf", not aufrufe, aufrufe)
aufrufe.clear()
sz.kennwort_pruefen(PW, h1)
check("(Gegenkontrolle) ein gueltiger Eintrag rechnet genau einmal", len(aufrufe) == 1, aufrufe)
sz._scrypt = echt


# ── B. main.py am Syntaxbaum ────────────────────────────────────────────────
def aufrufe_von(knoten, attr):
    return [c for c in ast.walk(knoten) if isinstance(c, ast.Call)
            and isinstance(c.func, ast.Attribute) and c.func.attr == attr]


def sha256_aufrufe(knoten):
    return [c for c in aufrufe_von(knoten, "sha256")
            if isinstance(c.func.value, ast.Name) and c.func.value.id == "hashlib"]


print("[B] main.py (Syntaxbaum)")
anm = FUNK["authenticate_linux_user"]
check("Anmeldung prueft ueber _standard_zugang.kennwort_pruefen",
      any(isinstance(c.func.value, ast.Name) and c.func.value.id == "_standard_zugang"
          for c in aufrufe_von(anm, "kennwort_pruefen")))
check("Anmeldung rechnet kein eigenes sha256", not sha256_aufrufe(anm))


def _nennt(knoten, name):
    return any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(knoten))


umschreiben = [i for i in ast.walk(anm) if isinstance(i, ast.If) and _nennt(i.test, "veraltet")
               and aufrufe_von(ast.Module(body=i.body, type_ignores=[]), "kennwort_hash")
               and any(isinstance(c.func, ast.Name) and c.func.id == "_save_auth_state"
                       for c in ast.walk(ast.Module(body=i.body, type_ignores=[])) if isinstance(c, ast.Call))]
check("Altwert wird nach gelungener Anmeldung neu gehasht UND gespeichert", bool(umschreiben))
check("... nur wenn die Anmeldung gelang (Bedingung nennt local_ok)",
      any(_nennt(i.test, "local_ok") for i in umschreiben))

wechsel = FUNK["change_password"]
# Nur die Zuweisung JE BENUTZER (state["docker_password"][name] = …) – das
# Anlegen des leeren Bereichs (state["docker_password"] = {}) ist kein Kennwort.
zuweisung = [a for a in ast.walk(wechsel) if isinstance(a, ast.Assign)
             and any(isinstance(t, ast.Subscript) and isinstance(t.value, ast.Subscript)
                     and "docker_password" in ast.unparse(t.value) for t in a.targets)]
check("Kennwortwechsel speichert ueber kennwort_hash",
      bool(zuweisung) and all(aufrufe_von(a.value, "kennwort_hash") for a in zuweisung),
      [ast.unparse(a) for a in zuweisung][:2])
check("Kennwortwechsel rechnet kein sha256", not sha256_aufrufe(wechsel))

print(f"\n{_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
