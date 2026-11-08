#!/usr/bin/env python3
"""Waechter: der Paketfilter faellt nicht mehr STILL aus (Pentest-Vorbereitung 2026-11-08).

Auf ECHT stand ``ExecStart=/bin/sh -c 'nft -f /etc/jarvis/firewall.nft || true'``:
scheiterte das Laden, bootete der Server ohne Filter, und die Unit meldete
Erfolg. Die Unit haengt nur per ``WantedBy=sysinit.target`` am Boot – ein
Fehlschlag haelt ihn ohnehin nicht an; ``|| true`` verbarg ihn nur.

  [1] REGEL (aus den Unit-Vorlagen im Skript gelesen): kein ExecStart der
      jarvis-firewall.service traegt ``|| true``; die v6-Zeile laedt nur bei
      vorhandener Datei (sonst schluege sie ohne echten Fehler fehl).
  [2] ``_nft_speichern`` AUSGEFUEHRT (Sandkasten, nft-Attrappe): eine
      ungueltige Regeldatei ersetzt die gute NICHT, die Funktion meldet Fehler;
      eine gueltige ersetzt sie.
  [3] ``--anwenden`` bricht mit Fehler ab, wenn das Speichern scheitert.
Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKRIPT = ROOT / "deploy" / "security" / "firewall.sh"
OK = FAIL = 0


def check(name, bed, detail=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  -> " + str(detail)) if detail else ""))


def abbruch(grund):
    print("ABBRUCH: " + grund)
    sys.exit(2)


if not SKRIPT.exists() or not shutil.which("bash"):
    abbruch("firewall.sh oder bash fehlt")
TEXT = SKRIPT.read_text(encoding="utf-8")

# ── [1] Unit-Vorlagen ─────────────────────────────────────────────────────
print("\n[1] Unit-Vorlagen")
vorlagen = re.findall(r"<<'(UNIT2?)'\n(.*?)\n\1\n", TEXT, re.S)
check("(Positivkontrolle) beide Unit-Vorlagen (nft + iptables) gefunden", len(vorlagen) == 2,
      [v[0] for v in vorlagen])
exec_zeilen = [z for _, v in vorlagen for z in v.splitlines() if z.startswith("ExecStart")]
check("(Positivkontrolle) ExecStart-Zeilen vorhanden", len(exec_zeilen) >= 3, exec_zeilen)
check("kein ExecStart traegt '|| true'", not [z for z in exec_zeilen if "|| true" in z],
      [z for z in exec_zeilen if "|| true" in z])
v6 = [z for z in exec_zeilen if "ip6tables-restore" in z]
check("v6-Zeile laedt nur bei vorhandener Datei", bool(v6) and all("-s /etc/jarvis/firewall-v6.rules" in z for z in v6),
      v6)


# ── [2] _nft_speichern ────────────────────────────────────────────────────
print("\n[2] _nft_speichern (Sandkasten)")


def funktion(name):
    m = re.search(r"^%s\(\) \{\n(.*?)^\}\n" % re.escape(name), TEXT, re.S | re.M)
    return ("%s() {\n%s}\n" % (name, m.group(1))) if m else ""


f_speichern = funktion("_nft_speichern")
if not f_speichern:
    abbruch("_nft_speichern nicht gefunden")


def lauf(gueltig: bool):
    tmp = Path(tempfile.mkdtemp(prefix="fw_still_"))
    try:
        (tmp / "bin").mkdir()
        etc = tmp / "etc"
        etc.mkdir()
        (etc / "firewall.nft").write_text("ALTE-GUTE-REGELN\n")
        # nft-Attrappe: "list table" liefert Regeln, "-c -f" prueft je nach Fall.
        (tmp / "bin" / "nft").write_text(
            "#!/bin/bash\n"
            "if [ \"$1\" = list ]; then echo 'table inet jarvis_fw { NEUE-REGELN }'; exit 0; fi\n"
            "if [ \"$1\" = -c ]; then exit %d; fi\n"
            "exit 0\n" % (0 if gueltig else 1))
        os.chmod(tmp / "bin" / "nft", 0o755)
        skript = "set -uo pipefail\nFW_ETC=%s\n%s\n_nft_speichern\necho RC=$?\n" % (etc, f_speichern)
        r = subprocess.run(["bash", "-c", skript], capture_output=True, text=True, timeout=30,
                           env={**os.environ, "PATH": "%s:%s" % (tmp / "bin", os.environ.get("PATH", ""))})
        return r.stdout + r.stderr, (etc / "firewall.nft").read_text()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


aus, datei = lauf(True)
check("(Positivkontrolle) gueltige Regeln ersetzen die Datei", "NEUE-REGELN" in datei and "RC=0" in aus,
      (aus[-120:], datei[:60]))
aus, datei = lauf(False)
check("ungueltige Regeln ersetzen die gute Datei NICHT", datei == "ALTE-GUTE-REGELN\n", datei[:60])
check("... und die Funktion meldet einen Fehler", "RC=1" in aus, aus[-160:])

# ── [3] Aufrufort ─────────────────────────────────────────────────────────
print("\n[3] --anwenden")
m = re.search(r"^ +--anwenden\)\n(.*?);;", TEXT, re.S | re.M)
zweig = m.group(1) if m else ""
check("(Positivkontrolle) Zweig --anwenden gefunden", "persistieren" in zweig)
check("persistieren mit Abbruch bei Fehler", bool(re.search(r"persistieren \|\| \{[^}]*exit 1", zweig)),
      zweig[-200:])

print("\nErgebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
