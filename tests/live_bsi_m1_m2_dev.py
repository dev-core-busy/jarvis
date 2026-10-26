#!/usr/bin/env python3
"""LIVE auf DEV: BSI M1 (systemd-Haertung) + M2 (Sicherheitsprotokoll) im laufenden Dienst.

Als root auf DEV, mit dem System-Python:
    python3 /opt/jarvis/tests/live_bsi_m1_m2_dev.py

Gemessen wird der GANZE installierte Drop-in, nicht einzelne Optionen: am
2026-10-05 waren alle Einzelproben gruen, und im Dienst scheiterte bwrap
trotzdem – ProtectHostname bricht `--proc` erst zusammen mit dem
Mount-Namensraum aus ProtectSystem.

A. Unter exakt dem Drop-in (transienter Dienst): bwrap mit --proc und
   --unshare-net laeuft, die lokale Kennwortpruefung (unix_chkpwd) prueft
   wirklich (7 statt 9). Gegenkontrolle: mit ProtectKernelTunables bricht
   bwrap – die Probe kann den Fehler also sehen.
B. Laufendes Backend: Einstellungen wirksam, / read-only, Projektbaum
   schreibbar, kein bwrap-Fehler im Journal seit dem Start, Bewertung nicht
   mehr UNSAFE/EXPOSED.
C. Ein falscher Login ueber HTTPS steht mit Quelladresse im Protokoll und im
   Journal (jarvis-security); die Kette prueft gruen.
D. logrotate-Regel fuer das Broker-Audit ist gueltig.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

JARVIS = Path(os.environ.get("JARVIS_DIR", "/opt/jarvis"))
DROPIN = Path("/etc/systemd/system/jarvis.service.d/50-haertung.conf")
PROTOKOLL = JARVIS / "data" / "logs" / "sicherheit.jsonl"
OK = FAIL = 0


def check(name, bed, info=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + str(info)[:200] + "]") if info else ""))


def abbruch(grund):
    print("ABBRUCH: " + grund)
    sys.exit(2)


def sh(cmd, timeout=120, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)


if os.geteuid() != 0:
    abbruch("muss als root laufen")
if not DROPIN.exists():
    abbruch("Drop-in fehlt: %s (Broker neu starten?)" % DROPIN)
zeilen = [z.strip() for z in DROPIN.read_text().splitlines()
          if z.strip() and not z.strip().startswith(("#", "["))]
if len(zeilen) < 8:
    abbruch("Drop-in hat nur %d Direktiven" % len(zeilen))

BWRAP = ("setpriv --inh-caps=-all --ambient-caps=-all -- bwrap --ro-bind / / --dev /dev "
         "--proc /proc --tmpfs /tmp --unshare-user --unshare-pid --die-with-parent "
         "/bin/sh -c 'echo BWRAP-OK'; "
         "setpriv --inh-caps=-all --ambient-caps=-all -- bwrap --ro-bind / / --dev /dev "
         "--proc /proc --unshare-user --unshare-pid --unshare-net --die-with-parent "
         "/bin/sh -c 'echo NETZ-OK'; "
         "printf 'falsch\\0' | /usr/sbin/unix_chkpwd jarvis nonull; echo CHKPWD=$?")


def transient(extra=()):
    args = ["systemd-run", "--quiet", "--wait", "--pipe", "--collect",
            "-p", "User=jarvis", "-p", "AmbientCapabilities=CAP_NET_BIND_SERVICE"]
    for z in list(zeilen) + list(extra):
        args += ["-p", z]
    return sh(args + ["/bin/bash", "-c", BWRAP]).stdout + "\n" + ""


# ── A ──
print("[A] Unter exakt dem installierten Drop-in")
aus = transient()
check("bwrap mit --proc laeuft", "BWRAP-OK" in aus, aus)
check("bwrap mit --unshare-net laeuft", "NETZ-OK" in aus, aus)
check("lokale Kennwortpruefung prueft wirklich (unix_chkpwd 7, nicht 9)", "CHKPWD=7" in aus, aus)
gegen = transient(["ProtectKernelTunables=yes"])
check("Gegenkontrolle: mit ProtectKernelTunables bricht bwrap (die Probe sieht es)",
      "BWRAP-OK" not in gegen, gegen)

# ── B ──
print("\n[B] Laufendes Backend")
r = sh(["systemctl", "show", "jarvis.service", "-p", "MainPID", "-p", "ProtectSystem",
        "-p", "DropInPaths", "-p", "ActiveEnterTimestamp", "-p", "ActiveState"])
eig = dict(z.split("=", 1) for z in r.stdout.splitlines() if "=" in z)
pid = eig.get("MainPID", "0")
if pid in ("", "0") or eig.get("ActiveState") != "active":
    abbruch("jarvis.service laeuft nicht")
check("Drop-in ist im laufenden Dienst aktiv", str(DROPIN) in eig.get("DropInPaths", ""))
check("ProtectSystem=strict", eig.get("ProtectSystem") == "strict")
status = Path("/proc/%s/status" % pid).read_text()
capbnd = re.search(r"CapBnd:\s*([0-9a-f]+)", status)
check("Bounding-Set nur CAP_NET_BIND_SERVICE (0x400)",
      capbnd is not None and int(capbnd.group(1), 16) == 0x400, capbnd and capbnd.group(1))
nnp = re.search(r"NoNewPrivs:\s*(\d)", status)
check("NoNewPrivs aus (lokale Anmeldung)", nnp is not None and nnp.group(1) == "0")
wurzel = sh(["nsenter", "-t", pid, "-m", "findmnt", "-n", "-o", "OPTIONS", "/"]).stdout
baum = sh(["nsenter", "-t", pid, "-m", "findmnt", "-n", "-o", "OPTIONS", "-T", str(JARVIS)]).stdout
check("/ ist im Dienst read-only", wurzel.startswith("ro"), wurzel)
check("Projektbaum ist im Dienst schreibbar", baum.startswith("rw"), baum)
seit = eig.get("ActiveEnterTimestamp", "")
jr = sh(["journalctl", "-u", "jarvis.service", "--since", " ".join(seit.split()[1:3]) or "-10min",
         "--no-pager", "-o", "cat"])
if not jr.stdout.strip():
    abbruch("Journal des Dienstes seit dem Start leer (Messung unmoeglich)")
check("seit dem Start kein bwrap-Fehler im Journal",
      "Can't mount proc" not in jr.stdout and "bwrap-Probe fehlgeschlagen" not in jr.stdout,
      [z for z in jr.stdout.splitlines() if "bwrap" in z][:2])
bew = sh(["systemd-analyze", "security", "jarvis.service"]).stdout.strip().splitlines()
letzte = bew[-1] if bew else ""
check("systemd-Bewertung nicht mehr UNSAFE/EXPOSED",
      "Overall exposure" in letzte and not re.search(r"UNSAFE|EXPOSED", letzte), letzte)

# ── C ──
print("\n[C] Sicherheitsprotokoll im laufenden Dienst")
name = "m2probe." + uuid.uuid4().hex[:8]
kennwort = "kw-" + uuid.uuid4().hex   # eindeutig: darf nirgends im Eintrag stehen
vorher = PROTOKOLL.read_text().count("\n") if PROTOKOLL.exists() else 0
req = urllib.request.Request("https://127.0.0.1/api/login", method="POST",
                             data=json.dumps({"username": name, "password": kennwort}).encode(),
                             headers={"Content-Type": "application/json"})
try:
    urllib.request.urlopen(req, context=ssl._create_unverified_context(), timeout=30)
    code = 200
except urllib.error.HTTPError as e:
    code = e.code
check("falscher Login wird abgewiesen (Positivkontrolle der Anfrage)", code in (401, 403), code)
eintrag = None
for _ in range(20):
    if PROTOKOLL.exists():
        for z in reversed(PROTOKOLL.read_text().splitlines()):
            if name in z:
                eintrag = json.loads(z)
                break
    if eintrag:
        break
    time.sleep(0.5)
check("Fehlschlag steht im Protokoll", eintrag is not None)
check("…mit Art und Quelladresse", bool(eintrag) and eintrag.get("art") == "anmeldung_fehlgeschlagen"
      and eintrag.get("ip") == "127.0.0.1", eintrag)
check("…und das Kennwort nicht", bool(eintrag) and kennwort not in json.dumps(eintrag))
check("Protokoll gehoert dem Dienstbenutzer und ist nicht weltlesbar",
      PROTOKOLL.exists() and (PROTOKOLL.stat().st_mode & 0o077) == 0)
jr = sh(["journalctl", "-t", "jarvis-security", "--since", "-5min", "--no-pager", "-o", "cat"])
check("dieselbe Meldung im Journal (syslog, jarvis-security)", name in jr.stdout)
# Ueber als_dienst.sh, NICHT runuser: ohne Hauptschluessel hat der Befehl den
# Schluessel der Kette nicht und endet seit 2026-10-26 mit Exit 2 (vorher
# meldete er jede Zeile mit Merkmal als Bruch – die Probe war dauerhaft rot).
pr = sh(["bash", str(JARVIS / "deploy" / "als_dienst.sh"), str(JARVIS / "venv" / "bin" / "python"),
         "-m", "backend.sicherheits_log", "pruefen"], cwd=str(JARVIS),
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
try:
    kette = json.loads(pr.stdout)
except Exception:  # noqa: BLE001
    kette = {}
check("Kette prueft gruen", kette.get("ok") is True and kette.get("zeilen", 0) > vorher, pr.stdout[-200:])

# ── D ──
print("\n[D] Rotation des Broker-Audits")
lr = sh(["logrotate", "-d", "/etc/logrotate.d/jarvis-broker-audit"])
check("logrotate-Regel gueltig", "error" not in (lr.stdout + lr.stderr).lower()
      and "old logs are removed after 365 days" in (lr.stdout + lr.stderr), lr.stderr[-200:])

print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(0 if FAIL == 0 else 1)
