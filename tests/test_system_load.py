#!/usr/bin/env python3
"""Waechter: Systemauslastung hinter der CPU-Anzeige (`backend/system_load.py`,
`/api/system/load`, `frontend/js/sysload.js`).

  1. der Bericht MISST WIRKLICH: ein eigens gestarteter Rechenprozess muss in
     der Liste stehen, mit spuerbarer CPU-Last – eine Liste, in der alles 0 %
     hat (Einzelaufruf von `cpu_percent` ohne Messfenster), sieht aus wie
     Entwarnung und ist eine falsche Sonde
  2. hoechstens 20 Prozesse, absteigend nach CPU
  3. alle vier Bereiche (CPU, Speicher, Netz, Platte) sind im Bericht
  4. Endpunkt: nur Administratoren (`require_local_auth`), Messung NICHT im
     Event-Loop (`asyncio.to_thread`) – am Syntaxbaum, nicht am Text
  5. Oberflaeche: /portal bindet das Modul ein, Admin-Frage ueber /api/me,
     jeder benutzte i18n-Schluessel existiert auf DE UND EN

Exit 0 = gruen, 1 = rot, 2 = konnte nicht laufen.
"""
import ast
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ok = fail = 0


def abschnitt(t):
    print("\n\033[1m%s\033[0m" % t)


def check(name, cond, detail=""):
    global ok, fail
    if bool(cond):
        ok += 1
        print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1
        print("  \033[31m✗\033[0m %s%s" % (name, (" – " + str(detail)) if detail else ""))


def abbruch(grund):
    print("\033[33mKONNTE NICHT LAUFEN: %s\033[0m" % grund)
    sys.exit(2)


# ── Positivkontrolle ─────────────────────────────────────────────────────
try:
    import psutil  # noqa: F401
    from backend import system_load
except Exception as e:  # pragma: no cover
    abbruch(f"backend.system_load nicht importierbar: {e}")

MAIN = ROOT / "backend" / "main.py"
JS = ROOT / "frontend" / "js" / "sysload.js"
I18N = ROOT / "frontend" / "js" / "i18n.js"
PORTAL = ROOT / "frontend" / "portal.html"
for p in (MAIN, JS, I18N, PORTAL):
    if not p.exists():
        abbruch(f"{p} fehlt")

# ── 1-3. Der Bericht misst ───────────────────────────────────────────────
abschnitt("1. Der Bericht misst wirklich (Rechenprozess muss oben stehen)")
last = subprocess.Popen([sys.executable, "-c", "while True: pass"])
try:
    time.sleep(0.3)
    b = system_load.bericht()
finally:
    last.kill()
    last.wait()

procs = b.get("prozesse") or []
if not procs:
    abbruch("Bericht ohne Prozesse – Messung nicht deutbar")
eigen = [p for p in procs if p.get("pid") == last.pid]
check("Rechenprozess steht in der Liste", bool(eigen),
      f"PID {last.pid} fehlt; oben: {[(p['pid'], p['cpu']) for p in procs[:5]]}")
check("Rechenprozess hat spuerbare CPU-Last (> 30 %)",
      bool(eigen) and eigen[0].get("cpu", 0) > 30,
      eigen[0].get("cpu") if eigen else "–")
check("nicht alles 0 %", any((p.get("cpu") or 0) > 0 for p in procs))

abschnitt("2. Hoechstens 20, absteigend nach CPU")
check(f"hoechstens 20 Prozesse ({len(procs)})", 0 < len(procs) <= 20)
werte = [p.get("cpu", 0) for p in procs]
check("absteigend sortiert", werte == sorted(werte, reverse=True), werte)
check("Gesamtzahl >= gelistete", (b.get("prozesse_gesamt") or 0) >= len(procs))
felder = {"pid", "name", "user", "cpu", "rss", "cmd"}
check("jede Zeile traegt pid/name/user/cpu/rss/cmd",
      all(felder <= set(p) for p in procs))

abschnitt("3. CPU, Speicher, Netz, Platte")
cpu = b.get("cpu") or {}
check("CPU gesamt + je Kern", "prozent" in cpu and
      len(cpu.get("je_kern") or []) == cpu.get("kerne"))
check("Speicher mit Gesamt/Belegt/Prozent",
      {"gesamt", "belegt", "prozent"} <= set(b.get("speicher") or {}))
check("Netz mit Raten", {"rx_rate", "tx_rate"} <= set(b.get("netz") or {}))
pl = b.get("platte") or {}
check("Platte mit I/O und mindestens einer Partition",
      "io" in pl and len(pl.get("partitionen") or []) >= 1)

# ── 4. Endpunkt am Syntaxbaum ────────────────────────────────────────────
abschnitt("4. Endpunkt: Admin + to_thread")
baum = ast.parse(MAIN.read_text(encoding="utf-8"))
ep = None
for n in ast.walk(baum):
    if isinstance(n, ast.AsyncFunctionDef):
        for d in n.decorator_list:
            if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                    and d.func.attr == "get" and d.args
                    and isinstance(d.args[0], ast.Constant)
                    and d.args[0].value == "/api/system/load"):
                ep = n
if ep is None:
    abbruch("Endpunkt /api/system/load nicht gefunden")


def _depends(fn):
    aus = set()
    for d in fn.args.defaults + fn.args.kw_defaults:
        if (isinstance(d, ast.Call) and isinstance(d.func, ast.Name)
                and d.func.id == "Depends" and d.args
                and isinstance(d.args[0], ast.Name)):
            aus.add(d.args[0].id)
    return aus


check("haengt an require_local_auth", "require_local_auth" in _depends(ep), _depends(ep))
to_thread = [c for c in ast.walk(ep) if isinstance(c, ast.Call)
             and isinstance(c.func, ast.Attribute) and c.func.attr == "to_thread"
             and c.args and isinstance(c.args[0], ast.Attribute)
             and c.args[0].attr == "bericht"]
direkt = [c for c in ast.walk(ep) if isinstance(c, ast.Call)
          and isinstance(c.func, ast.Attribute) and c.func.attr == "bericht"]
check("bericht laeuft ueber asyncio.to_thread", bool(to_thread))
check("bericht wird nicht direkt im Event-Loop aufgerufen", not direkt)

# ── 5. Oberflaeche ───────────────────────────────────────────────────────
abschnitt("5. Oberflaeche")
js = JS.read_text(encoding="utf-8")
portal = PORTAL.read_text(encoding="utf-8")
check("/portal bindet sysload.js ein", re.search(r'/static/js/sysload\.js\?v=\d+', portal))
# Der Klick hinter der CPU-Anzeige gilt auf JEDER Seite mit CPU-Anzeige, nicht
# nur auf /portal. Gemessen an den <script src>-Angaben, nicht am Teilstring –
# ein Kommentar, der "cpubar.js" erwaehnt, ist kein Einbinden.
SRC = re.compile(r'<script\b[^>]*\bsrc="/static/js/([a-z_]+)\.js(?:\?v=\d+)?"', re.I)
mit_cpu, ohne_load = [], []
for p in sorted((ROOT / "frontend").glob("*.html")):
    skripte = set(SRC.findall(p.read_text(encoding="utf-8")))
    if "cpubar" in skripte:
        mit_cpu.append(p.name)
        if "sysload" not in skripte:
            ohne_load.append(p.name)
if "portal.html" not in mit_cpu or len(mit_cpu) < 2:
    abbruch(f"Seiten mit CPU-Anzeige nicht erkannt ({mit_cpu})")
check(f"jede Seite mit CPU-Anzeige ({len(mit_cpu)}) bindet sysload.js ein",
      not ohne_load, ohne_load)
check("fragt /api/system/load ab", "'/api/system/load'" in js)
check("Admin-Frage ueber /api/me", "'/api/me'" in js and "is_admin" in js)

i18n = I18N.read_text(encoding="utf-8")
mitte = i18n.find("'wissen.cpu_load': 'CPU load'")
if mitte < 0:
    abbruch("EN-Block in i18n.js nicht gefunden")
de_teil, en_teil = i18n[:mitte], i18n[mitte:]
schluessel = sorted(set(re.findall(r"T\('(load\.[a-z_]+)'", js)))
if len(schluessel) < 10:
    abbruch(f"zu wenige load.*-Schluessel gefunden ({len(schluessel)})")
fehlt_de = [k for k in schluessel if f"'{k}':" not in de_teil]
fehlt_en = [k for k in schluessel if f"'{k}':" not in en_teil]
check(f"{len(schluessel)} Schluessel auf DE vorhanden", not fehlt_de, fehlt_de)
check(f"{len(schluessel)} Schluessel auf EN vorhanden", not fehlt_en, fehlt_en)

print(f"\n\033[1mErgebnis: {ok}/{ok + fail}\033[0m")
sys.exit(1 if fail else 0)
