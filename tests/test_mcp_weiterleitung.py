#!/usr/bin/env python3
"""Waechter: die mcp-Bibliothek folgt keiner Weiterleitung auf einen fremden Host.

Code-Review 2026-11-01: ohne eigenes CA-Zertifikat baut die Bibliothek den
httpx-Client selbst (``mcp_client._tls_haken`` liefert ``{}``). Bis mcp 1.29.1
setzt ``create_mcp_http_client`` dabei ``follow_redirects=True``; httpx
entfernt beim Ursprungswechsel nur ``Authorization``, ein API-Schluessel unter
eigenem Header-Namen (``X-API-Key``) ging einer 307 auf einen fremden Host
hinterher. Erst 1.30.0 folgt nur innerhalb des Ursprungs. An den Raedern
gemessen (1.28.1/1.29.0/1.29.1: ja, 1.30.0: nein).

Gehalten wird hier die ZUSAGE der Installation: ``requirements.txt`` laesst
keine Fassung unter 1.30.0 zu, und ``requirements.lock`` pinnt keine.

    python3 tests/test_mcp_weiterleitung.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MINDEST = (1, 30, 0)

_ok = 0
_fail = 0


def check(cond, label):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}")


def _ver(s):
    return tuple(int(x) for x in s.split("."))


req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
zeilen = [z.split("#")[0].strip() for z in req.splitlines()]
mcp = [z for z in zeilen if re.match(r"^mcp\s*[<>=!~]", z)]
if len(mcp) != 1:
    print(f"ABBRUCH: {len(mcp)} mcp-Zeilen in requirements.txt (erwartet 1).", file=sys.stderr)
    raise SystemExit(2)
unten = re.findall(r">=\s*([0-9][0-9.]*)", mcp[0])
gleich = re.findall(r"==\s*([0-9][0-9.]*)", mcp[0])
grenze = unten or gleich
check(bool(grenze), f"requirements.txt nennt eine Untergrenze ({mcp[0]})")
if grenze:
    check(_ver(grenze[0]) >= MINDEST,
          f"Untergrenze {grenze[0]} >= {'.'.join(map(str, MINDEST))}")

lock = ROOT / "requirements.lock"
if lock.exists():
    pin = re.findall(r"^mcp==([0-9][0-9.]*)", lock.read_text(encoding="utf-8"), re.M)
    check(len(pin) == 1, f"requirements.lock pinnt mcp genau einmal ({pin})")
    if pin:
        check(_ver(pin[0]) >= MINDEST, f"gepinnte Fassung {pin[0]} >= Untergrenze")

print(f"\nBilanz: {_ok} OK, {_fail} FAIL")
sys.exit(0 if _fail == 0 else 1)
