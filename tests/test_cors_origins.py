#!/usr/bin/env python3
"""Waechter: ``cors_origins`` wird beim Start geprueft (Pentest-Vorbereitung 2026-11-05).

Bis dahin ging jeder Eintrag aus ``cors_origins`` ungeprueft an die
CORS-Middleware – mit ``allow_credentials=True``. Ein ``*`` oder ein
``http://``-Ursprung haette fremden Seiten Anfragen mit den Cookies des
Benutzers erlaubt.

Gemessen wird die WIRKUNG: ``_cors_extra_pruefen`` wird aus main.py
geschnitten (AST, ohne den echten Import, der backend.config laedt) und mit
guten und schlechten Werten ausgefuehrt. Dazu die Regel am Syntaxbaum: die
Middleware bekommt nur die geprueften Werte, und jeder verworfene Eintrag
erzeugt eine Journalzeile.
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht messen.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
BAUM = ast.parse(SRC)
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  OK   {name}")
    else:
        fail += 1
        print(f"  FAIL {name}" + (f"  -> {detail}" if detail else ""))


fn = next((n for n in BAUM.body if isinstance(n, ast.FunctionDef) and n.name == "_cors_extra_pruefen"), None)
if fn is None:
    print("ABBRUCH: _cors_extra_pruefen fehlt in main.py")
    sys.exit(2)
ns = {}
exec(compile(ast.Module(body=[fn], type_ignores=[]), "main.py", "exec"), ns)
pruefe = ns["_cors_extra_pruefen"]

gut, weg = pruefe("https://jarvis.beispiel.de, https://host.beispiel.de:8443/")
if gut != ["https://jarvis.beispiel.de", "https://host.beispiel.de:8443"]:
    print(f"ABBRUCH: Positivkontrolle – gueltige Herkunft wird nicht angenommen ({gut!r})")
    sys.exit(2)
check("gueltige https-Herkuenfte angenommen (Schraegstrich am Ende normiert)", not weg, str(weg))

SCHLECHT = ["*", "null", "http://jarvis.beispiel.de", "https://*.beispiel.de",
            "https://jarvis.beispiel.de/pfad", "https://user:pw@jarvis.beispiel.de",
            "jarvis.beispiel.de", "https://a.beispiel.de https://b.beispiel.de",
            "https://", "javascript:alert(1)", "HTTP://x.beispiel.de"]
for s in SCHLECHT:
    g, w = pruefe(s)
    check(f"verworfen: {s!r}", g == [] and w == [s], f"gut={g} weg={w}")
g, w = pruefe(["https://[2001:db8::1]:443", "", "  "])
check("IPv6-Herkunft angenommen, Leereintraege ignoriert", g == ["https://[2001:db8::1]:443"] and w == [], str((g, w)))
g, w = pruefe("https://Jarvis.Beispiel.de,https://jarvis.beispiel.de")
check("Gross/Klein normiert, keine Doppelung", g == ["https://jarvis.beispiel.de"], str(g))

print("── Einbindung ──")
ziel = None
for n in BAUM.body:
    if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) \
            and getattr(n.value.func, "attr", "") == "add_middleware" \
            and n.value.args and getattr(n.value.args[0], "id", "") == "CORSMiddleware":
        ziel = n.value
if ziel is None:
    print("ABBRUCH: CORSMiddleware-Einbindung nicht gefunden")
    sys.exit(2)
quelle = next((k.value for k in ziel.keywords if k.arg == "allow_origins"), None)
check("allow_origins ist _cors_origins", getattr(quelle, "id", "") == "_cors_origins")
# Jede Erweiterung von _cors_origins auf Modulebene geht ueber das Pruefergebnis
erweiterungen = [n for n in ast.walk(ast.Module(body=BAUM.body, type_ignores=[]))
                 if isinstance(n, ast.Call) and getattr(n.func, "attr", "") in ("extend", "append")
                 and getattr(getattr(n.func, "value", None), "id", "") == "_cors_origins"]
check("_cors_origins wird nur mit dem Pruefergebnis erweitert",
      len(erweiterungen) == 1 and ast.unparse(erweiterungen[0].args[0]) == "_cors_gut",
      [ast.unparse(e) for e in erweiterungen])
roh_lesen = [n for n in BAUM.body if "cors_origins" in ast.unparse(n)
             and "get_setting" in ast.unparse(n)]
check("cors_origins wird genau einmal gelesen, und zwar durch _cors_extra_pruefen",
      len(roh_lesen) == 1 and "_cors_extra_pruefen(" in ast.unparse(roh_lesen[0]),
      [ast.unparse(n)[:120] for n in roh_lesen])
journal = [n for n in BAUM.body if isinstance(n, ast.For) and ast.unparse(n.iter) == "_cors_weg"
           and "print(" in ast.unparse(n)]
check("jeder verworfene Eintrag erzeugt eine Journalzeile", len(journal) == 1)

print(f"\nBilanz: {ok} OK, {fail} FAIL")
sys.exit(0 if fail == 0 else 1)
