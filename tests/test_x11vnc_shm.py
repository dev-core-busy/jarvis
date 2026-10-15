#!/usr/bin/env python3
"""Waechter: x11vnc wird nie hart beendet, ohne den Shared Memory aufzuraeumen.

Vorfall 2026-10-05: `pkill -9 x11vnc` bei jeder Admin-Anmeldung liess je 42
SysV-Segmente liegen (gemessen: SIGKILL +42, SIGTERM +0). DEV 4088, ECHT 3108,
Limit 4096 – danach startete x11vnc nicht mehr.

A. Regel ueber alle Python- und Shell-Dateien: kein SIGKILL an x11vnc
   ausserhalb von x11vnc_beenden().
B. x11vnc_beenden() AUSGEFUEHRT (Attrappe fuer subprocess): TERM zuerst; KILL
   nur, wenn TERM nicht wirkt, und dann wird aufgeraeumt.
C. shm_verwaiste_aufraeumen() AUSGEFUEHRT: nur root + nicht angehaengt +
   Erzeuger tot.
D. Der Broker-Start raeumt auf, bevor der Broker startet.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import ast
import os
import re
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OK = FAIL = 0


def check(name, bed, info=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [%s]" % info) if info else ""))


def abbruch(grund):
    print("ABBRUCH: " + grund)
    sys.exit(2)


# ── A ──
print("[A] Regel: kein SIGKILL an x11vnc ausserhalb von x11vnc_beenden()")
KILL = {"-9", "-KILL", "-SIGKILL", "-s9", "--signal=9", "--signal=KILL"}
funde = []
geprueft = 0
for p in list(ROOT.glob("backend/**/*.py")) + list(ROOT.glob("skills/**/*.py")) + [ROOT / "start_jarvis.sh", ROOT / "start_jarvis_root.sh"] + list(ROOT.glob("deploy/**/*.sh")):
    if "__pycache__" in p.parts or not p.exists():
        continue
    geprueft += 1
    text = p.read_text(encoding="utf-8", errors="replace")
    if p.suffix == ".py":
        try:
            baum = ast.parse(text)
        except SyntaxError:
            continue
        erlaubt = set()
        for fn in ast.walk(baum):
            if isinstance(fn, ast.FunctionDef) and fn.name == "x11vnc_beenden":
                erlaubt |= {id(n) for n in ast.walk(fn)}
        for n in ast.walk(baum):
            if isinstance(n, ast.List) and id(n) not in erlaubt:
                werte = [e.value for e in n.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                if werte[:1] in (["pkill"], ["killall"], ["kill"]) and "x11vnc" in werte \
                        and KILL & set(werte):
                    funde.append("%s:%d" % (p.relative_to(ROOT), n.lineno))
    else:
        for nr, z in enumerate(text.splitlines(), 1):
            code = z.split("#", 1)[0]
            if re.search(r"\b(pkill|killall)\b", code) and "x11vnc" in code \
                    and KILL & set(code.split()):
                funde.append("%s:%d" % (p.relative_to(ROOT), nr))
if geprueft < 50:
    abbruch("Positivkontrolle: nur %d Dateien gefunden" % geprueft)
check("kein SIGKILL an x11vnc ausserhalb von x11vnc_beenden()", not funde, funde)

# Positivkontrolle der Regel: dieselbe Pruefung findet die frueher vorhandene Zeile
_probe = ast.parse('subprocess.run(["pkill", "-9", "x11vnc"])')
_treffer = [n for n in ast.walk(_probe) if isinstance(n, ast.List)
            and [e.value for e in n.elts][:1] == ["pkill"] and KILL & {e.value for e in n.elts}]
check("Positivkontrolle: die Regel erkennt `pkill -9 x11vnc`", len(_treffer) == 1)

# ── B ──
print("\n[B] x11vnc_beenden() ausgefuehrt")
import backend.desktop_control as dc  # noqa: E402

AUFRUFE = []


def _attrappe(stur: bool):
    zustand = {"lebt": True}

    def run(cmd, **kw):
        AUFRUFE.append(list(cmd))
        if cmd[:1] == ["pkill"]:
            if "-KILL" in cmd or ("-TERM" in cmd and not stur):
                zustand["lebt"] = False
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[:1] == ["pgrep"]:
            return types.SimpleNamespace(returncode=0 if zustand["lebt"] else 1, stdout="", stderr="")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")
    return run


aufgeraeumt = []
_echt_run, _echt_auf, _echt_frist = dc.subprocess.run, dc.shm_verwaiste_aufraeumen, dc.X11VNC_TERM_WARTEN_S
try:
    dc.shm_verwaiste_aufraeumen = lambda: aufgeraeumt.append(1) or 0
    dc.X11VNC_TERM_WARTEN_S = 0.6
    dc.subprocess.run = _attrappe(stur=False)
    AUFRUFE.clear(); dc.x11vnc_beenden()
    pk = [c for c in AUFRUFE if c[:1] == ["pkill"]]
    if not pk:
        abbruch("Positivkontrolle: x11vnc_beenden() ruft pkill gar nicht (Attrappe greift nicht?)")
    check("folgsam: erst TERM", pk[0][:3] == ["pkill", "-TERM", "-x"])
    check("folgsam: kein KILL, kein Aufraeumen noetig", len(pk) == 1 and not aufgeraeumt)
    dc.subprocess.run = _attrappe(stur=True)
    AUFRUFE.clear(); aufgeraeumt.clear(); dc.x11vnc_beenden()
    pk = [c for c in AUFRUFE if c[:1] == ["pkill"]]
    check("stur: TERM, dann KILL", [c[1] for c in pk] == ["-TERM", "-KILL"])
    check("stur: nach dem KILL wird aufgeraeumt", aufgeraeumt == [1])
    check("vor dem KILL wurde gewartet (pgrep mehrfach)",
          sum(1 for c in AUFRUFE if c[:1] == ["pgrep"]) >= 2)
finally:
    dc.subprocess.run, dc.shm_verwaiste_aufraeumen, dc.X11VNC_TERM_WARTEN_S = _echt_run, _echt_auf, _echt_frist

for name in ("restart_vnc", "switch_desktop_session", "unlock_desktop_screen"):
    fn = next((n for n in ast.walk(ast.parse((ROOT / "backend" / "desktop_control.py").read_text()))
               if isinstance(n, ast.FunctionDef) and n.name == name), None)
    check("%s beendet x11vnc ueber x11vnc_beenden()" % name,
          fn is not None and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                                 and c.func.id == "x11vnc_beenden" for c in ast.walk(fn)))

# ── C ──
print("\n[C] shm_verwaiste_aufraeumen() ausgefuehrt")
IPCS = """
------ Shared Memory Segments --------
key        shmid      owner      perms      bytes      nattch     status
0x00000000 101        root       600        4096       0          dest
0x00000000 102        root       600        4096       0
0x00000000 103        root       600        4096       2
0x00000000 104        jarvis     600        4096       0
"""
IPCS_P = """
------ Shared Memory Creator/Last-op PIDs --------
shmid      owner      cpid       lpid
101        root       999991     1
102        root       %d         1
103        root       999992     1
104        jarvis     999993     1
""" % os.getpid()
entfernt = []


def _run_ipcs(cmd, **kw):
    if cmd == ["ipcs", "-m"]:
        return types.SimpleNamespace(returncode=0, stdout=IPCS, stderr="")
    if cmd == ["ipcs", "-m", "-p"]:
        return types.SimpleNamespace(returncode=0, stdout=IPCS_P, stderr="")
    if cmd[:2] == ["ipcrm", "-m"]:
        entfernt.append(cmd[2])
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")
    raise AssertionError("unerwarteter Aufruf %s" % cmd)


if os.path.exists("/proc/999991"):
    abbruch("Positivkontrolle: Test-PID 999991 lebt zufaellig")
try:
    dc.subprocess.run = _run_ipcs
    n = dc.shm_verwaiste_aufraeumen()
finally:
    dc.subprocess.run = _echt_run
check("verwaist (root, 0 Anhaenge, Erzeuger tot) wird entfernt", "101" in entfernt)
check("Erzeuger lebt noch -> bleibt", "102" not in entfernt)
check("angehaengt -> bleibt", "103" not in entfernt)
check("fremder Eigentuemer -> bleibt", "104" not in entfernt)
check("Rueckgabe = Zahl der entfernten", n == len(entfernt) == 1)

# ── D ──
print("\n[D] Broker-Start raeumt auf")
z = (ROOT / "start_jarvis_root.sh").read_text().splitlines()
auf = [i for i, l in enumerate(z) if not l.lstrip().startswith("#")
       and "backend.desktop_control shm-aufraeumen" in l]
start = next((i for i, l in enumerate(z) if l.startswith("# 7.")), None)
vnc = next((i for i, l in enumerate(z) if l.startswith("# 5. x11vnc")), None)
check("start_jarvis_root.sh ruft das Aufraeumen", bool(auf))
check("…vor dem x11vnc-Start und dem Broker", bool(auf) and vnc is not None and start is not None
      and auf[0] < vnc < start)
r = subprocess.run([sys.executable, "-c", "import runpy,sys; sys.argv=['x','--nix'];"
                    "runpy.run_module('backend.desktop_control', run_name='__main__')"],
                   cwd=str(ROOT), capture_output=True, text=True, timeout=30)
check("Modul laeuft als Skript (nur Standardbibliothek)", r.returncode == 0, r.stderr[-200:])

print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(0 if FAIL == 0 else 1)
