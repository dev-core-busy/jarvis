#!/usr/bin/env python3
"""Waechter (2026-11-12): ein LLM-Profil-Schluessel laesst sich LOESCHEN.

Gemeldet: ein leeres Schluesselfeld hiess immer "unveraendert" – ein einmal
gespeicherter API-Key liess sich nicht mehr entfernen. Seitdem schickt das
Formular ``<feld>_entfernen: true``, wenn das Feld sichtbar geleert wurde.

Gemessen an den ECHTEN Funktionen, per AST aus dem Quelltext geschnitten
(``backend.config`` wird NICHT importiert – der echte Import schreibt die
Live-settings.json):
  1. config.update_profile: entfernen + leer -> "", leer ohne Flag -> bleibt,
     entfernen + neuer Wert -> neuer Wert, nur echtes True zaehlt, fuer
     api_key UND session_key
  2. main._profil_umleitung: neue Adresse + entfernter Schluessel ist KEINE
     Umleitung (es geht nichts an das neue Ziel), ohne Flag weiterhin schon

Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OK = FAIL = 0


def check(name, cond, detail=""):
    global OK, FAIL
    if cond:
        OK += 1
        print("  ✓ " + name)
    else:
        FAIL += 1
        print("  ✗ " + name + (" – %s" % (detail,) if detail != "" else ""))


def schneide(datei, name, ns, klasse=None):
    baum = ast.parse((ROOT / datei).read_text(encoding="utf-8"))
    wurzel = baum.body
    if klasse:
        k = next((n for n in baum.body if isinstance(n, ast.ClassDef) and n.name == klasse), None)
        if k is None:
            print("ABBRUCH: Klasse %s fehlt in %s" % (klasse, datei))
            sys.exit(2)
        wurzel = k.body
    fn = next((n for n in wurzel if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == name), None)
    if fn is None:
        print("ABBRUCH: %s fehlt in %s" % (name, datei))
        sys.exit(2)
    fn.decorator_list = []
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<%s:%s>" % (datei, name), "exec"), ns)
    return ns[name]


# ── 1. config.update_profile ────────────────────────────────────────────────
print("\n1) config.update_profile")
cns = {}
for hilfe in ("_valid_effort", "_valid_temperature", "_clean_profile_str"):
    schneide("backend/config.py", hilfe, cns)
upd = schneide("backend/config.py", "update_profile", cns, klasse="Config")


class Selbst:
    def __init__(self):
        self.gespeichert = 0
        self.profiles = [{"id": "p1", "api_key": "sk-echt", "session_key": "sess-echt",
                          "api_url": "https://api.beispiel.de/v1", "model": "m"}]

    def _save_to_file(self):
        self.gespeichert += 1


def lauf(data):
    s = Selbst()
    p = upd(s, "p1", data)
    return s, p


s, p = lauf({"model": "m2", "api_key": ""})
check("Positivkontrolle: Aufruf speichert und aendert ein Feld",
      s.gespeichert == 1 and p is not None and p["model"] == "m2", (s.gespeichert, p))
if FAIL:
    print("\nErgebnis: %d OK, %d FAIL" % (OK, FAIL))
    sys.exit(2)
check("leer ohne Flag: Schluessel bleibt", p["api_key"] == "sk-echt", p["api_key"])
s, p = lauf({"api_key": "", "api_key_entfernen": True})
check("leer + api_key_entfernen: Schluessel geloescht", p["api_key"] == "", p["api_key"])
check("… session_key bleibt davon unberuehrt", p["session_key"] == "sess-echt", p["session_key"])
s, p = lauf({"api_key_entfernen": True})
check("Feld fehlt + api_key_entfernen: geloescht", p["api_key"] == "", p["api_key"])
s, p = lauf({"api_key": "sk-neu", "api_key_entfernen": True})
check("neuer Wert + Flag: der neue Wert gewinnt", p["api_key"] == "sk-neu", p["api_key"])
for falsch in ("true", 1, "1", "ja"):
    s, p = lauf({"api_key": "", "api_key_entfernen": falsch})
    check("nur echtes True zaehlt (%r -> bleibt)" % (falsch,), p["api_key"] == "sk-echt", p["api_key"])
s, p = lauf({"session_key": "", "session_key_entfernen": True})
check("session_key_entfernen: Session-Key geloescht", p["session_key"] == "", p["session_key"])
check("… api_key bleibt", p["api_key"] == "sk-echt", p["api_key"])

# ── 2. main._profil_umleitung ───────────────────────────────────────────────
print("\n2) main._profil_umleitung")


class Cfg:
    profiles = [{"id": "p1", "provider": "openai", "api_url": "https://api.beispiel.de/v1",
                 "api_key": "sk-echt", "session_key": ""}]


mns = {"config": Cfg()}
uml = schneide("backend/main.py", "_profil_umleitung", mns)
check("Positivkontrolle: neue Adresse, Schluessel leer -> Umleitung (400)",
      uml("p1", {"api_url": "https://anderswo.beispiel.de/v1", "api_key": ""}) is True)
check("neue Adresse + api_key_entfernen -> keine Umleitung",
      uml("p1", {"api_url": "https://anderswo.beispiel.de/v1", "api_key": "",
                 "api_key_entfernen": True}) is False)
check("neue Adresse + Flag als Text -> weiterhin Umleitung",
      uml("p1", {"api_url": "https://anderswo.beispiel.de/v1", "api_key": "",
                 "api_key_entfernen": "true"}) is True)

print("\nErgebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
