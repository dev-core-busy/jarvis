#!/usr/bin/env python3
"""Waechter: setup_broker.sh wartet auf den Broker-Socket des NEUEN Prozesses.

Vorfall 2026-11-25 (frisch installierte VM): nach ``systemctl restart
jarvis-broker`` stand ``sleep 4`` und EINE Pruefung. Der erste Start baut vor
dem Socket noch VNC/websockify auf, der Socket kam ~10 s spaeter – das Skript
meldete "Migration unvollstaendig" (Exit 1), obwohl alles lief.

  [1] ``_auf_socket_warten`` AUSGEFUEHRT (aus dem Skript geschnitten, in bash):
      a) Socket erscheint nach 2 s           -> 0 (wartet)
      b) kein Socket                          -> 1 nach der Frist
      c) Socket von VOR dem Neustart          -> 1 (alter Prozess zaehlt nicht)
      d) Socket schon da und frisch           -> 0 sofort
  [2] Schritt 5/5 prueft den Socket UEBER diese Funktion, mit einer Frist von
      mindestens 30 s, und der Zeitpunkt wird VOR dem Broker-Neustart genommen.

Pruefling umlenkbar fuer die Gegenprobe: JARVIS_PRUEFLING_SETUP_BROKER.
Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRUEFLING = Path(os.environ.get("JARVIS_PRUEFLING_SETUP_BROKER",
                                ROOT / "deploy" / "security" / "setup_broker.sh"))
OK = FAIL = 0


def check(name, bed, detail=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  -> " + detail) if detail else ""))


def abbruch(grund):
    print("ABBRUCH: " + grund)
    sys.exit(2)


if not shutil.which("bash") or not shutil.which("stat"):
    abbruch("bash/stat fehlen")
text = PRUEFLING.read_text(encoding="utf-8")
m = re.search(r"^_auf_socket_warten\(\) \{.*?^\}\n", text, re.S | re.M)
# Positivkontrolle: ohne die Funktion ist jede inhaltliche Pruefung sinnlos
if not m:
    abbruch("_auf_socket_warten() nicht in %s gefunden" % PRUEFLING)
FUNK = m.group(0)


def lauf(pfad, seit, frist):
    """Funktion in bash ausfuehren; (rc, dauer_s)."""
    t0 = time.monotonic()
    r = subprocess.run(["bash", "-c", FUNK + '\n_auf_socket_warten "$1" "$2" "$3"', "x",
                        str(pfad), str(seit), str(frist)], capture_output=True, timeout=60)
    return r.returncode, time.monotonic() - t0


def sock_anlegen(pfad):
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(pfad))
    return s


print("[1] _auf_socket_warten ausgefuehrt")
tmp = Path(tempfile.mkdtemp(prefix="sb_sock_"))
try:
    # a) erscheint nach 2 s
    p = tmp / "a.sock"
    seit = int(time.time())
    kind = subprocess.Popen([sys.executable, "-c",
                             "import socket,time,sys;time.sleep(2);"
                             "s=socket.socket(socket.AF_UNIX);s.bind(sys.argv[1]);time.sleep(8)", str(p)])
    rc, dauer = lauf(p, seit, 8)
    kind.kill()
    check("a) Socket nach 2 s -> wartet und meldet Erfolg", rc == 0 and dauer >= 1.5,
          "rc=%s dauer=%.1f" % (rc, dauer))

    # b) kein Socket
    rc, dauer = lauf(tmp / "fehlt.sock", int(time.time()), 2)
    check("b) kein Socket -> Fehlschlag nach der Frist", rc == 1 and dauer >= 1.5,
          "rc=%s dauer=%.1f" % (rc, dauer))

    # c) alter Socket (vor dem Neustart angelegt)
    p = tmp / "c.sock"
    s = sock_anlegen(p)
    time.sleep(1.2)
    rc, _ = lauf(p, int(time.time()) + 1, 2)
    s.close()
    check("c) Socket von VOR dem Neustart zaehlt nicht", rc == 1, "rc=%s" % rc)

    # d) frisch und schon da
    p = tmp / "d.sock"
    seit = int(time.time())
    s = sock_anlegen(p)
    rc, dauer = lauf(p, seit, 10)
    s.close()
    check("d) frischer Socket -> sofort Erfolg", rc == 0 and dauer < 1.5,
          "rc=%s dauer=%.1f" % (rc, dauer))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n[2] Schritt 5/5 nutzt die Funktion")
zeilen = text.splitlines()
aufruf = [z for z in zeilen if re.search(r"^\s*if _auf_socket_warten ", z)]
check("Verifikation ruft _auf_socket_warten auf (Positivkontrolle)", len(aufruf) == 1, str(aufruf))
frist = re.search(r'_auf_socket_warten\s+"\$BROKER_SOCK"\s+"\$NEUSTART_SEIT"\s+(\d+)', aufruf[0]) if aufruf else None
check("Frist mindestens 30 s", bool(frist) and int(frist.group(1)) >= 30, str(aufruf))
i_seit = next((i for i, z in enumerate(zeilen) if re.match(r'^NEUSTART_SEIT="\$\(date \+%s\)"', z)), -1)
i_neu = next((i for i, z in enumerate(zeilen) if z.strip() == "systemctl restart jarvis-broker.service"), -1)
check("Zeitpunkt wird VOR dem Broker-Neustart genommen", 0 <= i_seit < i_neu, "seit=%d neustart=%d" % (i_seit, i_neu))
i_s5 = next((i for i, z in enumerate(zeilen) if z.startswith('step "5/5')), -1)
i_pid = next((i for i, z in enumerate(zeilen) if z.startswith("MAIN_PID=")), -1)
check("Abschnitt Schritt 5 gefunden (Positivkontrolle)", 0 <= i_s5 < i_pid, "%d/%d" % (i_s5, i_pid))
check("keine Einmal-Pruefung [ -S … ] mehr in Schritt 5",
      not any("[ -S " in z for z in zeilen[i_s5:i_pid]), "\n".join(zeilen[i_s5:i_pid]))

print("\nErgebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
