#!/usr/bin/env python3
"""Gegenproben zur gemeinsamen Wissensgruppen-Normierung.

Jede Probe dreht GENAU EINE Zusage zurueck und misst, ob der Waechter das
meldet. Eine Probe, die nicht beisst, ist ein Testmangel – kein Beweis; oder
die Zusage existiert gar nicht, dann gehoert die Probe gestrichen und nicht
der Waechter geschaerft (am 2026-09-16 am `strip()`-Kommentar bezahlt).

Drei Regeln aus dem Register, hier als CODE statt als Vorsatz: jede angefasste
Datei steht geprueft in der Sicherung (Exit 2), eine Laufmarke nimmt den
Rueckstand eines abgeschossenen Laufs beim naechsten Start zurueck, und ein
gruener Basislauf ist Bedingung – ohne ihn ist keine Gegenprobe deutbar.
"""
from __future__ import annotations

import atexit
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ABL = Path.home() / ".gegen-gruppen-normierung"
MARKE = ABL / "LAUF"

DATEIEN = ["backend/main.py", "tests/test_gruppen_normierung.py"]

W = [sys.executable, str(ROOT / "tests" / "test_gruppen_normierung.py")]
W_CF = [sys.executable, str(ROOT / "tests" / "test_cf_bindung.py")]


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
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=300)
    return p.returncode, p.stdout + p.stderr


def bewerte(cmd) -> tuple[bool, str]:
    rc, aus = lauf(cmd)
    bilanz = [z for z in aus.splitlines() if "Ergebnis:" in z]
    if not bilanz:
        return True, "ABGEBROCHEN (keine Bilanz)"
    fails = sum(1 for z in aus.splitlines() if "✗" in z)
    return (rc != 0), f"{bilanz[-1].strip()} / {fails} FAIL"


MAIN = "backend/main.py"
TW = "tests/test_gruppen_normierung.py"

NORM_ECHT = """    if not isinstance(werte, list):
        return []
    return [g.strip() for g in werte if isinstance(g, str) and g.strip()]"""

PROBEN = [
    # (Name, Datei, alt, neu, Waechter)
    ("Helfer filtert nur auf Falsyness (der gemeldete Fall)", MAIN, NORM_ECHT,
     """    if not isinstance(werte, list):
        return []
    return [g for g in werte if isinstance(g, str) and g]""", W),

    ("Helfer wandelt Nicht-Strings um, statt zu verwerfen", MAIN, NORM_ECHT,
     """    if not isinstance(werte, list):
        return []
    return [str(g).strip() for g in werte if str(g).strip()]""", W),

    ("Helfer trimmt nicht (Leerraum bleibt am Wert)", MAIN, NORM_ECHT,
     """    if not isinstance(werte, list):
        return []
    return [g for g in werte if isinstance(g, str) and g.strip()]""", W),

    ("Helfer dedupliziert (nicht bestellt)", MAIN, NORM_ECHT,
     """    if not isinstance(werte, list):
        return []
    return list(dict.fromkeys(g.strip() for g in werte
                              if isinstance(g, str) and g.strip()))""", W),

    ("Helfer nimmt eine Zeichenkette als Liste", MAIN, NORM_ECHT,
     """    if werte is None:
        return []
    return [g.strip() for g in werte if isinstance(g, str) and g.strip()]""", W),

    ("Entwurfs-Freigabe zurueck auf die alte Fassung",
     MAIN,
     '    req_groups = _gruppen_normieren(body.get("groups") if isinstance(body, dict) else None)\n'
     '    ok, err = _wissen_check_groups(user, req_groups)',
     '    req_groups = [g for g in ((body.get("groups") if isinstance(body, dict) else None) or []) if g]\n'
     '    ok, err = _wissen_check_groups(user, req_groups)', W),

    ("Zuordnungs-Endpunkt normiert nicht mehr", MAIN,
     "    groups = _gruppen_normieren(groups)\n", "", W),

    ("Typpruefung im Zuordnungs-Endpunkt entfernt", MAIN,
     '    if not isinstance(groups, list):\n'
     '        return JSONResponse({"ok": False, "error": "groups muss eine Liste sein"}, status_code=400)\n',
     "", W),

    ("Docstring-Filter des Waechters ausgebaut", TW,
     "NACKT = _ohne_worte(QUELLE)", "NACKT = QUELLE", W),

    # ⚠ NICHT die Positivkontrolle selbst schwaechen – dass ein Waechter
    # geschwaecht wurde, kann nur ein Waechter UEBER dem Waechter melden
    # (Register). Hergestellt wird die LAGE, die sie abfangen soll: findet die
    # Regel keine Stellen mehr, ist sie trivial wahr – und genau das muss die
    # Positivkontrolle sagen.
    ("Regel findet keine Stellen mehr (Positivkontrolle muss melden)", TW,
     "def liest_rumpf_groups(knoten) -> bool:\n    for n in ast.walk(knoten):",
     "def liest_rumpf_groups(knoten) -> bool:\n    return False\n    for n in ast.walk(knoten):", W),

    # Der CF-Waechter muss die Verdrahtung ebenfalls halten.
    # Anker seit fabf66c (Einbindung als Baum): die Normierung steht jetzt vor
    # dem Rueckgabe-Tupel des gemeinsamen Pruefschritts.
    ("CF-Endpunkt umgeht die gemeinsame Normierung", MAIN,
     '    req_groups = _gruppen_normieren(body.get("groups"))\n'
     '    ok, err = _wissen_check_groups(user, req_groups)\n'
     '    if not ok:\n'
     '        return (JSONResponse(',
     '    req_groups = [g for g in (body.get("groups") or []) if g]\n'
     '    ok, err = _wissen_check_groups(user, req_groups)\n'
     '    if not ok:\n'
     '        return (JSONResponse(', W_CF),
]

# ── Regel: jede angefasste Datei ist gesichert ──────────────────────────────
fehlt = {rel for _, rel, *_ in PROBEN} - set(DATEIEN)
if fehlt:
    print(f"\033[31mABBRUCH:\033[0m nicht gesicherte Dateien in den Proben: {sorted(fehlt)}")
    sys.exit(2)

sichern()
atexit.register(aufraeumen)
signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

# ── Basislauf ───────────────────────────────────────────────────────────────
print("\033[1mBasislauf\033[0m")
for cmd, name in ((W, "test_gruppen_normierung"), (W_CF, "test_cf_bindung")):
    rc, aus = lauf(cmd)
    bil = [z for z in aus.splitlines() if "Ergebnis:" in z]
    print(f"  {name}: {bil[-1].strip() if bil else 'KEINE BILANZ'}")
    if rc != 0 or not bil:
        print("\033[31mABBRUCH:\033[0m Basis nicht gruen – Gegenproben waeren nicht deutbar")
        sys.exit(2)

print(f"\n\033[1m{len(PROBEN)} Gegenproben\033[0m")
beissen, stumm = 0, []
for name, rel, alt, neu, cmd in PROBEN:
    p = ROOT / rel
    s = p.read_text(encoding="utf-8")
    if s.count(alt) != 1:
        print(f"  \033[33m⚠\033[0m {name}: SABOTAGE TRIFFT NICHT ({s.count(alt)}x) – Probe unbrauchbar")
        stumm.append(name + " (trifft nicht)")
        continue
    p.write_text(s.replace(alt, neu, 1), encoding="utf-8")
    try:
        gemeldet, info = bewerte(cmd)
    finally:
        zurueck()
    if gemeldet:
        beissen += 1
        print(f"  \033[32m✓\033[0m {name} → {info}")
    else:
        stumm.append(name)
        print(f"  \033[31m✗\033[0m {name} → BEISST NICHT ({info})")

abweichend = [rel for rel in DATEIEN
              if (ROOT / rel).read_bytes() != (ABL / rel.replace("/", "__")).read_bytes()]
print(f"\n\033[1mErgebnis: {beissen}/{len(PROBEN)} Proben beissen\033[0m")
print(f"Arbeitsbaum wiederhergestellt: {'ja' if not abweichend else 'NEIN – ' + str(abweichend)}")
if stumm:
    print("Stumm: " + "; ".join(stumm))
sys.exit(1 if (stumm or abweichend) else 0)
