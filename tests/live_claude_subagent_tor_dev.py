#!/usr/bin/env python3
"""Live auf DEV: ein echter Delegations-Lauf schreibt trotz Tor (0770 + ACL) im Klon.

Befund 2026-11-27: der Wegwerf-Klon stand auf 0777. Seit dem Tor kommt die
Sandbox (shell_execute als jarvis_sandbox*) nur noch ueber eine benannte ACL
hinein – ob das durch bwrap + zusatz_bind + Broker traegt, sieht nur ein
echter Lauf.

Der Lauf geht direkt ueber ``job_anlegen`` + ``job_ausfuehren`` – derselbe Weg
wie im Dienst (Klon, Tor, Agent mit shell_execute ueber den Broker), aber
OHNE HTTP-Endpunkt: so braucht die Probe weder einen Delegations-Schluessel
noch die Bereichsfreigabe "Claude" (eine Sicherheitseinstellung nur fuer eine
Messung umzustellen ist der schlechtere Weg). Der Auftragsstand liegt in einer
Wegwerf-Datei, nicht in data/claude_subagent.json.

  1. Auftrag: per shell_execute eine Zeile an README.md haengen, Riegel gruen
  2. waehrend des Laufs: Auftragsordner 0770, ACL nennt beide Sandbox-Konten
  3. Ergebnis: angenommen, Patch enthaelt die Zeile

Laeuft im Dienstkontext (Broker und Modellschluessel, BSI M5):
    bash /opt/jarvis/deploy/als_dienst.sh env PYTHONDONTWRITEBYTECODE=1 \\
        venv/bin/python tests/live_claude_subagent_tor_dev.py
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, "/opt/jarvis")
from backend import claude_subagent as cs  # noqa: E402

MARKE = "tor-probe-%d" % int(time.time())
_ok = 0
_fail = 0


def check(cond, label):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}")


async def beobachten(stopp: asyncio.Event, ergebnis: dict):
    """Auftragsordner waehrend des Laufs messen (Modus + ACL)."""
    while not stopp.is_set():
        for z in cs.ARBEIT_ROOT.glob("*") if cs.ARBEIT_ROOT.is_dir() else []:
            if z.name == ergebnis.get("id") and "modus" not in ergebnis:
                ergebnis["modus"] = os.stat(z).st_mode & 0o7777
                ergebnis["acl"] = subprocess.run(["getfacl", "-p", str(z)],
                                                 capture_output=True, text=True).stdout
                ergebnis["wurzel"] = (os.lstat(cs.ARBEIT_ROOT).st_uid,
                                      os.lstat(cs.ARBEIT_ROOT).st_mode & 0o7777)
        await asyncio.sleep(0.5)


async def lauf():
    tmp = Path(tempfile.mkdtemp(prefix="csa_live_"))
    cs.STATE_PATH = tmp / "zustand.json"
    cs._reset_fuer_tests()
    basis = subprocess.run(["git", "ls-remote", cs._repo_url(), "refs/heads/master"],
                           capture_output=True, text=True).stdout.split()
    if not basis:
        print("ABBRUCH: origin/master nicht lesbar")
        sys.exit(2)
    spec = (f"Haenge mit shell_execute genau eine Zeile an das Ende von README.md an: "
            f"`echo '<!-- {MARKE} -->' >> README.md` – sonst nichts aendern.")
    geprueft = cs.auftrag_pruefen(spec=spec, basis=basis[0][:12], dateien=["README.md"],
                                  riegel="tests/test_rumpf_deckel.py")
    job = cs.job_anlegen("tor.probe", geprueft)
    print(f"Auftrag {job['id']}")
    beob = {"id": job["id"]}
    stopp = asyncio.Event()
    t = asyncio.create_task(beobachten(stopp, beob))
    await asyncio.wait_for(cs.job_ausfuehren(job["id"]), timeout=900)
    stopp.set()
    await t
    fertig = next((j for j in cs._laden().get("jobs", []) if j.get("id") == job["id"]), {})
    return beob, fertig


def main():
    beob, job = asyncio.run(lauf())
    if "modus" in beob:
        check(beob["modus"] == 0o770, f"Auftragsordner im Lauf 0770 (ist {oct(beob['modus'])})")
        check("user:jarvis_sandbox_noinet:rwx" in beob["acl"]
              and "user:jarvis_sandbox:rwx" in beob["acl"], "ACL nennt beide Sandbox-Konten")
        check(beob["wurzel"] == (os.geteuid(), 0o755),
              f"Wurzel dienst-eigen, 0755 ({beob['wurzel']})")
    else:
        check(False, "Auftragsordner im Lauf gesehen")
    text = json.dumps(job, ensure_ascii=False)
    check(job.get("status") == "fertig" and job.get("angenommen") is not False,
          f"Auftrag fertig und angenommen ({job.get('status')}, {job.get('gruende') or job.get('fehler')})")
    check(MARKE in text, "Patch enthaelt die Zeile – die Sandbox konnte im Klon schreiben")
    print(f"\nBilanz: {_ok} OK, {_fail} FAIL")
    sys.exit(1 if _fail else 0)


if __name__ == "__main__":
    main()
