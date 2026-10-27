#!/usr/bin/env python3
"""Waechter: Skill-Locks (skills/<name>/requirements.lock) passen zu Manifest und Kern-Lock.

Hintergrund (BSI-Abgleich 2026-10-27): die Manifest-`dependencies` nennen nur
Versionen; die Kernpakete installiert die Lock mit `--require-hashes`. Eine
Skill-Lock schliesst diese Luecke – der Server installiert daraus nur Fehlendes
mit `--no-deps --require-hashes`. Das traegt nur, wenn die Datei stimmt:

  1. REGEL: ein Skill, dessen `dependencies` ALLE exakt festgelegt sind (`==`
     oder `name @ url`), hat eine Skill-Lock. Wer pinnt, will einen festen Stand
     – ohne Lock waere er nur halb fest (keine Pruefsummen, transitive frei).
     Skills mit offenen Grenzen (`>=`, ohne Version) fallen bewusst NICHT
     darunter: dort wird beim Einschalten aufgeloest, eine Lock waere ein
     Versionssprung (Rueckstand, benannt statt verschwiegen).
  2. Jeder Eintrag traegt mindestens einen Hash – sonst lehnt pip mit
     `--require-hashes` die GANZE Datei ab, und zwar erst auf dem Server.
  3. Jede Manifest-Abhaengigkeit ist durch die Lock erfuellt; bei `name @ url`
     ist die Adresse dieselbe und der Hash der aus ihrem `#sha256=`.
  4. Jedes Paket, das auch in requirements.lock steht, hat DORT dieselbe
     Version – sonst wuerde eine Installation ein Kernpaket bewegen wollen.
  5. Kopf nennt den erzeugenden Befehl (`deploy/lock_erneuern.py --skill`).

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK = FAIL = 0


def check(name, bed, detail=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (" – " + str(detail) if detail else ""))


def abbruch(grund):
    print("ABBRUCH (Exit 2): " + grund)
    sys.exit(2)


try:
    from packaging.requirements import Requirement
    from packaging.version import Version
    from backend import abhaengigkeiten as A
except Exception as e:  # noqa: BLE001
    abbruch(f"packaging/abhaengigkeiten nicht ladbar: {e}")


def norm(n):
    return re.sub(r"[-_.]+", "-", n).lower()


def versionen(text):
    return {norm(m.group(1)): m.group(2) for z in text.splitlines()
            if (m := re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+)", z))}


def exakt(spec):
    try:
        r = Requirement(spec)
    except Exception:  # noqa: BLE001
        return False
    if r.url:
        return True
    ops = [s.operator for s in r.specifier]
    return ops == ["=="]


KERN = (ROOT / "requirements.lock").read_text(encoding="utf-8")
kern = versionen(KERN)
if len(kern) < 50:
    abbruch(f"requirements.lock zu klein gelesen ({len(kern)} Pakete) – Leser kaputt?")

skills = []
for mf in sorted((ROOT / "skills").glob("*/skill.json")):
    deps = json.loads(mf.read_text(encoding="utf-8")).get("dependencies") or []
    skills.append((mf.parent.name, deps))

print("\n── 1. Regel: exakt festgelegte Skills haben eine Lock")
pflicht = [s for s, d in skills if d and all(exakt(x) for x in d)]
check("Positivkontrolle: ai_mouse gilt als exakt festgelegt", "ai_mouse" in pflicht, pflicht)
check("Positivkontrolle: vision (>=) gilt NICHT als exakt", "vision" not in pflicht, pflicht)
for s in pflicht:
    check(f"{s}: skills/{s}/requirements.lock vorhanden",
          (ROOT / "skills" / s / "requirements.lock").is_file())

locks = sorted((ROOT / "skills").glob("*/requirements.lock"))
if not locks:
    abbruch("keine einzige Skill-Lock gefunden – Regel 2-5 waeren trivial wahr")

for lk in locks:
    s = lk.parent.name
    text = lk.read_text(encoding="utf-8")
    bl = A.lock_bloecke(text)
    ver = versionen(text)
    deps = dict(skills).get(s, [])
    print(f"\n── {s}: {len(bl)} Eintraege")
    check(f"{s}: Positivkontrolle – Eintraege gelesen", len(bl) >= len(deps) > 0, len(bl))
    ohne = [n for n, b in bl.items() if "--hash=sha256:" not in b]
    check(f"{s}: jeder Eintrag mit Hash", not ohne, ohne)
    for d in deps:
        r = Requirement(d)
        n = norm(r.name)
        if r.url:
            frag = re.search(r"#sha256=([0-9a-f]{64})", r.url)
            b = bl.get(n, "")
            check(f"{s}: {r.name} @ url – dieselbe Adresse und ihr Hash",
                  b.startswith(f"{r.name} @ {r.url}") and frag is not None
                  and f"--hash=sha256:{frag.group(1)}" in b, b[:160])
        else:
            v = ver.get(n)
            check(f"{s}: {d} erfuellt (Lock: {v})",
                  v is not None and r.specifier.contains(Version(v), prereleases=True), v)
    abw = sorted((n, v, kern[n]) for n, v in ver.items() if n in kern and kern[n] != v)
    check(f"{s}: Kernpakete in derselben Version wie requirements.lock", not abw, abw)
    check(f"{s}: Kopf nennt den Erzeuger",
          f"deploy/lock_erneuern.py --skill {s}" in text.split("\n", 1)[0], text[:120])

print("\n" + "=" * 60)
print(f"Ergebnis: {OK} OK, {FAIL} FAIL")
print("=" * 60)
sys.exit(0 if FAIL == 0 else 1)
