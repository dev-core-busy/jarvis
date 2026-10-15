#!/usr/bin/env python3
"""Waechter: /static/ wird nur unter einer INHALTS-Kennung lang gecacht.

Die Zusage (backend/static_kennung.py): ``Cache-Control: … immutable`` gibt es
AUSSCHLIESSLICH fuer eine Anfrage, deren ``v`` gleich der Kennung des AKTUELLEN
Inhalts ist. Eine Hand-Nummer, eine veraltete Kennung, eine fremde Datei oder
ein Pfad ausserhalb der Wurzel bleibt ``no-cache``. Daran haengt, dass kein
Browser je auf einer alten Fassung festsitzt.

Abschnitte:
  1. Positivkontrolle – das Umschreiben erzeugt ueberhaupt eine Kennung,
     sonst waeren alle "bleibt kurz"-Pruefungen trivial wahr (Exit 2).
  2. cache_kopf: lang nur bei Gleichheit, auch nach einer Aenderung mit
     GLEICHER Groesse (mtime + Groesse als Merkschluessel).
  3. html_umschreiben: was umgeschrieben wird und was nicht.
  4. Einbindung in main.py (AST): die Middleware setzt den Kopf ueber
     cache_kopf, schreibt HTML ueber html_umschreiben um und setzt die
     Wurzel auf FRONTEND_DIR.

Hermetisch: Wegwerf-Verzeichnis, kein Import von backend.main/config.
"""
import ast
import os
import re
import sys
import tempfile
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))
from backend import static_kennung as SK  # noqa: E402

ok = fail = 0


def check(text, bed, info=""):
    global ok, fail
    if not isinstance(bed, bool):
        print("ABBRUCH: Bedingung ist kein bool: %s" % text)
        sys.exit(2)
    if bed:
        ok += 1
        print("  \x1b[32m✓\x1b[0m " + text)
    else:
        fail += 1
        print("  \x1b[31m✗\x1b[0m " + text + ("  [%s]" % str(info)[:300] if info else ""))


tmp = Path(tempfile.mkdtemp(prefix="static-kennung-"))
(tmp / "js").mkdir()
(tmp / "css").mkdir()
(tmp / "js" / "a.js").write_text("var a = 1;\n")
(tmp / "css" / "b.css").write_text("body{}\n")
(tmp / "seite.html").write_text("<p>x</p>")
(tmp.parent / (tmp.name + "-aussen.js")).write_text("geheim")
SK.wurzel_setzen(tmp)
LANG, KURZ = SK.LANG, SK.KURZ

# ── 1 ─────────────────────────────────────────────────────────────────────
print("\n1. Positivkontrolle")
html = '<script src="/static/js/a.js?v=3"></script>'
neu = SK.html_umschreiben(html)
m = re.search(r'/static/js/a\.js\?v=([0-9a-f]{16})"', neu)
check("Umschreiben erzeugt eine 16-Hex-Kennung", m is not None, neu)
check("LANG ist wirklich ein langer, unveraenderlicher Cache",
      "immutable" in LANG and "max-age=31536000" in LANG)
check("KURZ verlangt Nachfrage", "no-cache" in KURZ)
if fail:
    print("ABBRUCH: ohne Kennung waeren alle folgenden Pruefungen trivial wahr")
    sys.exit(2)
k = m.group(1)

# ── 2 ─────────────────────────────────────────────────────────────────────
print("\n2. cache_kopf: lang nur bei Gleichheit mit dem aktuellen Inhalt")
check("passende Kennung -> lang", SK.cache_kopf("/static/js/a.js", k) == LANG)
check("Hand-Nummer -> kurz", SK.cache_kopf("/static/js/a.js", "3") == KURZ)
check("ohne v -> kurz", SK.cache_kopf("/static/js/a.js", None) == KURZ)
check("leeres v -> kurz", SK.cache_kopf("/static/js/a.js", "") == KURZ)
check("Kennung einer ANDEREN Datei -> kurz",
      SK.cache_kopf("/static/css/b.css", k) == KURZ)
check("unbekannte Datei -> kurz", SK.cache_kopf("/static/js/fehlt.js", k) == KURZ)
check("HTML unter /static/ -> nie lang",
      SK.cache_kopf("/static/seite.html", SK.kennung("seite.html") or "x") == KURZ
      and SK.kennung("seite.html") is None)
aussen = "../" + tmp.name + "-aussen.js"
check("Pfad ausserhalb der Wurzel hat keine Kennung", SK.kennung(aussen) is None)
check("Pfad ausserhalb der Wurzel -> kurz",
      SK.cache_kopf("/static/" + aussen, "x") == KURZ)

# Aenderung mit GLEICHER Groesse: nur mtime unterscheidet – der Merkschluessel
# muss sie sehen, sonst bliebe die alte Kennung "passend".
p = tmp / "js" / "a.js"
st = p.stat()
p.write_text("var a = 2;\n")
os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
check("Positivkontrolle: Groesse gleich geblieben", p.stat().st_size == st.st_size)
k2 = SK.kennung("js/a.js")
check("nach Inhaltsaenderung neue Kennung", k2 is not None and k2 != k, (k, k2))
check("veraltete Kennung -> kurz", SK.cache_kopf("/static/js/a.js", k) == KURZ)
check("neue Kennung -> lang", SK.cache_kopf("/static/js/a.js", k2) == LANG)

# ── 3 ─────────────────────────────────────────────────────────────────────
print("\n3. html_umschreiben")
faelle = [
    ('<link rel="stylesheet" href="/static/css/b.css?v=12">', True),
    ("<script src='/static/js/a.js'></script>", True),
    ('<script src="/static/js/a.js?v=1&x=2"></script>', False),
    ('<script src="/static/js/fehlt.js?v=1"></script>', False),
    ('<a href="/static/seite.html">', False),
    ('<script src="https://cdn.example/static/js/a.js"></script>', False),
    ('<p>/static/js/a.js?v=1</p>', False),
]
for roh, soll in faelle:
    aus = SK.html_umschreiben(roh)
    check(("umgeschrieben: " if soll else "unveraendert: ") + roh,
          (aus != roh) == soll and (not soll or re.search(r"\?v=[0-9a-f]{16}['\"]", aus) is not None),
          aus)
zwei = SK.html_umschreiben('<script src="/static/js/a.js?v=1"></script>'
                           '<link href="/static/css/b.css" rel="stylesheet">')
check("mehrere Einbindungen in einem Dokument",
      len(re.findall(r"\?v=[0-9a-f]{16}", zwei)) == 2, zwei)
check("Anfuehrungszeichen bleiben gepaart",
      SK.html_umschreiben("<script src='/static/js/a.js?v=1'></script>").count("'") == 2)

# ── 4 ─────────────────────────────────────────────────────────────────────
print("\n4. Einbindung in main.py")
baum = ast.parse((WURZEL / "backend" / "main.py").read_text(encoding="utf-8"))
mw = [n for n in ast.walk(baum)
      if isinstance(n, ast.AsyncFunctionDef) and n.name == "no_cache_static"]
check("Middleware no_cache_static existiert genau einmal", len(mw) == 1, len(mw))


def ruft(knoten, name):
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == name for n in ast.walk(knoten))


if mw:
    check("Middleware setzt den Kopf ueber cache_kopf", ruft(mw[0], "cache_kopf"))
    check("Middleware schreibt HTML ueber html_umschreiben um", ruft(mw[0], "html_umschreiben"))
    feste = [n.value for n in ast.walk(mw[0])
             if isinstance(n, ast.Constant) and isinstance(n.value, str) and "max-age" in n.value]
    check("kein fest verdrahteter langer Cache in der Middleware", not feste, feste)
wurzel = [n for n in ast.walk(baum)
          if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
          and n.func.attr == "wurzel_setzen"
          and any(isinstance(a, ast.Name) and a.id == "FRONTEND_DIR" for a in n.args)]
check("Wurzel wird auf FRONTEND_DIR gesetzt", len(wurzel) == 1, len(wurzel))

print("\nErgebnis: %d OK, %d FAIL" % (ok, fail))
sys.exit(1 if fail else 0)
