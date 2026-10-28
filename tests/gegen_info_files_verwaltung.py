"""Gegenprobe zu test_info_files_verwaltung (Info-Dokumente verwalten, 2026-10-28).

Dreht je EINE Zusage in einer Plattenkopie zurueck und erwartet FAILs MIT
Bilanzzeile; stellt danach byte-gleich wieder her (md5). Laeuft ohne Bytecode
(gleich grosse Sabotage in derselben Sekunde liesse sonst eine .pyc stehen).
Exit 0 = alle beissen, 1 = mindestens eine zahnlos, 2 = Basis nicht gruen.
"""
import hashlib, os, re, subprocess, sys
from pathlib import Path

W = Path(__file__).resolve().parent.parent
IF = W / "backend/info_files.py"
MA = W / "backend/main.py"
I18N = W / "frontend/js/i18n.js"
TEST = "test_info_files_verwaltung.py"
DATEIEN = [IF, MA, I18N]
md5 = lambda p: hashlib.md5(p.read_bytes()).hexdigest()
vorher = {p: md5(p) for p in DATEIEN}
sich = {p: p.read_bytes() for p in DATEIEN}
env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")


def lauf():
    r = subprocess.run([sys.executable, str(W / "tests" / TEST)], capture_output=True,
                       text=True, env=env, timeout=300)
    m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout)
    return r.returncode, (int(m.group(2)) if m else None)


PROBEN = [
    ("Pfadanteil im Namen erlaubt", IF,
     '    if "/" in n or "\\\\" in n:\n        raise ValueError("Dateiname darf keinen Pfad enthalten")\n',
     ''),
    ("ersetzen wird ignoriert", IF,
     "    if ziel.exists() and not ersetzen:\n", "    if False:\n"),
    ("keine Groessengrenze", IF,
     "                if groesse > MAX_UPLOAD_BYTES:\n", "                if False:\n"),
    ("Zwischendatei bleibt nach Abbruch liegen", IF,
     "    finally:\n        if temp.exists():\n", "    finally:\n        if False:\n"),
    ("Loeschen ohne resolve-Schranke", IF,
     "    if not resolve(name):\n        return False\n", ""),
    ("DELETE nur an require_auth", MA,
     "async def info_files_delete(name: str, user: str = Depends(require_local_auth)):",
     "async def info_files_delete(name: str, user: str = Depends(require_auth)):"),
    ("Upload nur an require_auth", MA,
     "                            user: str = Depends(require_local_auth)):\n    \"\"\"Legt ein Info-Dokument ab",
     "                            user: str = Depends(require_auth)):\n    \"\"\"Legt ein Info-Dokument ab"),
    ("verwalten fuer jeden", MA,
     '"verwalten": _user_is_admin(user)})', '"verwalten": True})'),
    ("EN-Text fehlt", I18N,
     "        'portal.info_upload':       'Upload',\n", ""),
]

if {p[1] for p in PROBEN} - set(DATEIEN):
    print("ABBRUCH: Probe faesst eine ungesicherte Datei an"); sys.exit(2)

rc_ende = 1
try:
    rc, f = lauf()
    if rc != 0 or f != 0:
        print(f"ABBRUCH: Basis nicht gruen (rc={rc}, fail={f})"); sys.exit(2)
    print("Basis gruen.")
    gut = 0
    for name, datei, a, n in PROBEN:
        txt = sich[datei].decode()
        if txt.count(a) != 1:
            print(f"  VERFEHLT {name}: Anker {txt.count(a)}x"); continue
        datei.write_text(txt.replace(a, n, 1))
        try:
            rc, f = lauf()
        finally:
            datei.write_bytes(sich[datei])
        biss = rc == 1 and (f or 0) > 0
        gut += biss
        print(f"  {'OK     ' if biss else 'ZAHNLOS'} {name}: rc={rc} FAIL={f}")
    print(f"{gut} von {len(PROBEN)} beissen.")
    rc_ende = 0 if gut == len(PROBEN) else 1
finally:
    for p in DATEIEN:
        p.write_bytes(sich[p])
    print("byte-gleich:", all(md5(p) == vorher[p] for p in DATEIEN))
sys.exit(rc_ende)
