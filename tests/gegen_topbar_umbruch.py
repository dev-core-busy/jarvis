#!/usr/bin/env python3
"""Gegenproben zur Umbruch-Regel der Titelleisten.

Geprueft wird der STRUKTURELLE Waechter (`test_topbar_umbruch.py`) – er laeuft
ueberall und faengt eine neue Seite schon im Repo ab. Die WIRKUNG misst
`live_topbar_umbruch_dev.py` im echten Chrome; dafuer gibt es hier bewusst
keine Probe: ein Lauf dauert Minuten, und die Wirkung ist einmal live belegt.

Regeln aus dem Register als Code: jede angefasste Datei ist geprueft gesichert
(Exit 2), eine Laufmarke nimmt den Rueckstand eines abgeschossenen Laufs
zurueck, und ein gruener Basislauf ist Bedingung.
"""
from __future__ import annotations

import atexit
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ABL = Path.home() / ".gegen-topbar-umbruch"
MARKE = ABL / "LAUF"

DATEIEN = ["frontend/css/theme.css", "tests/test_topbar_umbruch.py",
           "tests/live_topbar_umbruch_dev.py"]
W = [sys.executable, str(ROOT / "tests" / "test_topbar_umbruch.py")]


def sichern():
    ABL.mkdir(parents=True, exist_ok=True)
    for rel in DATEIEN:
        shutil.copy2(ROOT / rel, ABL / rel.replace("/", "__"))
    MARKE.write_text("laeuft\n", encoding="utf-8")


def zurueck():
    for rel in DATEIEN:
        q = ABL / rel.replace("/", "__")
        if q.is_file():
            shutil.copy2(q, ROOT / rel)


def aufraeumen():
    zurueck()
    if MARKE.exists():
        MARKE.unlink()


if MARKE.exists():
    print("⚠ Rueckstand eines frueheren Laufs – wird zurueckgenommen.")
    zurueck(); MARKE.unlink()


def bewerte(cmd):
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=300)
    aus = p.stdout + p.stderr
    bil = [z for z in aus.splitlines() if "Ergebnis:" in z]
    if not bil:
        return True, "ABGEBROCHEN (keine Bilanz)"
    fails = sum(1 for z in aus.splitlines() if "✗" in z)
    return (p.returncode != 0), f"{bil[-1].strip()} / {fails} FAIL"


CSS = "frontend/css/theme.css"
TW = "tests/test_topbar_umbruch.py"
LW = "tests/live_topbar_umbruch_dev.py"

PROBEN = [
    ("flex-wrap-Regel der Leisten ganz raus", CSS,
     ".topbar, .wi-topbar, .pt-topbar, .sa-topbar, .ad-top { flex-wrap: wrap; }",
     "/* entfernt */", W),

    ("eine Leisten-Klasse faellt aus der Regel (die neue Seite von morgen)", CSS,
     ".topbar, .wi-topbar, .pt-topbar, .sa-topbar, .ad-top { flex-wrap: wrap; }",
     ".topbar, .pt-topbar, .sa-topbar, .ad-top { flex-wrap: wrap; }", W),

    ("min-width der Titel raus", CSS,
     ".topbar-title, .wi-title, .pt-title, .sa-title, .ad-title { min-width: 0; }",
     "/* entfernt */", W),

    ("Symbolgruppe bricht nicht mehr selbst um", CSS,
     """.topbar-right, .wi-top-icons, .pt-top-icons, .sa-top-icons, .ad-top-icons,
.topbar-left {
    flex-wrap: wrap;
}""", "/* entfernt */", W),

    # ⚠ Der Dialogkopf ist eine EINZELN begruendete Ausnahme – faellt die
    # Begruendung weg, meldet der Waechter ihn wieder.
    ("Dialogkopf-Ausnahme aufgehoben", TW,
     'LEISTEN_AUSNAHMEN = {"modal-header"}', "LEISTEN_AUSNAHMEN = set()", W),

    # ⚠ NICHT die Positivkontrolle schwaechen – dass ein Waechter geschwaecht
    # wurde, meldet nur ein Waechter darueber (Register). Hergestellt wird die
    # LAGE: findet der Parser keine Leisten, ist alles darunter trivial wahr.
    ("Parser findet keine Leiste mehr (Positivkontrolle muss melden)", TW,
     'if d.get("data-i18n-title") in ANKER and len(self.stapel) >= 3:',
     'if False and d.get("data-i18n-title") in ANKER and len(self.stapel) >= 3:', W),

    ("Anker zurueck auf den Theme-Knopf (erzeugt die Fehlalarme von 2026-09-22)", TW,
     'ANKER = {"nav.home", "chat.logout", "nav.logout", "portal.logout"}',
     'ANKER = {"nav.home", "chat.logout", "nav.logout", "portal.logout", "chat.theme"}', W),

    ("der Live-Waechter misst keinen Ueberlauf mehr", LW,
     "var ue=Math.max(d.scrollWidth-d.clientWidth,b.scrollWidth-b.clientWidth);",
     "var ue=0;", W),

    ("dem Live-Waechter fehlt die Referenzbreite", LW,
     "BREIT = 1400", "BREIT = 0", W),
]

fehlt = {rel for _, rel, *_ in PROBEN} - set(DATEIEN)
if fehlt:
    print(f"\033[31mABBRUCH:\033[0m nicht gesicherte Dateien: {sorted(fehlt)}")
    sys.exit(2)

sichern()
atexit.register(aufraeumen)
signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

print("\033[1mBasislauf\033[0m")
gemeldet, info = bewerte(W)
print(f"  test_topbar_umbruch: {info}")
if gemeldet:
    print("\033[31mABBRUCH:\033[0m Basis nicht gruen – Gegenproben waeren nicht deutbar")
    sys.exit(2)

print(f"\n\033[1m{len(PROBEN)} Gegenproben\033[0m")
beissen, stumm = 0, []
for name, rel, alt, neu, cmd in PROBEN:
    p = ROOT / rel
    s = p.read_text(encoding="utf-8")
    if s.count(alt) != 1:
        print(f"  \033[33m⚠\033[0m {name}: SABOTAGE TRIFFT NICHT ({s.count(alt)}x)")
        stumm.append(name + " (trifft nicht)")
        continue
    p.write_text(s.replace(alt, neu, 1), encoding="utf-8")
    try:
        g, info = bewerte(cmd)
    finally:
        zurueck()
    if g:
        beissen += 1
        print(f"  \033[32m✓\033[0m {name} → {info}")
    else:
        stumm.append(name)
        print(f"  \033[31m✗\033[0m {name} → BEISST NICHT ({info})")

abw = [rel for rel in DATEIEN
       if (ROOT / rel).read_bytes() != (ABL / rel.replace("/", "__")).read_bytes()]
print(f"\n\033[1mErgebnis: {beissen}/{len(PROBEN)} Proben beissen\033[0m")
print(f"Arbeitsbaum wiederhergestellt: {'ja' if not abw else 'NEIN – ' + str(abw)}")
if stumm:
    print("Stumm: " + "; ".join(stumm))
sys.exit(1 if (stumm or abw) else 0)
