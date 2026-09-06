#!/bin/bash
# Misst, ob die Werkzeug-Buendel richtig geschnitten sind.
#
# ⚠ JEDER werkzeuge_anfordern-Aufruf ist ein Buendel, das zu eng war. Die Zahl
# ist die Messgrundlage fuer den Zuschnitt - nicht das Bauchgefuehl. Rein
# lesend; als Dienstbenutzer aufrufen (das Audit-Log ist 0640 jarvis:jarvis):
#
#   sudo -u jarvis bash deploy/buendel_zaehlen.sh [TAGE]
#
TAGE=${1:-7}
Z=${JARVIS_DIR:-/opt/jarvis}
"$Z/venv/bin/python" - "$TAGE" "$Z" <<'PYEOF'
import collections, json, sys, time
tage = float(sys.argv[1]); zh = sys.argv[2]
seit = time.time() - tage * 86400
ruf = collections.Counter(); nach = []
# ⚠ ZWEI DINGE, die die Zahl sonst falsch machen:
#  - `[task]` ist KEIN Werkzeug-Aufruf, sondern eine Zeile je Anfrage
#    (audit_log.log_task). Mitgezaehlt waere die Gesamtzahl zu hoch und der
#    Prozentsatz des Rueckwegs zu niedrig - also genau die Kennzahl verfaelscht,
#    wegen der es dieses Skript gibt.
#  - `read_log()` liest auch die rotierte `.bak`; wer nur die aktive Datei
#    nimmt, verliert bei Altbestand einen Teil des Zeitraums.
dateien = [f"{zh}/data/logs/audit.jsonl", f"{zh}/data/logs/audit.jsonl.bak"]
gefunden = False
for pfad in dateien:
    try:
        f = open(pfad, encoding="utf-8")
    except FileNotFoundError:
        continue
    gefunden = True
    with f:
        for z in f:
            try: e = json.loads(z)
            except Exception: continue
            if float(e.get("ts") or 0) < seit: continue
            t = e.get("tool") or ""
            if not t or t == "[task]":
                continue
            ruf[t] += 1
            if t == "werkzeuge_anfordern":
                nach.append(e)
if not gefunden:
    print("kein Audit-Log gefunden"); raise SystemExit(2)
gesamt = sum(ruf.values())
n = ruf.get("werkzeuge_anfordern", 0)
print(f"Zeitraum: {tage:g} Tage")
print(f"  Werkzeug-Aufrufe gesamt : {gesamt}")
print(f"  davon werkzeuge_anfordern: {n}" + (f"  ({n/gesamt*100:.1f} %)" if gesamt else ""))
if nach:
    print("\n  Diese Buendel waren zu eng (Grund, den das Modell genannt hat):")
    g = collections.Counter((e.get("args") or {}).get("grund") or "(ohne Grund)" for e in nach)
    for grund, k in g.most_common(15):
        print(f"    {k:3d}x  {grund[:78]}")
    print("\n  -> Wiederkehrende Gruende gehoeren als Werkzeug in das passende")
    print("     Buendel (backend/werkzeug_buendel.py) oder brauchen ein Muster.")
else:
    print("\n  -> kein Nachladen noetig gewesen: die Buendel passen bisher.")
print("\n  Meistbenutzte Werkzeuge:")
for t, k in ruf.most_common(10):
    print(f"    {k:5d}x {t}")
PYEOF
