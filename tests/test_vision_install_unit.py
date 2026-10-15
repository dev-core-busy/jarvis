#!/usr/bin/env python3
"""Waechter K1-c: die Vision-Installations-Unit aus docs/install.sh laeuft NICHT als root.

Befund (BSI-Abgleich 2026-09-29, K1-c): ``jarvis-vision-install.service`` lief
ohne ``User=`` und fuehrte als root ``$INSTALL_DIR/vision-install.sh`` und pip
im venv aus – in einem Baum, der dem Dienstbenutzer gehoert. Die Unit entsteht
bei jeder Erstinstallation neu; Entfernen allein haelt nicht.

Gemessen an der WIRKUNG: der Abschnitt aus install.sh wird ECHT ausgefuehrt
(Wegwerf-Verzeichnis, ``$SUDO`` leer, Unit-Pfad umgelenkt, systemctl als
Attrappe), und die ERZEUGTEN Dateien werden geprueft.

Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
import getpass
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "docs" / "install.sh").read_text(encoding="utf-8")
OK = FAIL = 0


def check(name, bed, detail=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + ((" – " + detail) if detail else ""))


zeilen = SRC.splitlines(keepends=True)
anfang = next((i for i, z in enumerate(zeilen) if "vision-install.sh\" >/dev/null << VISION_SH" in z), None)
if anfang is None:
    print("ABBRUCH: Vision-Abschnitt nicht in install.sh")
    sys.exit(2)
# Bis zur Zeile vor dem Schreibvorgang zurueck (Vorbereitung: VISION_USER, Marke)
start = anfang
while start > 0 and "if [[ $UPDATE_MODE -eq 0 ]]; then" not in zeilen[start]:
    start -= 1
ende = next((i for i in range(anfang, len(zeilen)) if zeilen[i].strip() == "VISION_UNIT"), None)
if ende is None or start == 0:
    print("ABBRUCH: Abschnitt nicht abgrenzbar")
    sys.exit(2)
block = "".join(zeilen[start + 1:ende + 1])

tmp = Path(tempfile.mkdtemp(prefix="waechter-vision-unit-"))
inst = tmp / "jarvis"
(inst / "venv").mkdir(parents=True)
(inst / "data").mkdir()
unit = tmp / "jarvis-vision-install.service"
block = block.replace("/etc/systemd/system/jarvis-vision-install.service", str(unit))
if str(unit) not in block:
    print("ABBRUCH: Unit-Pfad nicht umlenkbar")
    sys.exit(2)
skript = 'SUDO=""\nINSTALL_DIR=%s\nCURRENT_USER=%s\n%s' % (inst, getpass.getuser(), block)
r = subprocess.run(["bash", "-c", skript], capture_output=True, text=True, timeout=60)
if r.returncode != 0 or not unit.exists() or not (inst / "vision-install.sh").exists():
    print("ABBRUCH: Abschnitt lief nicht (rc=%s) %s" % (r.returncode, r.stderr[-400:]))
    sys.exit(2)
u = unit.read_text()
sh = (inst / "vision-install.sh").read_text()
check("Positivkontrolle: Unit und Skript erzeugt, ExecStart zeigt aufs Skript",
      "ExecStart=%s/vision-install.sh" % inst in u)

user = re.search(r"^User=(.*)$", u, re.M)
check("Unit hat User=", bool(user))
check("User= ist der Eigentuemer des venv (%s), nicht root" % getpass.getuser(),
      bool(user) and user.group(1) == getpass.getuser() and user.group(1) != "root",
      user.group(1) if user else "")
check("Marke als ConditionPathExists=!…",
      "ConditionPathExists=!%s/data/.vision-installiert" % inst in u)
check("Skript setzt die Marke (beide Erfolgswege)",
      sh.count('touch "%s/data/.vision-installiert"' % inst) == 2)
check("Skript ruft kein systemctl (ginge ohne root nicht)", "systemctl" not in sh)
print("\nErgebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(0 if FAIL == 0 else 1)
