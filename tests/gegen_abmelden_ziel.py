#!/usr/bin/env python3
"""Gegenprobe zu tests/test_abmelden_ziel.js: beisst der Waechter?

Zwei Arten von Proben:
* ALTSTAND: eine der am 2026-11-18 korrigierten Dateien wird auf ihren Stand
  VOR der Korrektur zurueckgesetzt (Commit 39f26608) – genau der gemeldete
  Fehler muss als FAIL erscheinen.
* SABOTAGE: eine Zeile in einem Modul, das schon vorher richtig war, wird
  gezielt verdorben (anderes Ziel, Server-Abmeldung entfernt).

Vorher gruener Basislauf, danach Byte-Gleichheit per md5; ein Rueckstand
eines abgebrochenen Laufs wird beim Start aus der Sicherung zurueckgelegt.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_abmelden_ziel.js"
SICHERUNG = Path.home() / ".gegen_abmelden_sicherung"
ALTSTAND = "39f26608"   # letzter Stand vor der Korrektur

ALT = ["frontend/js/chat.js", "frontend/js/userchat.js", "frontend/js/support.js",
       "frontend/js/security_incidents.js", "frontend/js/claude_portal.js",
       "frontend/js/sql.js", "frontend/js/tracks.js"]
SABOTAGE = [
    ("Kopfzeile fuehrt auf /chat", "frontend/js/kopfzeile.js",
     "p.catch(function () {}).then(function () { location.replace('/'); });",
     "p.catch(function () {}).then(function () { location.replace('/chat'); });"),
    ("AI-Maus ohne Server-Abmeldung", "frontend/js/ai_mouse.js",
     "fetch('/api/logout', {", "fetch('/api/abmelden-gibt-es-nicht', {"),
    ("Portal laedt neu statt '/'", "frontend/js/portal_seite.js",
     "_p.catch(function(){}).then(function(){ window.location.replace('/'); });",
     "_p.catch(function(){}).then(function(){ window.location.reload(); });"),
]
DATEIEN = sorted(set(ALT) | {s[1] for s in SABOTAGE})


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def lauf() -> tuple[int, str]:
    r = subprocess.run(["node", str(WAECHTER)], cwd=ROOT, capture_output=True, text=True, timeout=120)
    zeile = next((z for z in reversed(r.stdout.splitlines()) if z.startswith("Ergebnis")), "")
    return r.returncode, zeile


def zurueck() -> None:
    if not SICHERUNG.exists():
        return
    for rel in DATEIEN:
        q = SICHERUNG / rel
        if q.exists():
            shutil.copy2(q, ROOT / rel)
    shutil.rmtree(SICHERUNG)


def altstand(rel: str) -> str | None:
    r = subprocess.run(["git", "show", "%s:%s" % (ALTSTAND, rel)], cwd=ROOT,
                       capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def main() -> int:
    zurueck()
    for name, rel, alt, neu in SABOTAGE:
        n = (ROOT / rel).read_text(encoding="utf-8").count(alt)
        if n != 1:
            print("ABBRUCH: Anker %dx gefunden – %s" % (n, name))
            return 2
    alte = {rel: altstand(rel) for rel in ALT}
    if any(v is None for v in alte.values()):
        print("ABBRUCH: Altstand %s nicht lesbar." % ALTSTAND)
        return 2
    for rel, t in alte.items():
        if t == (ROOT / rel).read_text(encoding="utf-8"):
            print("ABBRUCH: %s ist unveraendert gegenueber %s – Probe waere leer." % (rel, ALTSTAND))
            return 2
    code, zeile = lauf()
    if code != 0:
        print("ABBRUCH: Basislauf nicht gruen (%s, Exit %d)" % (zeile, code))
        return 2
    print("Basislauf gruen: " + zeile)
    vorher = {rel: md5(ROOT / rel) for rel in DATEIEN}
    SICHERUNG.mkdir(mode=0o700)
    for rel in DATEIEN:
        (SICHERUNG / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, SICHERUNG / rel)
    proben = [("Altstand " + rel.split("/")[-1], rel, None, alte[rel]) for rel in ALT] + \
             [(n, r, a, b) for n, r, a, b in SABOTAGE]
    stumm = []
    try:
        for name, rel, alt, neu in proben:
            pfad = ROOT / rel
            original = pfad.read_text(encoding="utf-8")
            pfad.write_text(neu if alt is None else original.replace(alt, neu), encoding="utf-8")
            try:
                code, zeile = lauf()
            finally:
                pfad.write_text(original, encoding="utf-8")
            biss = code == 1 and bool(zeile)
            print("%s  %-40s %s (Exit %d)" % ("BEISST" if biss else "STUMM ", name, zeile, code))
            if not biss:
                stumm.append(name)
    finally:
        zurueck()
    if {rel: md5(ROOT / rel) for rel in DATEIEN} != vorher:
        print("FEHLER: Dateien nach der Gegenprobe nicht byte-gleich!")
        return 2
    print("\nDateien byte-gleich wiederhergestellt.")
    print("Bilanz: %d von %d Proben beissen" % (len(proben) - len(stumm), len(proben)))
    return 0 if not stumm else 1


if __name__ == "__main__":
    sys.exit(main())
