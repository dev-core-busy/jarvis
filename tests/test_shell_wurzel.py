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

# ─── 3b. F-18: interne Ablage der Wissensverwaltung ─────────────────────────
print("3b. F-18: Entwuerfe, Gruppenkonfiguration, Suchindex")
_kn = SB.PROJECT_ROOT / "data" / "knowledge"
_fall = {
    "Entwurf": _kn / "pending" / "0123abcd.json",
    "Entwurfs-Ordner": _kn / "pending",
    "Gruppenkonfiguration": _kn / ".groups.json",
    "Gruppen-Sicherung": _kn / ".groups.json.bak",
}
_frei = _kn / "extract_1234abcd_Handbuch.md"
_erl, _ = SB.authorize_fs("read", str(_frei), username="alice")
pruefe(_erl, "Positivkontrolle: gewoehnliche Wissensdatei bleibt lesbar")
for name, pfad in _fall.items():
    erl, grund = SB.authorize_fs("read", str(pfad), username="alice")
    pruefe(not erl and "Wissensverwaltung" in grund,
           f"Dateiwerkzeug: {name} gesperrt, mit Begruendung", f"{erl} {grund!r}")
    pruefe(not SB.fs_target_sensitive(str(pfad)),
           f"{name}: WEICHE Sperre (kein Angriffsindiz, keine Kontosperre)")
_ordner = {str(SB.PROJECT_ROOT / r) for r in SB.WISSEN_INTERN_REL
           if not r.endswith(".json")}
pruefe(_ordner == set(LT.WISSEN_VERDECKT),
       "jeder gesperrte Ordner ist in der Shell verdeckt (Gleichstand)",
       f"Werkzeug {sorted(_ordner)} / Shell {sorted(LT.WISSEN_VERDECKT)}")
for rel in ("data/knowledge/pending", "data/vector_store"):
    pruefe(rel in SB.PRIVATE_DIRS, f"{rel} steht in PRIVATE_DIRS")
pruefe("data/knowledge/.groups.json" in SB.PRIVATE_FILES,
       "data/knowledge/.groups.json steht in PRIVATE_FILES")
with tempfile.TemporaryDirectory() as tmp:
    baum = Path(tmp)
    for d in ("data/knowledge/pending", "data/vector_store"):
        (baum / d).mkdir(parents=True)
        (baum / d).chmod(0o755)
    for f in ("data/knowledge/.groups.json", "data/knowledge/.groups.json.bak",
              "data/knowledge/extract_x.md"):
        (baum / f).write_text("{}", encoding="utf-8")
        (baum / f).chmod(0o644)
    alt = SB.PROJECT_ROOT
    try:
        SB.PROJECT_ROOT = baum
        SB.harden_data_dirs()
    finally:
        SB.PROJECT_ROOT = alt
    _m = lambda r: (baum / r).stat().st_mode & 0o777
    pruefe(_m("data/knowledge/pending") == 0o750, "Entwurfs-Ordner danach 0750",
           oct(_m("data/knowledge/pending")))
    pruefe(_m("data/vector_store") == 0o750, "Suchindex-Ordner danach 0750",
           oct(_m("data/vector_store")))
    pruefe(_m("data/knowledge/.groups.json") == 0o640, ".groups.json danach 0640",
           oct(_m("data/knowledge/.groups.json")))
    pruefe(_m("data/knowledge/.groups.json.bak") == 0o640, ".groups.json.bak danach 0640",
           oct(_m("data/knowledge/.groups.json.bak")))
    pruefe(_m("data/knowledge/extract_x.md") == 0o644,
           "gewoehnliche Wissensdatei bleibt unberuehrt (0644)")

# ─── 3c. F-02 / F-15: Anweisungsdateien und Schwachstellenpruefung ──────────
print("3c. F-02/F-15: Anweisungen (auch Sicherungen) und CVE-Ergebnis auf 0750")
with tempfile.TemporaryDirectory() as tmp:
    baum = Path(tmp)
    _dirs = ("data/instructions", "data/instructions_default",
             "data/instructions-safe-20260804-191216", "data/cve")
    for d in _dirs:
        (baum / d).mkdir(parents=True)
        (baum / d).chmod(0o755)
        (baum / d / "x.md").write_text("x", encoding="utf-8")
        (baum / d / "x.md").chmod(0o644)
    # Gegenstuecke, die das Muster NICHT anfassen darf: eine gleichnamige DATEI
    # und ein Verweis auf ein fremdes Verzeichnis.
    (baum / "data" / "instructions_notiz.txt").write_text("x", encoding="utf-8")
    (baum / "data" / "instructions_notiz.txt").chmod(0o644)
    fremd = baum / "fremd"
    fremd.mkdir()
    fremd.chmod(0o755)
    (baum / "data" / "instructions-verweis").symlink_to(fremd)
    alt = SB.PROJECT_ROOT
    try:
        SB.PROJECT_ROOT = baum
        SB.harden_data_dirs()
    finally:
        SB.PROJECT_ROOT = alt
    for d in _dirs:
        m = (baum / d).stat().st_mode & 0o777
        pruefe(m == 0o750, f"{d} danach 0750", oct(m))
    pruefe(((baum / "data" / "instructions_notiz.txt").stat().st_mode & 0o777) == 0o644,
           "gleichnamige DATEI bleibt unberuehrt")
    pruefe((fremd.stat().st_mode & 0o777) == 0o755,
           "Verweis-Ziel bleibt unberuehrt (keine Rechte ueber einen Symlink)")
pruefe("data/cve" in SB.PRIVATE_DIRS, "data/cve steht in PRIVATE_DIRS")

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
    (wissen / "pending").mkdir()
    (wissen / "pending" / "entwurf.json").write_text("ENTWURFSINHALT", encoding="utf-8")
    os.chmod(wissen / "pending", 0o755)
    os.chmod(wissen / "pending" / "entwurf.json", 0o644)
    alt_orte, alt_verd = LT.WISSEN_ORTE, LT.WISSEN_VERDECKT
    try:
        LT.WISSEN_ORTE = (str(wissen),)
        LT.WISSEN_VERDECKT = (str(wissen / "pending"),)

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
        # F-18: Positivkontrolle ist die lesbare Datei eine Zeile hoeher; der
        # Entwurf liegt auf dem Host 0644 – nur das Verdecken haelt ihn fern.
        aus = lauf(f"cat {wissen}/pending/entwurf.json 2>&1; ls -A {wissen}/pending | wc -l")
        pruefe("ENTWURFSINHALT" not in aus and aus.strip().endswith("0"),
               "Entwurfs-Ordner ist im Lauf leer (F-18)", aus.strip()[:160])
    finally:
        LT.WISSEN_ORTE, LT.WISSEN_VERDECKT = alt_orte, alt_verd
        shutil.rmtree(lauf_dir, ignore_errors=True)
        shutil.rmtree(wissen, ignore_errors=True)

print(f"\n{_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
