#!/usr/bin/env python3
"""Waechter: Beschriftung der letzten Handlung in "Angemeldete Benutzer".

Gemeldet (2026-09-27): bei Short-Tracks-Nutzung stand dort nur "Aktion" -
der Pfad /api/tracks/ fehlte in der Bereichstabelle, und die Seite /tracks
fehlte in der Whitelist von POST /api/activity. Die Beschriftung ist seitdem
zweistufig (main.py::_action_label): genauer Endpunkt, sonst Bereich (+ Verb).

Geprueft wird die ECHTE Funktion samt ECHTER Tabellen, per ast aus main.py
herausgeloest (main.py selbst ist nicht importierbar - es zieht die Live-
Konfiguration). Gegen die ECHTEN Routen aller backend/*.py.

Nachtrag 2026-09-30: Abschnitt 5 hat die Kennung einer Seite aus ihrem
DATEINAMEN gebildet und war deshalb blind fuer genau den Fall, in dem Route und
Dateiname auseinandergehen - ``ai_mouse.html`` liegt unter ``/ai-mouse``,
``jira_addon.html`` unter ``/jira-addon``. Beide Whitelist-Eintraege trugen
Unterstriche, trafen nie, und die zwei Seiten liefen unter dem neutralen
"Aktion", waehrend dieser Waechter gruen meldete. Abschnitt 5 leitet die Kennung
jetzt aus dem ROUTE-Pfad ab, fuehrt dafuer die echte ``seite()`` aus
activity.js aus und prueft BEIDE Richtungen (fehlender wie toter Eintrag).
Bei derselben Gelegenheit fielen in Abschnitt 4 drei Endpunkte der
Kundenverwaltung auf, die in keiner Tabelle standen.

Exit 0 = gruen, 1 = Fehler, 2 = konnte nicht laufen.
"""
import ast
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OK = FAIL = 0


def check(text, bed, info=""):
    global OK, FAIL
    if bed:
        OK += 1
        print(f"  OK   {text}")
    else:
        FAIL += 1
        print(f"  FAIL {text}" + (f"  [{info}]" if info else ""))


def abbruch(grund):
    print(f"NICHT PRUEFBAR: {grund}")
    sys.exit(2)


src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
baum = ast.parse(src)
ns = {"re": re}
NAMEN = {"_ID", "_ACTION_DETAILS", "_ACTION_LABELS", "_ACTION_VERBEN",
         "_ACTION_IGNORE", "_ACTIVITY_PAGES"}
gefunden = set()
note_activity = None
for n in baum.body:
    if isinstance(n, ast.Assign):
        for t in n.targets:
            if isinstance(t, ast.Name) and t.id in NAMEN:
                exec(compile(ast.Module([n], []), "main.py", "exec"), ns)
                gefunden.add(t.id)
    elif isinstance(n, ast.FunctionDef) and n.name == "_action_label":
        exec(compile(ast.Module([n], []), "main.py", "exec"), ns)
        gefunden.add(n.name)
    elif isinstance(n, ast.FunctionDef) and n.name == "_note_activity":
        note_activity = n

print("\n1. Positivkontrolle")
fehlt = (NAMEN | {"_action_label"}) - gefunden
if fehlt:
    abbruch(f"nicht in main.py gefunden: {sorted(fehlt)}")
L = ns["_action_label"]
ROUTE = re.compile(r'@app\.(post|put|patch|delete)\("(/api/[^"]*)"')
routen = []
for f in sorted((ROOT / "backend").glob("*.py")):
    for m, pfad in ROUTE.findall(f.read_text(encoding="utf-8")):
        routen.append((m.upper(), pfad))
if len(routen) < 100:
    abbruch(f"nur {len(routen)} veraendernde Routen gefunden - Muster passt nicht mehr")
check(f"{len(routen)} veraendernde Routen gelesen", True)
check("unbekannter Pfad bleibt 'Aktion' (die Funktion unterscheidet ueberhaupt)",
      L("/api/gibtesnicht", "POST") == "Aktion", L("/api/gibtesnicht", "POST"))

print("\n2. Der gemeldete Fall: Short Tracks")
erwartet = [
    ("POST", "/api/tracks/drop", "Short Tracks · Datei abgelegt"),
    ("POST", "/api/tracks/drop_url", "Short Tracks · Web-Adresse abgelegt"),
    ("POST", "/api/tracks/dumps", "Short Tracks · Ablage angelegt"),
    ("PUT", "/api/tracks/dumps/d1", "Short Tracks · Ablage bearbeitet"),
    ("DELETE", "/api/tracks/dumps/d1", "Short Tracks · Ablage gelöscht"),
    ("POST", "/api/tracks/dumps/d1/reset", "Short Tracks · Ablage zurückgesetzt"),
    ("DELETE", "/api/tracks/jobs/j1", "Short Tracks · Lauf entfernt"),
]
for m, p, soll in erwartet:
    ist = L(p, m)
    check(f"{m} {p} -> {soll}", ist == soll, ist)
check("Seite /tracks meldet 'Short Tracks' (Whitelist von /api/activity)",
      ns["_ACTIVITY_PAGES"].get("tracks") == "Short Tracks", ns["_ACTIVITY_PAGES"].get("tracks"))

print("\n3. Stufe 2: Bereich + Verb")
check("DELETE ohne eigenen Eintrag -> Bereich · gelöscht",
      L("/api/knowledge/groups/g1", "DELETE") == "Wissen · gelöscht", L("/api/knowledge/groups/g1", "DELETE"))
check("PATCH ohne eigenen Eintrag -> Bereich · geändert",
      L("/api/knowledge/groups/g1", "PATCH") == "Wissen · geändert", L("/api/knowledge/groups/g1", "PATCH"))
check("POST ohne eigenen Eintrag -> nur der Bereich (nicht geraten)",
      L("/api/knowledge/reindex", "POST") == "Wissen", L("/api/knowledge/reindex", "POST"))
check("die Methode zaehlt: PUT auf den POST-Endpunkt ist nicht 'angelegt'",
      "angelegt" not in L("/api/tracks/dumps", "PUT"), L("/api/tracks/dumps", "PUT"))
check("ganzer Pfad, kein Praefix: /dumps/x/reset ist nicht 'bearbeitet'",
      L("/api/tracks/dumps/x/reset", "PUT") != "Short Tracks · Ablage bearbeitet",
      L("/api/tracks/dumps/x/reset", "PUT"))

print("\n4. Generell: keine Route mehr mit nichtssagendem 'Aktion'")
# /api/login laeuft ohne Anmeldung -> nie in _note_activity.
ohne = [(m, p) for m, p in routen
        if not p.startswith(ns["_ACTION_IGNORE"]) and p != "/api/login"
        and L(re.sub(r"\{[^}]+\}", "x1", p), m) == "Aktion"]
check("jede angemeldete veraendernde Route hat eine Beschriftung", not ohne,
      "; ".join(f"{m} {p}" for m, p in ohne[:10]))
lang = [(p, L(re.sub(r"\{[^}]+\}", "x1", p), m)) for m, p in routen]
lang = [x for x in lang if len(x[1]) > 60]
check("keine Beschriftung ueber 60 Zeichen (note_action kuerzt sonst mitten im Wort)",
      not lang, str(lang[:3]))

print("\n5. Jede Seite mit activity.js steht in der Whitelist")
# ⚠ DIE KENNUNG WIRD AUS DEM ROUTE-PFAD ABGELEITET, NICHT AUS DEM DATEINAMEN.
# Bis zum 2026-09-30 nahm dieser Abschnitt ``h.stem`` – damit war er fuer
# ``ai_mouse.html`` (/ai-mouse) und ``jira_addon.html`` (/jira-addon) GRUEN,
# waehrend die beiden Whitelist-Eintraege nie trafen und die Seiten unter dem
# neutralen "Aktion" liefen. Genau dort weichen Route und Dateiname
# voneinander ab, und nur die Route zaehlt: ``activity.js`` liest
# ``location.pathname``.
seiten = []
for h in sorted((ROOT / "frontend").glob("*.html")):
    if re.search(r"js/activity\.js", h.read_text(encoding="utf-8")):
        seiten.append(h.name)
if len(seiten) < 5:
    abbruch(f"nur {len(seiten)} Seiten mit activity.js gefunden")

# Route -> ausgelieferte HTML-Datei, aus den ECHTEN Dekoratoren von main.py.
# ast.Constant statt Regex: ``ast.unparse`` normiert auf einfache
# Anfuehrungszeichen, eine Suche nach "...html" findet dort nichts.
paare = []          # (route, htmldatei)
for n in ast.walk(baum):
    if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        continue
    routen_hier = [d.args[0].value for d in n.decorator_list
                   if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                   and d.func.attr == "get" and d.args
                   and isinstance(d.args[0], ast.Constant)
                   and isinstance(d.args[0].value, str)]
    if not routen_hier:
        continue
    htmls = sorted({c.value for c in ast.walk(n)
                    if isinstance(c, ast.Constant) and isinstance(c.value, str)
                    and c.value.endswith(".html")})
    for r in routen_hier:
        for h in htmls:
            if h in seiten:
                paare.append((r, h))

# Positivkontrolle A: jede Seite mit activity.js ist ueber mindestens eine Route
# erreichbar. Fehlt eine, uebersieht der Abschnitt sie STILL - "nicht geprueft"
# muss von "bestanden" unterscheidbar sein.
ohne_route = sorted(set(seiten) - {h for _, h in paare})
if ohne_route:
    abbruch("keine Route gefunden fuer: " + ", ".join(ohne_route))
check(f"{len(seiten)} Seiten mit activity.js, {len(paare)} Routen dazu", True)

# Die Umrechnung Pfad -> Kennung wird nicht nachgebaut, sondern die ECHTE
# ``seite()`` aus activity.js ausgefuehrt: eine nachgebaute Fassung weicht am
# Tag der naechsten Aenderung ab, ohne dass es auffaellt.
JS = (ROOT / "frontend" / "js" / "activity.js").read_text(encoding="utf-8")
_i = JS.find("function seite()")
if _i < 0:
    abbruch("function seite() nicht in activity.js gefunden")
_tiefe, _j = 0, JS.index("{", _i)
for _k in range(_j, len(JS)):
    if JS[_k] == "{":
        _tiefe += 1
    elif JS[_k] == "}":
        _tiefe -= 1
        if _tiefe == 0:
            _j = _k + 1
            break
else:
    abbruch("Rumpf von seite() nicht abgegrenzt")
SEITE_JS = JS[_i:_j]
if shutil.which("node") is None:
    abbruch("node fehlt - die echte seite() ist nicht ausfuehrbar")
_wege = sorted({r for r, _ in paare} | {"/ai-mouse", "/", "/x/y", "/Portal"})
_skript = (SEITE_JS + "\nconst W = " + json.dumps(_wege) + ";\nconst out = {};\n"
           "for (const w of W) { global.location = { pathname: w }; out[w] = seite(); }\n"
           "console.log(JSON.stringify(out));\n")
with tempfile.TemporaryDirectory() as _d:
    _f = Path(_d) / "seite.js"
    _f.write_text(_skript, encoding="utf-8")
    _p = subprocess.run(["node", str(_f)], capture_output=True, text=True, timeout=30)
if _p.returncode != 0:
    abbruch(f"seite() nicht ausfuehrbar: {_p.stderr.strip()[:200]}")
KENNUNG = json.loads(_p.stdout)

# Positivkontrolle B: die ausgefuehrte Funktion rechnet ueberhaupt - und zwar so,
# wie dieser Abschnitt es voraussetzt (erstes Segment, klein, ohne Schraegstrich).
for _weg, _soll in (("/ai-mouse", "ai-mouse"), ("/", ""), ("/x/y", "x"), ("/Portal", "portal")):
    if KENNUNG.get(_weg) != _soll:
        abbruch(f"seite({_weg!r}) liefert {KENNUNG.get(_weg)!r}, erwartet {_soll!r}")
check("echte seite() aus activity.js ausgefuehrt (4 Kontrollwege)", True)

# Die Anmeldeseite ist die EINE begruendete Ausnahme: ``/`` liefert
# settings.html als Huelle, die Kennung ist dort leer - und ``melde()`` kehrt
# ohne Sitzungstoken zurueck, bevor es ueberhaupt sendet. Es kommt also nie
# etwas an. Ausgenommen ist genau dieser Weg mit genau dieser Kennung, nicht
# "leere Kennungen allgemein".
ANMELDEWEG = "/"
PRUEFPAARE = [(r, h) for r, h in paare
              if not (r == ANMELDEWEG and KENNUNG[r] == "")]

# Positivkontrolle C: unter den geprueften Routen ist mindestens eine, deren
# Kennung vom DATEINAMEN abweicht. Ohne so einen Fall messen die beiden
# Pruefungen darunter dasselbe wie die Vorfassung ueber ``h.stem`` - sie waeren
# nicht falsch, aber blind fuer die Fehlerklasse, um die es hier geht.
_abweichend = [(h, KENNUNG[r]) for r, h in PRUEFPAARE if KENNUNG[r] != h[:-5].lower()]
if not _abweichend:
    abbruch("keine gepruefte Route weicht vom Dateinamen ab - der Abschnitt "
            "kann Route und Dateiname nicht mehr unterscheiden")
check(f"{len(_abweichend)} Route(n) weichen vom Dateinamen ab "
      f"(z. B. {_abweichend[0][0]} -> {_abweichend[0][1]!r})", True)

ANKOMMEND = {KENNUNG[r] for r, _ in PRUEFPAARE}
fehlen = sorted(ANKOMMEND - set(ns["_ACTIVITY_PAGES"]))
check("jede ankommende Kennung hat eine Beschriftung", not fehlen, ", ".join(fehlen))

# Die Gegenrichtung - und die ist es, die den Fehler vom 2026-09-30 faengt: ein
# Eintrag, den keine Route erzeugt, ist toter Text. Er sieht im Quelltext aus
# wie eine erfuellte Zusage und ist keine.
tot = sorted(set(ns["_ACTIVITY_PAGES"]) - ANKOMMEND)
check("kein toter Eintrag in _ACTIVITY_PAGES", not tot, ", ".join(tot))

print("\n6. Verdrahtung: _note_activity reicht die Methode durch")
if note_activity is None:
    abbruch("_note_activity nicht gefunden")
aufrufe = [c for c in ast.walk(note_activity)
           if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "_action_label"]
check("_action_label wird mit (pfad, request.method) gerufen",
      len(aufrufe) == 1 and len(aufrufe[0].args) == 2
      and ast.unparse(aufrufe[0].args[1]) == "request.method",
      ast.unparse(aufrufe[0]) if aufrufe else "kein Aufruf")

print(f"\nERGEBNIS: {OK}/{OK + FAIL}")
sys.exit(1 if FAIL else 0)
