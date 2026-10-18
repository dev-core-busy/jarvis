#!/usr/bin/env python3
"""Waechter: Shell-Befehle haben eine ABSOLUTE Frist, einen Mengendeckel und
sterben mit dem Stopp-Knopf (Code-Review 2026-10-18).

Gemessen an ``ShellTool._lesen`` mit ECHTEN Prozessen (eigene Prozessgruppe,
wie im Werkzeug):
  [1] Ein Befehl, der alle 0,3 s eine Zeile schreibt, endet nach der Frist –
      vorher galt der Zeitdeckel je Zeile, er lief unbegrenzt. Der Prozess
      ist danach weg.
  [2] 5 MB Ausgabe: gesammelt hoechstens SAMMEL_MAX, Kuerzung gemeldet.
  [3] Statuszeilen gebuendelt: 2000 Zeilen in kurzer Zeit -> wenige Rueckrufe.
  [4] Abbrechen des Laufs (CancelledError) beendet den Prozessbaum.
Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
import asyncio
import os
import sys
import time
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
        print("  FAIL " + name + (("  -> " + detail) if detail else ""))


try:
    from backend.tools.shell import ShellTool
except Exception as e:  # noqa: BLE001
    print("ABBRUCH: backend.tools.shell nicht importierbar: %s" % e)
    sys.exit(2)

S = ShellTool()


def lebt(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


async def starten(cmd):
    return await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True)


async def haupt():
    print("\n[0] Positivkontrolle")
    p = await starten("echo hallo; echo fehler >&2")
    aus, fehl, ab, gek = await S._lesen(p, 5)
    check("normaler Befehl: stdout, stderr, kein Ablauf", aus.strip() == "hallo" and fehl.strip() == "fehler"
          and not ab and not gek, repr((aus, fehl, ab, gek)))

    print("\n[1] absolute Frist")
    p = await starten("while true; do echo x; sleep 0.3; done")
    t0 = time.monotonic()
    meldungen = []

    async def cb(t):
        meldungen.append(t)
    try:
        # Wachhund: haengt der Lauf (Frist wirkungslos), ist das ein FAIL, kein Haenger
        aus, fehl, ab, gek = await asyncio.wait_for(S._lesen(p, 2, cb), 15)
    except asyncio.TimeoutError:
        aus, fehl, ab, gek = "", "", False, False
        S._gruppe_beenden(p)
    dauer = time.monotonic() - t0
    check("troepfelnder Befehl endet nach der Frist (%.1f s)" % dauer, ab and dauer < 4, str(dauer))
    await asyncio.sleep(0.3)
    check("... und der Prozess lebt nicht mehr", not lebt(p.pid))

    print("\n[2] Mengendeckel")
    p = await starten("head -c 5000000 /dev/zero | tr '\\\\0' 'a'")
    aus, fehl, ab, gek = await S._lesen(p, 30)
    check("5 MB: gesammelt hoechstens SAMMEL_MAX", len(aus.encode()) <= S.SAMMEL_MAX, str(len(aus)))
    check("... Kuerzung gemeldet", gek is True)
    check("... und der Befehl lief zu Ende (kein Haengen an voller Pipe)", not ab)

    print("\n[3] Statuszeilen gebuendelt")
    meldungen.clear()
    p = await starten("for i in $(seq 1 2000); do echo Zeile$i; done")
    aus, fehl, ab, gek = await S._lesen(p, 30, cb)
    check("(Positivkontrolle) alle 2000 Zeilen gesammelt", aus.count("Zeile") == 2000, str(aus.count("Zeile")))
    check("hoechstens wenige Rueckrufe statt 2000 (%d)" % len(meldungen), 0 < len(meldungen) < 100)
    check("die letzte Meldung ist die letzte Zeile", meldungen and meldungen[-1] == "💻 Zeile2000",
          meldungen[-1] if meldungen else "")

    print("\n[4] Stopp beendet den Prozessbaum")
    p = await starten("sleep 30 & sleep 30; wait")
    aufgabe = asyncio.ensure_future(S._lesen(p, 60))
    await asyncio.sleep(0.5)
    kinder = os.popen("pgrep -g %d" % p.pid).read().split()
    check("(Positivkontrolle) Prozessgruppe laeuft (%d Prozesse)" % len(kinder), len(kinder) >= 2)

    async def mit_kill():
        try:
            return await aufgabe
        except asyncio.CancelledError:
            S._gruppe_beenden(p)
            raise
    huelle = asyncio.ensure_future(mit_kill())
    await asyncio.sleep(0.1)
    huelle.cancel()
    try:
        await huelle
    except asyncio.CancelledError:
        pass
    await asyncio.sleep(0.5)
    rest = os.popen("pgrep -g %d" % p.pid).read().split()
    check("nach dem Abbruch: keine Prozesse der Gruppe mehr", rest == [], str(rest))


asyncio.run(haupt())

# Regel: der Werkzeug-Aufruf faengt CancelledError um _lesen und beendet dort
import ast  # noqa: E402
quelle = (ROOT / "backend" / "tools" / "shell.py").read_text(encoding="utf-8")
treffer = [n for n in ast.walk(ast.parse(quelle)) if isinstance(n, ast.Try)
           and any("_lesen(" in ast.unparse(s) for s in n.body)
           and any(h.type is not None and ast.unparse(h.type) == "asyncio.CancelledError"
                   and "_gruppe_beenden(proc)" in ast.unparse(h) for h in n.handlers)]
check("Werkzeug: _lesen steht im try mit CancelledError -> _gruppe_beenden", len(treffer) == 1)

print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
