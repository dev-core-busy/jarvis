#!/usr/bin/env python3
"""MESSUNG 2: Was kostet ein ZUGESCHNITTENER Werkzeugsatz?

Das ist die Kernfrage: die Werkzeug-Schemata sind mit 53k Zeichen der GROESSTE
Block je Anfrage. Schneidet man sie je Aufgabe zu, aendert sich das tools-Feld -
und damit womoeglich der Cache-Praefix. Gemessen mit den ECHTEN Schemata des
laufenden Agenten, nicht mit Attrappen.

  1 ALLE Werkzeuge, immer gleich          (heute)
  2 ALLE, aber Reihenfolge wechselt       (Kontrolle: reicht schon Umsortieren?)
  3 ZUGESCHNITTEN, je Aufgabe verschieden (die Idee)
  4 ZUGESCHNITTEN, stabile Teilmenge      (Zuschnitt je Konfiguration statt je Aufgabe)
"""
import json, time, urllib.request, sys, statistics, random
sys.path.insert(0, "/opt/jarvis")
from backend.config import config
from backend.agent import JarvisAgent
_p = config.active_profile or {}
_KEY = (_p.get("api_key") or "").strip()
URL = (_p.get("api_url") or "").rstrip("/") + "/chat/completions"
MODEL = _p.get("model") or ""

a = JarvisAgent()
def schema(t):
    return {"type": "function", "function": {
        "name": t.name, "description": getattr(t, "description", "") or "",
        "parameters": t.parameters_schema()}}
ALLE = []
for t in (a._tool_instances or []):
    try: ALLE.append(schema(t))
    except Exception: pass
SYS = a._base_system_prompt()
print(f"Werkzeuge: {len(ALLE)} | Schemata {len(json.dumps(ALLE, ensure_ascii=False))} Z. "
      f"| System-Prompt {len(SYS)} Z.")

def frage(tools, text):
    daten = json.dumps({"model": MODEL,
        "messages": [{"role": "system", "content": SYS}, {"role": "user", "content": text}],
        "tools": tools, "max_tokens": 8, "temperature": 0}).encode()
    req = urllib.request.Request(URL, data=daten, headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + _KEY})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.loads(r.read())
    return time.perf_counter() - t0, (d.get("usage") or {}).get("prompt_tokens", 0)

rnd = random.Random(7)
def gemischt():
    x = list(ALLE); rnd.shuffle(x); return x
def zugeschnitten():           # je Aufgabe eine andere Teilmenge
    x = list(ALLE); rnd.shuffle(x); return x[:12]
STABIL12 = ALLE[:12]           # immer dieselbe Teilmenge

VAR = {
  "1 alle, stabil (heute)        ": lambda: ALLE,
  "2 alle, Reihenfolge wechselt  ": gemischt,
  "3 zugeschnitten, je Aufgabe   ": zugeschnitten,
  "4 zugeschnitten, stabil       ": lambda: STABIL12,
}
for f in VAR.values():
    try: frage(f(), "Aufwaermen.")
    except Exception as e: print("FEHLER:", e); sys.exit(2)

N, mess, tok = 5, {k: [] for k in VAR}, {}
namen = list(VAR)
for runde in range(2):
    for k in (namen if runde == 0 else namen[::-1]):
        for i in range(N):
            dt, pt = frage(VAR[k](), f"Sage nur OK. ({runde}-{i})")
            mess[k].append(dt); tok[k] = pt
print()
basis = statistics.median(mess[namen[0]])
for k in namen:
    m = statistics.median(mess[k])
    print(f"{k}: median {m*1000:7.0f} ms | prompt_tokens {tok[k]:6d} | {(m-basis)/basis*100:+7.1f} %")
