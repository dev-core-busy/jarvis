#!/usr/bin/env python3
"""Gegenproben zu tests/test_container_akzent.py (Container-Titel beim
Ueberfahren in der Akzentfarbe, auf allen Seiten, auch kuenftigen).

Jede Probe dreht GENAU EINE Zusage zurueck und misst, ob der Waechter das
meldet. Harness wie gegen_wissensgraph.py: Sicherung, Laufmarke, gruener
Basislauf als Bedingung, ohne Bytecode.

    python3 tests/gegen_container_akzent.py
"""
from __future__ import annotations

import atexit
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ABL = Path.home() / ".gegen-container-akzent"
MARKE = ABL / "LAUF"

THEME = "frontend/css/theme.css"
EMAIL = "frontend/email.html"
PORTAL = "frontend/portal.html"
CRON = "frontend/js/cron.js"
DATEIEN = [THEME, EMAIL, PORTAL, CRON]

UMG = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
W = [sys.executable, str(ROOT / "tests" / "test_container_akzent.py")]


def sichern() -> None:
    ABL.mkdir(parents=True, exist_ok=True)
    for rel in DATEIEN:
        shutil.copy2(ROOT / rel, ABL / rel.replace("/", "__"))
    MARKE.write_text("laeuft\n", encoding="utf-8")


def zurueck() -> None:
    for rel in DATEIEN:
        q = ABL / rel.replace("/", "__")
        if q.is_file():
            shutil.copy2(q, ROOT / rel)


def aufraeumen() -> None:
    zurueck()
    if MARKE.exists():
        MARKE.unlink()


if MARKE.exists():
    print("⚠ Rueckstand eines frueheren Laufs gefunden – wird zurueckgenommen.")
    zurueck()
    MARKE.unlink()


def lauf(cmd) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=300, env=UMG)
    return p.returncode, p.stdout + p.stderr


def bilanz(aus: str) -> list[str]:
    return [z for z in aus.splitlines() if "ergebnis:" in z.lower()]


def bewerte(cmd) -> tuple[bool, str]:
    rc, aus = lauf(cmd)
    b = bilanz(aus)
    if not b:
        # Ein Abbruch ohne Bilanz ist KEIN Biss (Register).
        return False, f"ABGEBROCHEN rc={rc} (keine Bilanz)"
    fails = sum(1 for z in aus.splitlines() if "✗" in z)
    return (rc == 1 and fails > 0), f"{fails} FAIL · {b[-1].strip()}"


PROBEN = [
    ("Regel: dunkles Thema mit --accent pur (unlesbar auf dunklem Grund)", THEME,
     "    color: color-mix(in srgb, var(--accent) 65%, #fff);\n", "    color: var(--accent);\n", W),
    ("Regel: dunkles Thema zu wenig aufgehellt (80 %)", THEME,
     "    color: color-mix(in srgb, var(--accent) 65%, #fff);\n", "    color: color-mix(in srgb, var(--accent) 80%, #fff);\n", W),
    ("Regel: Container fehlt in der Liste (Claude)", THEME,
     "body :is(.ja-card-head, .em-card-head, .st-card-head, .cs-card-head, .kb-collapse-header):hover",
     "body :is(.ja-card-head, .em-card-head, .st-card-head, .kb-collapse-header):hover", W),
    ("Regel: helles Thema erfasst weniger als dunkles", THEME,
     "body.light :is(.ja-sect, .sp-sect, .vm-sect, .chs-sect, .sec-sub) > summary:hover",
     "body.light :is(.ja-sect, .sp-sect, .chs-sect, .sec-sub) > summary:hover", W),
    ("Regel: Titel h3 nicht erfasst (Einstellungen)", THEME,
     "body :is(.ja-card-head, .em-card-head, .st-card-head, .cs-card-head, .kb-collapse-header):hover > :is(h1, h2, h3, h4),",
     "body :is(.ja-card-head, .em-card-head, .st-card-head, .cs-card-head, .kb-collapse-header):hover > :is(h2),", W),
    ("Seite: Einzelregel kommt zurueck (zweite Quelle)", EMAIL,
     "        .em-card-head {", "        .em-card-head:hover h2 { color: var(--accent); }\n        .em-card-head {", W),
    ("Kuenftig: neuer Container auf einer Seite ohne Regel", PORTAL,
     "</body>", '<div class="neu-card-head" role="button" aria-expanded="true"><h2>Neu</h2></div>\n</body>', W),
    ("Kuenftig: neuer aufklappbarer Abschnitt ohne Regel", PORTAL,
     "</body>", '<details class="neu-sect"><summary>Neu</summary></details>\n</body>', W),
    ("Kuenftig: neuer Container per JavaScript-Vorlage", CRON,
     'class="kb-section-header kb-collapse-header" id="cron-sect-jobs-hdr"',
     'class="kb-section-header kb-collapse-header" id="cron-sect-jobs-hdr"></div><div class="neu2-sect-head"', W),
]

fehlt = {p[1] for p in PROBEN} - set(DATEIEN)
if fehlt:
    print(f"ABBRUCH: nicht gesicherte Dateien in den Proben: {sorted(fehlt)}")
    sys.exit(2)

sichern()
atexit.register(aufraeumen)
signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

print("Basislauf")
for cmd in (W,):
    rc, aus = lauf(cmd)
    b = bilanz(aus)
    print(f"  {Path(cmd[1]).stem}: {b[-1].strip() if b else 'KEINE BILANZ'}")
    if rc != 0 or not b:
        print("ABBRUCH: Basis nicht gruen – Gegenproben waeren nicht deutbar")
        sys.exit(2)

print(f"\n{len(PROBEN)} Gegenproben")
beissen, stumm = 0, []
for name, rel, alt, neu, cmd in PROBEN:
    p = ROOT / rel
    s = p.read_text(encoding="utf-8")
    if s.count(alt) != 1:
        print(f"  ⚠ {name}: SABOTAGE TRIFFT NICHT ({s.count(alt)}x) – Probe unbrauchbar")
        stumm.append(name + " (trifft nicht)")
        continue
    p.write_text(s.replace(alt, neu, 1), encoding="utf-8")
    try:
        gemeldet, info = bewerte(cmd)
    finally:
        zurueck()
    if gemeldet:
        beissen += 1
        print(f"  ✓ {name} → {info}")
    else:
        stumm.append(name)
        print(f"  ✗ {name} → BEISST NICHT ({info})")

abweichend = [rel for rel in DATEIEN
              if (ROOT / rel).read_bytes() != (ABL / rel.replace("/", "__")).read_bytes()]
print(f"\nErgebnis: {beissen}/{len(PROBEN)} Proben beissen")
print(f"Arbeitsbaum wiederhergestellt: {'ja' if not abweichend else 'NEIN – ' + str(abweichend)}")
if stumm:
    print("Stumm: " + "; ".join(stumm))
sys.exit(1 if (stumm or abweichend) else 0)
