#!/usr/bin/env python3
"""Waechter fuer den manuellen Lauf der Sicherheitsupdates (apt_upgrades.jetzt_ausfuehren).

Zusagen:
  1. Fail-closed: ohne Paket ODER ohne wirksame Begrenzungen wird
     ``unattended-upgrade`` NICHT aufgerufen (sonst gaelte die Debian-Vorgabe,
     die je nach Fassung Pakete aufraeumt).
  2. Mit Begrenzungen: erst ``apt-get update``, dann ``unattended-upgrade`` –
     OHNE ``--dry-run`` (sonst waere der Knopf wirkungslos).
  3. Neu eingespielte Pakete werden genannt; ein Fehlschlag meldet ok=False.
  4. Broker-Op und Endpunkt sind verdrahtet, die Op laeuft im langen Pool.

Hermetisch: alle Systemaufrufe sind Attrappen, nichts wird ausgefuehrt.

    python3 tests/test_apt_jetzt.py
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = 0
_fail = []


def check(name, cond, detail=""):
    global _ok
    if cond:
        _ok += 1
        print(f"  \033[32m✓\033[0m {name}")
    else:
        _fail.append(name)
        print(f"  \033[31m✗\033[0m {name}  {detail}")


try:
    from backend import apt_upgrades as au
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: apt_upgrades nicht importierbar: {e}")
    sys.exit(2)


class _R:
    def __init__(self, rc=0, out=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = ""


def aufbau(pkg=True, limits=True, uu_rc=0, neu=None):
    """Stellt die Attrappen und liefert die Liste der Aufrufe."""
    aufrufe = []
    verlauf = {"n": 0}

    def run(cmd, timeout=30, env=None):
        aufrufe.append(list(cmd))
        if cmd and cmd[0] == au.UU:
            return _R(uu_rc, "lauf")
        return _R(0)

    def eingespielt(max_n=20):
        verlauf["n"] += 1
        # Erster Aufruf = vorher, zweiter = nachher
        if verlauf["n"] == 1 or not neu:
            return [{"start": 1.0, "pakete": [{"name": "alt"}]}]
        return [{"start": 2.0, "pakete": [{"name": n} for n in neu]},
                {"start": 1.0, "pakete": [{"name": "alt"}]}]

    au._run = run
    au._pkg_installed = lambda: pkg
    au._limits_ok = lambda: limits
    au.eingespielt = eingespielt
    au.status = lambda live=False: {"stub": True}
    return aufrufe


def uu_aufrufe(aufrufe):
    return [c for c in aufrufe if c and c[0] == au.UU]


# Positivkontrolle: die Attrappe sieht einen UU-Aufruf ueberhaupt
a = aufbau()
erg = au.jetzt_ausfuehren()
if not uu_aufrufe(a):
    print("ABBRUCH: Positivkontrolle – Attrappe sieht keinen unattended-upgrade-Aufruf")
    sys.exit(2)

print("1. Fail-closed")
a = aufbau(limits=False)
erg = au.jetzt_ausfuehren()
check("ohne Begrenzungen kein unattended-upgrade", not uu_aufrufe(a), str(a))
check("ohne Begrenzungen ok=False", erg.get("ok") is False)
a = aufbau(pkg=False)
erg = au.jetzt_ausfuehren()
check("ohne Paket kein unattended-upgrade", not uu_aufrufe(a), str(a))
check("ohne Paket ok=False", erg.get("ok") is False)

print("2. Reihenfolge und echter Lauf")
a = aufbau(neu=["openssl", "libssl3"])
erg = au.jetzt_ausfuehren()
idx_upd = next((i for i, c in enumerate(a) if c[:2] == [au.APT_GET, "update"]), None)
idx_uu = next((i for i, c in enumerate(a) if c and c[0] == au.UU), None)
check("apt-get update vor unattended-upgrade",
      idx_upd is not None and idx_uu is not None and idx_upd < idx_uu, str(a))
check("kein --dry-run", all("--dry-run" not in c for c in uu_aufrufe(a)), str(a))
check("ok=True bei rc 0", erg.get("ok") is True)

print("3. Rueckmeldung")
namen = " ".join(s.get("name", "") for s in erg.get("steps") or [])
check("neue Pakete werden genannt", "openssl" in namen and "libssl3" in namen, namen)
check("altes Paket nicht als neu genannt", "alt" not in namen.replace("aktualisiert", ""), namen)
a = aufbau(uu_rc=1)
erg = au.jetzt_ausfuehren()
check("Fehlschlag meldet ok=False", erg.get("ok") is False)

print("4. Verdrahtung")
ops_src = (ROOT / "backend/broker/ops.py").read_text(encoding="utf-8")
baum = ast.parse(ops_src)
schluessel = set()
for knoten in ast.walk(baum):
    if isinstance(knoten, ast.Dict):
        for k in knoten.keys:
            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                schluessel.add(k.value)
check("Broker-Op apt_upgrades_jetzt registriert", "apt_upgrades_jetzt" in schluessel)
daemon_src = (ROOT / "backend/broker/daemon.py").read_text(encoding="utf-8")
lange = set()
for knoten in ast.walk(ast.parse(daemon_src)):
    if (isinstance(knoten, ast.Assign) and any(getattr(t, "id", "") == "LANGE_OPS" for t in knoten.targets)):
        lange = {c.value for c in ast.walk(knoten.value) if isinstance(c, ast.Constant)}
check("Op laeuft im langen Pool", "apt_upgrades_jetzt" in lange)
main_src = (ROOT / "backend/main.py").read_text(encoding="utf-8")
check("Endpunkt POST /api/security/unattended/jetzt vorhanden",
      '@app.post("/api/security/unattended/jetzt")' in main_src)

print(f"\nErgebnis: {_ok}/{_ok + len(_fail)}")
sys.exit(1 if _fail else 0)
