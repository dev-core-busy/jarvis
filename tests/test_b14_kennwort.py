#!/usr/bin/env python3
"""Waechter: Haertung B14 im Jarvis-Code – PAM-Dienst der Web-Anmeldung und
Mindestlaenge eines Kennworts.

Gemessen an der WIRKUNG, wo sie ohne Server messbar ist:
  [A] ``_pam_dienst`` (aus backend/main.py per AST geschnitten und ausgefuehrt):
      jarvis-web, wenn /etc/pam.d/jarvis-web da ist, sonst login.
  [B] Regel am AST: die lokale Kennwortpruefung (``_pam.authenticate``) laeuft
      ueber ``service=_pam_dienst()`` – kein fester Dienstname mehr.
      WARUM: im Dienstkontext meldet pam_faillock "System error", auch beim
      richtigen Kennwort (DEV 2026-11-21) – ein fester Dienst "login" braeche
      mit B14 jede lokale Web-Anmeldung.
  [C] ``_validate_password_strength`` ausgefuehrt: 13 Zeichen abgelehnt, mit der
      Zahl im Text; 14 Zeichen angenommen.
  [D] Dieselbe Zahl an allen Stellen der Oberflaeche: beide Staerkeanzeigen in
      app.js, security.pw_hint DE/EN (i18n.js) und der Vorgabetext in
      settings.html; dazu pwquality in deploy/security/system_haertung.sh.

Die geprueften Dateien koennen ueber JARVIS_B14_WURZEL aus einer KOPIE des
Baums gelesen werden (Gegenprobe tests/gegen_b14_kennwort.py) – so sabotiert
die Gegenprobe nie eine Datei im Arbeitsbaum.

Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import ast
import os
import re
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(os.environ.get("JARVIS_B14_WURZEL") or Path(__file__).resolve().parent.parent)
MAIN = ROOT / "backend" / "main.py"
OK = 0
FAIL = 0


def check(name: str, bed: bool) -> None:
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name)


def abbruch(grund: str) -> None:
    print("ABBRUCH: " + grund)
    sys.exit(2)


QUELLE = MAIN.read_text(encoding="utf-8")
BAUM = ast.parse(QUELLE)


def funktion(name: str):
    treffer = [n for n in BAUM.body if isinstance(n, ast.FunctionDef) and n.name == name]
    return treffer[0] if len(treffer) == 1 else None


def konstante(name: str):
    for n in BAUM.body:
        if (isinstance(n, ast.Assign) and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name) and n.targets[0].id == name
                and isinstance(n.value, ast.Constant)):
            return n.value.value
    return None


# ── Positivkontrolle: die Stellen gibt es ───────────────────────────────────
for _n in ("_pam_dienst", "_validate_password_strength", "authenticate_linux_user"):
    if funktion(_n) is None:
        abbruch("Funktion %s nicht genau einmal in backend/main.py" % _n)
MIN = konstante("KENNWORT_MIN_LAENGE")
if not isinstance(MIN, int):
    abbruch("KENNWORT_MIN_LAENGE fehlt in backend/main.py (keine ganze Zahl)")

# ── [A] _pam_dienst ─────────────────────────────────────────────────────────
print("[A] PAM-Dienst der Web-Anmeldung")
check("PAM_DIENST_WEB = 'jarvis-web'", konstante("PAM_DIENST_WEB") == "jarvis-web")
_tmp = Path(tempfile.mkdtemp(prefix="waechter-b14-"))
_ns = {"PAM_DIENST_WEB": "jarvis-web", "PAM_DIENST_DATEI": _tmp / "jarvis-web"}
exec(compile(ast.Module(body=[funktion("_pam_dienst")], type_ignores=[]), str(MAIN), "exec"), _ns)
check("Datei fehlt: login (bisheriges Verhalten)", _ns["_pam_dienst"]() == "login")
(_tmp / "jarvis-web").write_text("auth required pam_unix.so\n", encoding="utf-8")
check("Datei da: jarvis-web", _ns["_pam_dienst"]() == "jarvis-web")
(_tmp / "jarvis-web").unlink()
(_tmp / "jarvis-web").mkdir()
check("Verzeichnis statt Datei: login", _ns["_pam_dienst"]() == "login")
_tmp_rest = _tmp

# ── [B] Regel: die Kennwortpruefung nimmt _pam_dienst() ──────────────────────
print("[B] lokale Kennwortpruefung")
aufrufe = [c for c in ast.walk(BAUM) if isinstance(c, ast.Call)
           and isinstance(c.func, ast.Attribute) and c.func.attr == "authenticate"
           and isinstance(c.func.value, ast.Name) and c.func.value.id == "_pam"]
if not aufrufe:
    abbruch("kein Aufruf _pam.authenticate(...) in backend/main.py gefunden")
check("genau ein _pam.authenticate-Aufruf (%d)" % len(aufrufe), len(aufrufe) == 1)
im_login = [c for c in ast.walk(funktion("authenticate_linux_user")) if c in aufrufe]
check("er steht in authenticate_linux_user", len(im_login) == 1)


def dienst_arg(c):
    for k in c.keywords:
        if k.arg == "service":
            return k.value
    return None


check("jeder Aufruf: service=_pam_dienst()",
      all(isinstance(dienst_arg(c), ast.Call) and isinstance(dienst_arg(c).func, ast.Name)
          and dienst_arg(c).func.id == "_pam_dienst" and not dienst_arg(c).args for c in aufrufe))

# ── [C] Mindestlaenge ausgefuehrt ───────────────────────────────────────────
print("[C] Mindestlaenge")
check("KENNWORT_MIN_LAENGE = 14", MIN == 14)
_ns2 = {"KENNWORT_MIN_LAENGE": MIN,
        "_standard_zugang": types.SimpleNamespace(ist_standardkennwort=lambda pw, u: False)}
exec(compile(ast.Module(body=[funktion("_validate_password_strength")], type_ignores=[]),
             str(MAIN), "exec"), _ns2)
pruef = _ns2["_validate_password_strength"]
kurz = "Ab1" + "x" * (MIN - 4)       # MIN-1 Zeichen, sonst alles erfuellt
lang = "Ab1" + "x" * (MIN - 3)       # MIN Zeichen
f_kurz, f_lang = pruef(kurz, "jarvis"), pruef(lang, "jarvis")
check("%d Zeichen abgelehnt" % len(kurz), bool(f_kurz))
check("Ablehnung nennt die Zahl %d" % MIN, any(str(MIN) in f for f in f_kurz))
check("%d Zeichen angenommen (%s)" % (len(lang), f_lang), f_lang == [])

# ── [D] dieselbe Zahl in Oberflaeche und Skript ─────────────────────────────
print("[D] dieselbe Zahl an allen Stellen")
app = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
anzeigen = re.findall(r"\bpw\.length\s*>=\s*(\d+)", app)
check("app.js: zwei Staerkeanzeigen gefunden (%d)" % len(anzeigen), len(anzeigen) == 2)
check("app.js: beide mit %d (%s)" % (MIN, anzeigen), bool(anzeigen) and set(anzeigen) == {str(MIN)})
i18n = (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")
hinweise = re.findall(r"'security\.pw_hint':\s*'([^']*)'", i18n)
check("i18n.js: security.pw_hint in DE und EN (%d)" % len(hinweise), len(hinweise) == 2)
check("i18n.js: beide nennen %d und keine andere Zahl" % MIN,
      len(hinweise) == 2 and all(re.findall(r"\d+", h) == [str(MIN)] for h in hinweise))
seite = (ROOT / "frontend" / "settings.html").read_text(encoding="utf-8")
vorgabe = re.search(r'data-i18n="security\.pw_hint"[^>]*>\s*([^<]*)<', seite)
check("settings.html: Vorgabetext nennt %d" % MIN,
      bool(vorgabe) and re.findall(r"\d+", vorgabe.group(1)) == [str(MIN)])
skript = (ROOT / "deploy" / "security" / "system_haertung.sh").read_text(encoding="utf-8")
pw = re.search(r"(?m)^minlen = (\d+)'?$", skript)
check("system_haertung.sh: pwquality minlen = %d" % MIN, bool(pw) and pw.group(1) == str(MIN))

import shutil  # noqa: E402
shutil.rmtree(_tmp_rest, ignore_errors=True)
print("\nErgebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
