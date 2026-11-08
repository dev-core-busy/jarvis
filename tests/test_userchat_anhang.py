#!/usr/bin/env python3
"""Waechter: Benutzer-Chat verwirft Anhaenge mit ungueltigem base64 (Befund B3, Serverseite).

``_uc_anhaenge_pruefen`` wird per AST aus ``backend/main.py`` geschnitten und
ausgefuehrt; dazu die Regel, dass der ``dm``-Zweig der WebSocket-Schleife seine
Anhaenge WIRKLICH ueber diese Funktion fuehrt (Aufruf am Syntaxbaum, Ergebnis
ist das, was in ``msg["attachments"]`` landet).
Kein ``backend.config``. Exit 0 gruen, 1 FAIL, 2 konnte nicht laufen.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "backend" / "main.py"
OK = FAIL = 0


def check(bed, text):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + text)
    else:
        FAIL += 1
        print("  FAIL " + text)


QUELLE = MAIN.read_text(encoding="utf-8")
BAUM = ast.parse(QUELLE)
teile = [k for k in BAUM.body
         if (isinstance(k, ast.FunctionDef) and k.name == "_uc_anhaenge_pruefen")
         or (isinstance(k, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_UC_OK_MIME"
                                              for t in k.targets))]
if len(teile) != 2:
    print("ABBRUCH: _uc_anhaenge_pruefen/_UC_OK_MIME nicht gefunden", flush=True)
    sys.exit(2)
NS: dict = {}
exec(compile(ast.Module(body=teile, type_ignores=[]), str(MAIN), "exec"), NS)
f = NS["_uc_anhaenge_pruefen"]

gut = {"name": "a.png", "mime_type": "image/png", "data": "iVBORw0KGgo="}
r = f([gut], 1000)
if r != [gut]:
    print("ABBRUCH: Positivkontrolle – gueltiger Anhang kam nicht durch: %r" % r, flush=True)
    sys.exit(2)
check(True, "Positivkontrolle: gueltiger Anhang bleibt")

print("\n1. Ungueltiges base64 wird verworfen")
for daten, text in (('AAAA" onmouseover="x', "Anfuehrungszeichen"),
                    ('"><img src=x onerror=alert(1)>', "Markup"),
                    ("QUJD\nRA==", "Zeilenumbruch"),
                    ("QUJ", "falsche Laenge")):
    check(f([dict(gut, data=daten)], 1000) == [], "verworfen: %s" % text)

print("\n2. Typen und Grenzen")
check(f([dict(gut, mime_type="text/html")], 1000) == [], "text/html nicht erlaubt")
check(f([dict(gut, mime_type="image/svg+xml")], 1000) == [], "SVG nicht erlaubt")
check(f([dict(gut, data=["x"])], 1000) == [], "data als Liste verworfen (kein Absturz)")
check(f([dict(gut, mime_type=None)], 1000) == [], "mime_type None verworfen")
check(f("kein-array", 1000) == [], "Anhaenge als String -> leer")
check(f([None, 3, gut], 1000) == [gut], "Nicht-Objekte uebersprungen")
check(f([gut] * 9, 1000) == [gut] * 5, "hoechstens 5 Anhaenge")
check(f([gut], 4) == [], "Groessengrenze greift")
check(f([dict(gut, name=None)], 1000)[0]["name"] == "datei", "fehlender Name -> 'datei'")
check(set(f([dict(gut, extra="x")], 1000)[0]) == {"name", "mime_type", "data"},
      "unbekannte Felder fallen weg")

print("\n3. Der dm-Zweig benutzt die Pruefung")
zuweisung = aufruf_ok = False
for k in ast.walk(BAUM):
    if isinstance(k, ast.Assign) and isinstance(k.value, ast.Call) \
            and isinstance(k.value.func, ast.Name) and k.value.func.id == "_uc_anhaenge_pruefen":
        if any(isinstance(t, ast.Name) and t.id == "clean_atts" for t in k.targets):
            zuweisung = True
    if isinstance(k, ast.Assign) and any(
            isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
            and t.slice.value == "attachments" for t in k.targets):
        if isinstance(k.value, ast.Name) and k.value.id == "clean_atts":
            aufruf_ok = True
check(zuweisung, "clean_atts = _uc_anhaenge_pruefen(...) im WebSocket-Zweig")
check(aufruf_ok, 'msg["attachments"] = clean_atts (das Gepruefte wird gespeichert)')
anzahl = sum(1 for k in ast.walk(BAUM) if isinstance(k, ast.Assign) and any(
    isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
    and t.slice.value == "attachments" for t in k.targets))
check(anzahl == 1, "genau EINE Stelle setzt msg['attachments'] (%d)" % anzahl)

print("\n" + "=" * 60)
print("  %d OK, %d FAIL" % (OK, FAIL))
print("=" * 60)
sys.exit(0 if FAIL == 0 else 1)
