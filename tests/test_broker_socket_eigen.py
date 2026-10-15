#!/usr/bin/env python3
"""Waechter: der Broker entfernt beim Beenden nur seinen EIGENEN Socket.

Vorfall 2026-09-30 (DEV): ein verwaister Alt-Broker (seit 11.08.) wurde
beendet und loeschte dabei ``/run/jarvis-broker.sock`` – den Pfad, an dem
laengst der Socket des laufenden Dienstes lag. Das Backend erreichte den Broker
danach nicht mehr, bis der Dienst neu gestartet wurde.

Gemessen am echten ``daemon.main()`` in einem Kindprozess (unprivilegiert,
Socket im Wegwerf-Verzeichnis, Policy-Schritt als Attrappe):

  1. Positivkontrolle: ohne Fremd-Socket raeumt der Broker seinen Pfad ab.
  2. Liegt beim Beenden ein ANDERER Socket am Pfad, bleibt der stehen.

Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

KIND = r"""
import asyncio, json, os, signal, socket, sys
sys.path.insert(0, sys.argv[1])
fremd = sys.argv[2] == "fremd"
from backend.broker import daemon
if not daemon.SOCKET_PATH.startswith(os.environ["TMPDIR_PROBE"]):
    print(json.dumps({"abbruch": "Socket-Pfad nicht im Sandkasten"})); sys.exit(2)
daemon.policy.herabstufen = lambda _ops: []
erg = {}
async def ausloeser():
    # bereit = Socket da UND Signal-Handler gesetzt (sonst beendet SIGTERM hart)
    for _ in range(200):
        if (os.path.exists(daemon.SOCKET_PATH)
                and signal.getsignal(signal.SIGTERM) not in (signal.SIG_DFL, None)):
            break
        await asyncio.sleep(0.05)
    erg["bereit"] = os.path.exists(daemon.SOCKET_PATH)
    if fremd:
        # ein NEUER Broker uebernimmt den Pfad (so wie der Dienststart es tut)
        os.unlink(daemon.SOCKET_PATH)
        s = socket.socket(socket.AF_UNIX); s.bind(daemon.SOCKET_PATH); s.listen(1)
        erg["fremd_ino"] = os.stat(daemon.SOCKET_PATH).st_ino
        erg["_s"] = s
    os.kill(os.getpid(), signal.SIGTERM)
async def lauf():
    t = asyncio.create_task(ausloeser())
    await daemon.main()
    await t
asyncio.run(lauf())
erg.pop("_s", None)
erg["pfad_da"] = os.path.exists(daemon.SOCKET_PATH)
erg["ino_nachher"] = os.stat(daemon.SOCKET_PATH).st_ino if erg["pfad_da"] else None
print(json.dumps(erg))
"""


def lauf(art: str) -> dict:
    tmp = tempfile.mkdtemp(prefix="waechter-broker-sock-")
    env = dict(os.environ, JARVIS_BROKER_SOCKET=os.path.join(tmp, "b.sock"),
               JARVIS_BROKER_GROUP="gibt-es-nicht-4711", TMPDIR_PROBE=tmp,
               JARVIS_PROJECT_ROOT=tmp, PYTHONDONTWRITEBYTECODE="1")
    skript = os.path.join(tmp, "kind.py")
    with open(skript, "w") as f:
        f.write(KIND)
    r = subprocess.run([sys.executable, skript, str(ROOT), art], env=env,
                       capture_output=True, text=True, timeout=60)
    zeilen = [z for z in (r.stdout or "").splitlines() if z.startswith("{")]
    fremd_meldung = "gehoert inzwischen einem anderen Broker" in (r.stdout or "")
    if not zeilen:
        print("ABBRUCH: Kindprozess ohne Ergebnis (rc=%s)\n%s" % (r.returncode, (r.stderr or "")[-800:]))
        sys.exit(2)
    d = json.loads(zeilen[-1])
    if "abbruch" in d:
        print("ABBRUCH: " + d["abbruch"])
        sys.exit(2)
    d["fremd_meldung"] = fremd_meldung
    return d


OK = FAIL = 0


def check(name, bed):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name)


a = lauf("allein")
if not a.get("bereit"):
    print("ABBRUCH: Broker hat seinen Socket nicht angelegt")
    sys.exit(2)
check("Positivkontrolle: eigener Socket wird beim Beenden entfernt", a["pfad_da"] is False)
check("normales Beenden meldet KEINEN fremden Broker (kein Fehlalarm je Neustart)",
      a["fremd_meldung"] is False)
b = lauf("fremd")
check("Fremd-Socket am Pfad bleibt stehen", b["pfad_da"] is True)
check("... und ist unveraendert der fremde", b.get("ino_nachher") == b.get("fremd_ino"))
check("... und das Beenden sagt es", b["fremd_meldung"] is True)

print("\nErgebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(0 if FAIL == 0 else 1)
