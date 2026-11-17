#!/usr/bin/env python3
"""Pentest "Hardening" F-13 / F-16 / F-19: was ein Shell-Lauf vom Server sieht.

DIE BEFUNDE (2026-11-17):
  F-13  Shell sieht das Dateisystem des Servers  – bis dahin ``--dev-bind / /``,
        die harte Grenze waren allein die OS-Rechte. Auf DEV gemessen las der
        Sandbox-Benutzer 72.722 Dateien unter /opt/jarvis, dazu /var/log,
        /etc/jarvis und /run.
  F-19  Alles, was die Shell lesen kann, laesst sich als Datei herunterladen –
        ``cp <serverdatei> /tmp/`` plus Liefer-Marker.
  F-16  Versionsverlauf (.git) trotz Pfadfilter lesbar – .git lag mit 0755 da.

DIE ZUSAGEN, die dieser Waechter festschreibt:
  1. Die Wissensorte der Shell sind DIESELBEN, die das filesystem-Werkzeug
     lesen darf (``sandbox.READ_ROOTS`` ohne /tmp und data/documents) – zwei
     Listen fuer dieselbe Frage laufen sonst auseinander.
  2. ``.git`` steht in ``PRIVATE_DIRS`` und ``harden_data_dirs`` setzt es
     WIRKLICH auf 0750 (gegen einen echten Baum im Sandkasten ausgefuehrt).
  3. Der echte bwrap-Lauf (mit installiertem bwrap) sieht weder den Projektbaum
     noch /etc/jarvis, WOHL ABER einen eingebundenen Wissensort.

Laeuft ohne ``backend.config`` (Register: der echte Import schreibt die
Live-settings.json). Exit 2 = konnte nicht messen.

Lauf:  python3 tests/test_shell_wurzel.py
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def pruefe(bed, text, detail=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print(f"  ok   {text}")
    else:
        _fail += 1
        print(f"  FAIL {text}" + (f" – {detail}" if detail else ""))


def abbruch(grund):
    print(f"ABBRUCH (Exit 2): {grund}")
    sys.exit(2)


try:
    from backend import lauf_tmp as LT      # noqa: E402
    from backend import sandbox as SB       # noqa: E402
except Exception as e:  # noqa: BLE001
    abbruch(f"Module nicht ladbar: {e}")
if "backend.config" in sys.modules:
    abbruch("backend.config wurde geladen – der Test wuerde die Live-Konfiguration anfassen")

# ─── 1. Gleichstand der Wissensorte ─────────────────────────────────────────
print("1. Wissensorte der Shell = Leseorte des filesystem-Werkzeugs")
_soll = {str(r) for r in SB.READ_ROOTS} - {str(Path("/tmp").resolve()),
                                          str(SB.DOCS_ROOT)}
_ist = {str(Path(w).resolve()) for w in LT.WISSEN_ORTE}
pruefe(len(_soll) >= 2, "Positivkontrolle: READ_ROOTS nennt Wissensorte", str(_soll))
pruefe(_ist == _soll, "dieselbe Menge (ohne /tmp und data/documents)",
       f"nur Shell: {sorted(_ist - _soll)}, nur Werkzeug: {sorted(_soll - _ist)}")
pruefe(str(SB.DOCS_ROOT) not in _ist,
       "data/documents ist KEIN Wissensort der Shell (Ablagen aller Benutzer)")

# ─── 2. Aufbau der Wurzel ───────────────────────────────────────────────────
print("2. Aufbau der Wurzel")
_w = LT.minimal_wurzel()
_s = " ".join(_w)
pruefe("--ro-bind /usr /usr" in _s, "/usr schreibgeschuetzt")
pruefe("--dev /dev" in _s, "frische Geraeteknoten (2>/dev/null)")
pruefe("/" not in [_w[i + 1] for i, t in enumerate(_w[:-1]) if t in ("--bind", "--ro-bind", "--dev-bind")],
       "die Wurzel / wird NICHT eingebunden")
pruefe(str(LT.PROJECT_ROOT) not in [_w[i + 1] for i, t in enumerate(_w[:-1])
                                    if t in ("--bind", "--ro-bind", "--dev-bind")],
       "der Projektbaum wird NICHT eingebunden")
# Feste Erwartung statt Schleife ueber LT.ETC_VERBORGEN: sonst waere eine
# geleerte Liste trivial erfuellt (die Pruefung liefe gar nicht).
for v in ("/etc/jarvis", "/etc/ssh"):
    if os.path.isdir(v):
        pruefe(f"--tmpfs {v}" in _s, f"{v} im Lauf verdeckt")

# ─── 3. .git wird auf 0750 gezogen (F-16) ───────────────────────────────────
print("3. harden_data_dirs zieht .git auf 0750")
pruefe(".git" in SB.PRIVATE_DIRS, ".git steht in PRIVATE_DIRS")
with tempfile.TemporaryDirectory() as tmp:
    baum = Path(tmp)
    (baum / ".git" / "objects").mkdir(parents=True)
    (baum / ".git").chmod(0o755)
    alt = SB.PROJECT_ROOT
    try:
        SB.PROJECT_ROOT = baum
        if Path(SB.PROJECT_ROOT) != baum:
            abbruch("Sandkasten greift nicht (PROJECT_ROOT nicht umgebogen)")
        SB.harden_data_dirs()
    finally:
        SB.PROJECT_ROOT = alt
    pruefe(((baum / ".git").stat().st_mode & 0o777) == 0o750,
           ".git danach 0750", oct((baum / ".git").stat().st_mode & 0o777))

# ─── 4. Echter Lauf ─────────────────────────────────────────────────────────
print("4. Echter bwrap-Lauf")
if not os.path.exists(LT.BWRAP):
    print("  (uebersprungen: bwrap ist auf diesem Rechner nicht installiert)")
else:
    lauf_dir = Path(tempfile.mkdtemp(prefix="wurzel_", dir="/tmp"))
    wissen = Path(tempfile.mkdtemp(prefix="wissen_", dir=str(Path.home())))
    (wissen / "handbuch.txt").write_text("WISSENSINHALT", encoding="utf-8")
    os.chmod(wissen, 0o755)
    os.chmod(wissen / "handbuch.txt", 0o644)
    alt_orte = LT.WISSEN_ORTE
    try:
        LT.WISSEN_ORTE = (str(wissen),)

        def lauf(cmd):
            b = LT.sandbox_befehl("", cmd, lauf_dir, (), _pruefen=True)
            r = subprocess.run(["/bin/bash", "-c", b], capture_output=True,
                               text=True, timeout=60)
            return (r.stdout or "") + (r.stderr or "")

        _quelle = Path(LT.__file__).resolve()
        pruefe(_quelle.is_file(), "Positivkontrolle: Quellcode existiert auf dem Host")
        aus = lauf("echo LAEUFT")
        if "LAEUFT" not in aus:
            abbruch(f"bwrap-Lauf startet hier nicht: {aus.strip()[:200]}")
        aus = lauf(f"test -e {_quelle} && echo SICHTBAR || echo WEG")
        pruefe("WEG" in aus, "Projektbaum im Lauf NICHT VORHANDEN", aus.strip())
        aus = lauf(f"test -e {LT.PROJECT_ROOT}/.git && echo SICHTBAR || echo WEG")
        pruefe("WEG" in aus, ".git im Lauf NICHT VORHANDEN (F-16)", aus.strip())
        if os.path.isdir("/etc/jarvis") and any(Path("/etc/jarvis").iterdir()):
            aus = lauf("ls -A /etc/jarvis | wc -l")
            pruefe(aus.strip().endswith("0"), "/etc/jarvis im Lauf leer", aus.strip())
        aus = lauf(f"cat {wissen}/handbuch.txt")
        pruefe("WISSENSINHALT" in aus, "eingebundener Wissensort ist lesbar",
               aus.strip()[:120])
        aus = lauf(f"echo x > {wissen}/neu.txt 2>&1 || echo VERWEIGERT")
        pruefe("VERWEIGERT" in aus and not (wissen / "neu.txt").exists(),
               "Wissensort ist im Lauf NICHT beschreibbar", aus.strip()[:120])
    finally:
        LT.WISSEN_ORTE = alt_orte
        shutil.rmtree(lauf_dir, ignore_errors=True)
        shutil.rmtree(wissen, ignore_errors=True)

print(f"\n{_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
