"""Ein Skript, EIN Cache-Buster-Stand – ueber alle Seiten hinweg.

DER FEHLER, DEN DAS VERHINDERT: `frontend/js/chatlib.js` stand auf einer Seite
mit `?v=4` und auf einer anderen mit `?v=16`. Ein Browser, der beide Seiten
besucht, haelt damit ZWEI Fassungen derselben Datei im Cache – und die Seite
mit dem niedrigen Stand bekommt nach jeder Aenderung an chatlib.js weiter die
ALTE Fassung ausgeliefert, ohne dass irgendetwas auffaellt. Genau deshalb ist
die Konvention "bei Frontend-Aenderungen den Cache-Buster hochzaehlen" nur die
halbe Regel: sie muss an ALLEN Einbindungen derselben Datei gleichzeitig
greifen.

Gemessen beim Anlegen dieses Waechters: 9 von 64 eingebundenen Dateien liefen
auseinander, verteilt auf 14 Seiten – u.a. security_incidents.js (v=14 gegen
v=30) und theme.css (v=17 gegen v=18).

Der Test prueft die REGEL, nicht eine gepflegte Liste: jede kuenftige Seite und
jede neue Datei faellt automatisch darunter.
"""
import collections
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Einbindungen der Form /static/js/name.js?v=N bzw. /static/css/name.css?v=N
_RE = re.compile(r'/static/(?:js|css)/([A-Za-z0-9_.-]+\.(?:js|css))\?v=(\d+)')

res = []


def check(name, cond, detail=""):
    res.append(bool(cond))
    mark = "\033[32m✓\033[0m" if cond else "\033[31m✗\033[0m"
    print(f"  {mark} {name}" + ("" if cond else f" – {detail}"))


seiten = sorted(glob.glob(os.path.join(ROOT, "frontend", "**", "*.html"), recursive=True))
stand = collections.defaultdict(lambda: collections.defaultdict(list))
ohne = collections.defaultdict(list)

for h in seiten:
    txt = open(h, encoding="utf-8", errors="replace").read()
    kurz = os.path.relpath(h, ROOT)
    for m in _RE.finditer(txt):
        stand[m.group(1)][m.group(2)].append(kurz)
    # Einbindung GANZ OHNE ?v= – dieselbe Wirkung wie ein eingefrorener Stand:
    # der Browser behaelt die Datei, bis er den Cache von sich aus aufgibt.
    for m in re.finditer(r'/static/(?:js|css)/([A-Za-z0-9_.-]+\.(?:js|css))(?!\?v=)', txt):
        ohne[m.group(1)].append(kurz)

print(f"\n\033[1m1. Grundlage\033[0m")
check(f"{len(seiten)} Seiten gelesen", len(seiten) >= 10, str(len(seiten)))
check(f"{len(stand)} versionierte Dateien gefunden", len(stand) >= 30, str(len(stand)))

print(f"\n\033[1m2. Ein Skript, EIN Stand\033[0m")
uneins = {d: v for d, v in stand.items() if len(v) > 1}
for datei in sorted(stand):
    v = stand[datei]
    if len(v) == 1:
        continue
    teile = " | ".join(f"v={k}: {', '.join(sorted(set(s)))}"
                       for k, s in sorted(v.items(), key=lambda x: -int(x[0])))
    check(f"{datei} hat ueberall denselben Stand", False, teile)
if not uneins:
    check("alle Dateien haben ueberall denselben Stand", True)

print(f"\n\033[1m3. Keine Einbindung ohne ?v=\033[0m")
# Nur melden, wo dieselbe Datei anderswo SEHR WOHL versioniert ist: eine Datei,
# die nirgends einen Stand traegt, ist eine bewusste Entscheidung – eine, die
# ihn auf 9 von 10 Seiten traegt, ist ein Vergessen.
gemischt = {d: s for d, s in ohne.items() if d in stand}
for d, s in sorted(gemischt.items()):
    check(f"{d} ist ueberall versioniert", False, "ohne ?v= in: " + ", ".join(sorted(set(s))))
if not gemischt:
    check("keine halb versionierte Datei", True)

schlecht = res.count(False)
print(f"\n\033[1mErgebnis: {len(res) - schlecht}/{len(res)}\033[0m")
sys.exit(1 if schlecht else 0)
