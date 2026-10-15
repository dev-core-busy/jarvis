"""Gegenprobe zu test_doc_delivery / test_bild_anzeige / test_bild_chip_ui (Bild-Chip, 2026-10-12).

Dreht je EINEN der drei Fixes in einer Plattenkopie zurueck und erwartet
FAILs MIT Bilanzzeile; stellt danach byte-gleich wieder her (md5).
Exit 0 = alle beissen, 1 = mindestens eine zahnlos, 2 = Basis nicht gruen.
"""
import hashlib, os, re, shutil, subprocess, sys
from pathlib import Path

W = Path(__file__).resolve().parent.parent
AG = W / "backend/agent.py"
CL = W / "frontend/js/chatlib.js"
DATEIEN = [AG, CL]
md5 = lambda p: hashlib.md5(p.read_bytes()).hexdigest()
vorher = {p: md5(p) for p in DATEIEN}
sich = {p: p.read_bytes() for p in DATEIEN}
env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")

def lauf(test):
    cmd = ["node", str(W / "tests" / test)] if test.endswith(".js") else [sys.executable, str(W / "tests" / test)]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=300)
    m = re.search(r"(\d+) (?:ok|OK), (\d+) (?:Fehler|FAIL)", r.stdout)
    return r.returncode, (int(m.group(2)) if m else None)

PROBEN = [
    ("Bild ohne Chip (agent._emit)", AG,
     'md = f"![{name}]({url})\\n{chip}" if ext in _IMG_EXT else chip',
     'md = f"![{name}]({url})" if ext in _IMG_EXT else chip', "test_doc_delivery.py"),
    ("Bild-Verweis laesst '!Label' stehen (_clean_doc_refs)", AG,
     'lambda m: "" if m.group(1) else m.group(2), text)',
     'lambda m: m.group(2), text)', "test_bild_anzeige.py"),
    ("Chip-Regel ohne Bildendungen (chatlib)", CL,
     "pptx|pdf|png|jpe?g|gif|webp|bmp|svg))\\)/g,", "pptx|pdf))\\)/g,", "test_bild_chip_ui.js"),
]
rc_ende = 1
try:
    for _, _, _, _, t in PROBEN:
        rc, f = lauf(t)
        if rc != 0 or f != 0:
            print(f"ABBRUCH: Basis {t} nicht gruen (rc={rc}, fail={f})"); sys.exit(2)
    print("Basis gruen.")
    gut = 0
    for name, datei, a, n, t in PROBEN:
        txt = sich[datei].decode()
        if txt.count(a) != 1:
            print(f"  VERFEHLT {name}: Anker {txt.count(a)}x"); continue
        datei.write_text(txt.replace(a, n, 1))
        try:
            rc, f = lauf(t)
        finally:
            datei.write_bytes(sich[datei])
        biss = rc == 1 and (f or 0) > 0
        gut += biss
        print(f"  {'OK     ' if biss else 'ZAHNLOS'} {name}: {t} rc={rc} FAIL={f}")
    print(f"{gut} von {len(PROBEN)} beissen.")
    rc_ende = 0 if gut == len(PROBEN) else 1
finally:
    for p in DATEIEN:
        p.write_bytes(sich[p])
    print("byte-gleich:", all(md5(p) == vorher[p] for p in DATEIEN))
sys.exit(rc_ende)
