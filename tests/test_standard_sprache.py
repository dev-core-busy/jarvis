#!/usr/bin/env python3
"""Waechter: Standardsprache der Installation (2026-11-26).

Befund: Eine Installation in Franzoesisch/Englisch/Niederlaendisch zeigte die
Oberflaeche beim ersten Aufruf deutsch – i18n.js fiel ohne gespeicherte Wahl
fest auf 'de' zurueck. Jetzt gilt ``extra.standard_sprache`` aus settings.json:

  A  ``sprache.vorgabe()`` liest den Wert (nur de/en/fr/nl), folgt einer
     Aenderung der Datei und ist leer ohne Datei/Eintrag;
  B  ``aus_anfrage``: ?lang= > Cookie > Vorgabe > de;
  C  ``cookie_vorgabe``: nur fuer eine Anfrage OHNE gueltiges Cookie, eine
     eigene Wahl wird nie ueberschrieben;
  D  Middleware in main.py (am Syntaxbaum): setzt das Cookie aus
     ``cookie_vorgabe`` auf HTML-Antworten, lesbar fuer Skripte (httponly
     False), BEVOR sie die Antwort zurueckgibt.

Die Browserseite (i18n.js liest das Cookie) prueft test_standard_sprache_ui.js.
Prueflinge umlenkbar fuer die Gegenprobe: JARVIS_PRUEFLING_SPRACHE,
JARVIS_PRUEFLING_MAIN.

    python3 tests/test_standard_sprache.py
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import ast
import importlib.util
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPRACHE = Path(os.environ.get("JARVIS_PRUEFLING_SPRACHE", ROOT / "backend" / "sprache.py"))
MAIN = Path(os.environ.get("JARVIS_PRUEFLING_MAIN", ROOT / "backend" / "main.py"))
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("  OK   %s" % name)
    else:
        fail += 1
        print("  FAIL %s%s" % (name, (" – %s" % (detail,)) if detail else ""))


def abbruch(grund):
    print("ABBRUCH: " + grund)
    sys.exit(2)


class Anfrage:
    """Attrappe mit der Form, die aus_anfrage/cookie_vorgabe lesen (Starlette Request)."""
    def __init__(self, cookies=None, query=None):
        self.cookies = cookies or {}
        self.query_params = query or {}


for p in (SPRACHE, MAIN):
    if not p.is_file():
        abbruch("Pruefling fehlt: %s" % p)

d = tempfile.mkdtemp(prefix="std_sprache_")
os.environ["DATA_DIR"] = d                     # vor dem Laden: EINSTELLUNGEN haengt daran
spec = importlib.util.spec_from_file_location("sprache_pruefling", SPRACHE)
sp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sp)
datei = Path(d) / "settings.json"
for name in ("vorgabe", "aus_anfrage", "cookie_vorgabe"):
    if not callable(getattr(sp, name, None)):
        abbruch("sprache.%s fehlt" % name)
if Path(getattr(sp, "EINSTELLUNGEN", "")) != datei:
    abbruch("sprache.EINSTELLUNGEN folgt DATA_DIR nicht (%s)" % getattr(sp, "EINSTELLUNGEN", None))


def schreiben(inhalt):
    datei.write_text(json.dumps(inhalt), encoding="utf-8")
    # Aenderungszeit sicher weiterruecken (Cache haengt an st_mtime_ns)
    t = time.time() + schreiben.n
    schreiben.n += 1
    os.utime(datei, (t, t))


schreiben.n = 1

print("\nA – vorgabe()")
check("ohne Datei leer", sp.vorgabe() == "", sp.vorgabe())
schreiben({"version": 2, "extra": {"standard_sprache": "fr"}})
check("liest extra.standard_sprache", sp.vorgabe() == "fr", sp.vorgabe())
schreiben({"version": 2, "extra": {"standard_sprache": "nl"}})
check("folgt einer Aenderung der Datei", sp.vorgabe() == "nl", sp.vorgabe())
schreiben({"version": 2, "extra": {"standard_sprache": "xx"}})
check("unbekannte Sprache -> leer", sp.vorgabe() == "", sp.vorgabe())
schreiben({"version": 2, "standard_sprache": "fr"})
check("oberste Ebene zaehlt NICHT (geht beim Speichern verloren)", sp.vorgabe() == "", sp.vorgabe())

print("\nB – aus_anfrage()")
schreiben({"version": 2, "extra": {"standard_sprache": "fr"}})
check("ohne Cookie -> Vorgabe", sp.aus_anfrage(Anfrage()) == "fr", sp.aus_anfrage(Anfrage()))
check("Cookie gewinnt", sp.aus_anfrage(Anfrage(cookies={"jarvis_lang": "en"})) == "en")
check("?lang= gewinnt", sp.aus_anfrage(Anfrage(cookies={"jarvis_lang": "en"}, query={"lang": "nl"})) == "nl")
schreiben({"version": 2})
check("ohne Vorgabe -> de", sp.aus_anfrage(Anfrage()) == "de", sp.aus_anfrage(Anfrage()))

print("\nC – cookie_vorgabe()")
schreiben({"version": 2, "extra": {"standard_sprache": "fr"}})
check("ohne Cookie -> Vorgabe", sp.cookie_vorgabe(Anfrage()) == "fr", sp.cookie_vorgabe(Anfrage()))
check("eigene Wahl bleibt (Cookie de)", sp.cookie_vorgabe(Anfrage(cookies={"jarvis_lang": "de"})) == "")
check("ungueltiges Cookie wird ersetzt", sp.cookie_vorgabe(Anfrage(cookies={"jarvis_lang": "xx"})) == "fr")
schreiben({"version": 2})
check("ohne Vorgabe nichts setzen", sp.cookie_vorgabe(Anfrage()) == "")

print("\nD – Middleware in main.py")
baum = ast.parse(MAIN.read_text(encoding="utf-8"))
mw = next((n for n in ast.walk(baum)
           if isinstance(n, ast.AsyncFunctionDef) and n.name == "_sprache_setzen"), None)
if mw is None:
    abbruch("_sprache_setzen nicht in %s" % MAIN)


def aufruf(n, attr):
    return isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == attr


setz = [n for n in ast.walk(mw) if aufruf(n, "set_cookie")]
vorg = [n for n in ast.walk(mw) if aufruf(n, "cookie_vorgabe")]
rueck = [n for n in ast.walk(mw) if isinstance(n, ast.Return)]
check("ruft cookie_vorgabe(request)", bool(vorg))
check("setzt ein Cookie", bool(setz))
s = setz[0] if setz else None
if s is not None:
    erstes = s.args[0] if s.args else None
    check("… namens sprache.COOKIE",
          isinstance(erstes, ast.Attribute) and erstes.attr == "COOKIE", ast.unparse(s))
    kw = {k.arg: k.value for k in s.keywords}
    check("… fuer Skripte lesbar (httponly=False)",
          isinstance(kw.get("httponly"), ast.Constant) and kw["httponly"].value is False, ast.unparse(s))
    check("… fuer die ganze Seite (path='/')",
          isinstance(kw.get("path"), ast.Constant) and kw["path"].value == "/", ast.unparse(s))
    # nur auf HTML-Antworten: die umschliessende Bedingung nennt text/html
    huelle = next((n for n in ast.walk(mw) if isinstance(n, ast.If) and s in list(ast.walk(n))), None)
    check("… nur auf HTML-Antworten", huelle is not None and "text/html" in ast.unparse(huelle.test),
          ast.unparse(huelle.test) if huelle else None)
    check("… bevor die Middleware die Antwort zurueckgibt",
          bool(rueck) and s.lineno < min(r.lineno for r in rueck), (s.lineno, [r.lineno for r in rueck]))

print("\n%d OK, %d FAIL" % (ok, fail))
sys.exit(1 if fail else 0)
