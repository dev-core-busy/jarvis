#!/usr/bin/env python3
"""Live auf DEV: das Verbinden einer Freigabe leert den Wissens-Index nicht.

Aufruf auf dem Server, als Dienstbenutzer im Produktiv-venv:

    cd /opt/jarvis && PYTHONPATH=/opt/jarvis HOME=/home/jarvis \\
      runuser -u jarvis --preserve-environment -- \\
      ./venv/bin/python tests/live_reindex_mount_dev.py [freigabe-index]

⚠ DER FUELLSTAND WIRD BEIM DIENST ERFRAGT, NICHT IN DIESEM PROZESS.
Der erste Anlauf pollte `vs.chunk_count()` einer EIGENEN VectorStore-Instanz -
die tut waehrend des Dienst-Laufs gar nichts, der Wert war trivial konstant und
bewies nichts. Gemessen wird ueber `GET /api/knowledge/stats`, also die Instanz,
die der Reindex wirklich anfasst.

Gegenprobe mit dem Altstand (`force_reindex` ohne `incremental` in
`mount_share`), am 2026-09-07 auf DEV gefahren: der Index fiel beim ZWEITEN
Messpunkt von 2737 auf 0 und war nach 600 s immer noch leer - die Wissenssuche
war in dieser Zeit tot. Mit dem Fix: 8 Messpunkte, konstant 2737, nach 3,4 s
fertig.
"""
import sys
import threading
import time

import urllib3
import requests

urllib3.disable_warnings()
sys.argv = ["live_reindex_mount_dev"]
from backend import main as M            # noqa: E402

IDX = int(sys.argv[1]) if len(sys.argv) > 1 else 1
BASIS = "https://127.0.0.1"
_ok = _fail = 0


def p(text: str, cond, zusatz: str = "") -> None:
    global _ok, _fail
    try:
        wahr = bool(cond)
    except Exception as e:                # noqa: BLE001
        print(f"FAIL {text}  [Bedingung wirft: {e}]")
        _fail += 1
        return
    print(("OK   " if wahr else "FAIL ") + text + (f"  [{zusatz}]" if zusatz else ""))
    _ok += wahr
    _fail += not wahr


kopf = {"Authorization": f"Bearer {M.generate_token('jarvis')}"}


def stats() -> int:
    d = requests.get(f"{BASIS}/api/knowledge/stats", headers=kopf,
                     verify=False, timeout=20).json()
    for feld in ("total_chunks", "chunks", "vector_chunks"):
        if feld in d:
            return int(d[feld] or 0)
    return -1


def gemountet() -> bool:
    with open("/proc/mounts", encoding="utf-8") as fh:
        return f"/mnt/jarvis-kb/share_{IDX}" in fh.read()


start = stats()
if start <= 0:
    print(f"ABBRUCH: Dienst meldet {start} Chunks - ohne Bestand misst die Probe "
          f"nichts (ein leerer Index kann nicht leerer werden).")
    raise SystemExit(2)
print(f"Dienst meldet vorher: {start} Chunks, Freigabe {IDX} gemountet={gemountet()}")

tief = [start]
werte: list[int] = []
laeuft = threading.Event()
laeuft.set()


def poll() -> None:
    while laeuft.is_set():
        try:
            c = stats()
            werte.append(c)
            tief[0] = min(tief[0], c)
        except Exception:                 # noqa: BLE001
            pass
        time.sleep(0.4)


t = threading.Thread(target=poll, daemon=True)
t.start()

t0 = time.time()
r = requests.post(f"{BASIS}/api/knowledge/mounts/{IDX}/mount", headers=kopf,
                  verify=False, timeout=180)
antwortzeit = time.time() - t0
print(f"\nHTTP {r.status_code} in {antwortzeit:.1f} s: {r.text[:180]}")

# Hintergrund-Reindex abwarten - der Fortschritt wird beim DIENST erfragt.
ende = time.time() + 900
lief_mal = False
while time.time() < ende:
    try:
        pr = requests.get(f"{BASIS}/api/knowledge/index_progress", headers=kopf,
                          verify=False, timeout=20).json()
    except Exception:                     # noqa: BLE001
        break
    if pr.get("running"):
        lief_mal = True
    elif lief_mal:
        break
    time.sleep(1)
time.sleep(2)
laeuft.clear()
t.join(timeout=3)
gesamt = time.time() - t0
nachher = stats()

print(f"\nNachher: {nachher} Chunks   Tiefpunkt: {tief[0]}   "
      f"({len(werte)} Messpunkte, {gesamt:.1f} s)")

p("Endpunkt antwortet mit 200", r.status_code == 200)
p("Endpunkt haengt nicht (Reindex laeuft im Hintergrund)",
  antwortzeit < 60, f"{antwortzeit:.1f} s")
p("mehr als ein Messpunkt - sonst misst der Poll nichts", len(werte) >= 2,
  f"{len(werte)}")
p("DER INDEX WAR ZU KEINEM ZEITPUNKT LEER", tief[0] > 0, f"min={tief[0]}")
p("der Fuellstand bricht nicht ein", tief[0] >= start * 0.9,
  f"{tief[0]} von {start}")
p("Bestand danach unveraendert oder groesser", nachher >= start,
  f"{start} -> {nachher}")
p("kein Neu-Einbetten des ganzen Bestands (unter 120 s)", gesamt < 120,
  f"{gesamt:.1f} s")
p(f"Freigabe {IDX} ist danach wieder eingehaengt", gemountet())

print(f"\n{_ok} OK, {_fail} FAIL")
raise SystemExit(1 if _fail else 0)
