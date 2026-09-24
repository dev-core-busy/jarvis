#!/usr/bin/env python3
"""LIVE auf DEV: liefert /api/wissen/scope den Ordnerbaum hierarchisch?

Reproduziert den gemeldeten Fehler am ECHTEN Endpunkt (nicht nur an der
geschnittenen Funktion) und belegt nach dem Fix die Behebung.

⚠ ES WERDEN LEERE TESTORDNER ANGELEGT und danach RESTLOS entfernt; der
vorgefundene Zustand wird vorher gemerkt und hinterher geprueft. Leere Ordner
erzeugen keine Index-Chunks, der Wissensbestand bleibt unberuehrt.

Aufruf auf DEV:  ./venv/bin/python /root/live_ordnerbaum_dev.py
"""
import json
import os
import shutil
import ssl
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, "/opt/jarvis")
os.chdir("/opt/jarvis")

WURZEL_REL = "data/rag/community"
BASIS = Path("/opt/jarvis") / WURZEL_REL

# Baum mit einem FRUEH einsortierten Ordner, der Kinder hat – nur daran wird
# der Unterschied sichtbar (ein Zweig ganz am Ende sieht zufaellig richtig aus).
BAUM = [
    "01 Systembasis",
    "04 Station",
    "04 Station/A Visite",
    "04 Station/B Kurve",
    "05 Arzt",
    "Vertraege",
    "Vertraege/01 Patientenfuehrung",
    "Vertraege/02 Administration",
]

_ok = _fail = 0


def check(t, b):
    global _ok, _fail
    if b:
        _ok += 1
        print(f"  OK   {t}")
    else:
        _fail += 1
        print(f"  FAIL {t}")


# ── Vorzustand merken ───────────────────────────────────────────────────────
if not BASIS.is_dir():
    print(f"WISSENSORDNER {BASIS} FEHLT – Messung nicht moeglich")
    sys.exit(2)
VORHER = sorted(p.name for p in BASIS.iterdir())
print(f"Vorgefunden in {WURZEL_REL}: {VORHER or '(leer)'}")

angelegt = []
try:
    for p in BAUM:
        z = BASIS / p
        if not z.exists():
            z.mkdir(parents=True)
            angelegt.append(z)

    from backend import main as m

    token = m.generate_token("jarvis")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request("https://127.0.0.1/api/wissen/scope",
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
        d = json.load(r)

    check("Endpunkt antwortet", bool(d.get("ok")))
    folders = d.get("folders") or []
    eigene = [f for f in folders if f["path"].startswith(WURZEL_REL)]
    # ⚠ Positivkontrolle: ohne gelieferte Unterordner waere jede Pruefung
    #   darunter trivial wahr.
    if len(eigene) < len(BAUM) + 1:
        print(f"  FAIL Endpunkt liefert den Testbaum nicht ({len(eigene)} Eintraege) –"
              f" Messung wertlos. Ist 'jarvis' Wissens-Editor?")
        _fail += 1
        raise SystemExit
    check(f"Testbaum kommt vollstaendig an ({len(eigene)} Eintraege)", True)

    rel = [f["path"][len(WURZEL_REL) + 1:] for f in eigene if f["depth"]]
    print()
    print("  ── so steht es im Pulldown ──")
    for f in eigene:
        if not f["depth"]:
            continue
        print("     " + "    " * (f["depth"] - 1) + f["name"])
    print()

    def eltern(p):
        return p.rsplit("/", 1)[0] if "/" in p else None

    vor_kind = [p for p in rel
                if eltern(p) and rel.index(eltern(p)) > rel.index(p)]
    check(f"jeder Ordner steht vor seinen Kindern"
          f"{'' if not vor_kind else ' – ' + str(vor_kind)}", not vor_kind)

    loecher = []
    for i, p in enumerate(rel):
        k = [j for j, q in enumerate(rel) if q.startswith(p + "/")]
        if k and sorted(k) != list(range(i + 1, i + 1 + len(k))):
            loecher.append(p)
    check(f"Teilbaeume zusammenhaengend{'' if not loecher else ' – ' + str(loecher)}",
          not loecher)

    soll = ["01 Systembasis", "04 Station", "04 Station/A Visite",
            "04 Station/B Kurve", "05 Arzt", "Vertraege",
            "Vertraege/01 Patientenfuehrung", "Vertraege/02 Administration"]
    check(f"exakter Baum{'' if rel == soll else f' – ist={rel}'}", rel == soll)

except SystemExit:
    pass
except Exception as e:  # noqa: BLE001
    _fail += 1
    print(f"  FAIL Messung wirft: {type(e).__name__}: {e}")
finally:
    # ── Abraeumen: NUR was diese Probe angelegt hat ─────────────────────────
    for z in sorted(angelegt, key=lambda p: len(p.parts), reverse=True):
        shutil.rmtree(z, ignore_errors=True)
    nachher = sorted(p.name for p in BASIS.iterdir())
    check(f"Ausgangszustand wiederhergestellt ({nachher or '(leer)'})",
          nachher == VORHER)

print()
print(f"ERGEBNIS: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
