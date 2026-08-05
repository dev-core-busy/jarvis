#!/usr/bin/env python3
"""Tests fuer die Lebensdauer der Anhang-Arbeitskopien (backend/attachments.py).

Hintergrund: die Kopie `/tmp/anhang_<12 Hex>_<name>` muss fuer `jarvis_sandbox`
lesbar sein, und weil alle Domain-Benutzer als dieser eine OS-Benutzer laufen, kann
jeder die Anhaenge aller anderen lesen. Dieses Modul begrenzt die Lebensdauer – die
Tests halten vor allem fest, dass es NICHTS Fremdes anfasst.

    python3 tests/test_attachment_cleanup.py
"""
import os
import sys
import time
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def check(cond, label):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}")


from backend import attachments as at                                  # noqa: E402

# Sandkasten: NIEMALS im echten /tmp arbeiten – dort liegen Arbeitsdateien laufender
# Auftraege. Gleiche Schranke wie in tests/test_log_retention.py.
_tmp = Path(tempfile.mkdtemp(prefix="jarvis_attach_test_"))
at.WORK_DIR = _tmp
if "jarvis_attach_test_" not in str(at.WORK_DIR):
    print("ABBRUCH: WORK_DIR zeigt nicht in das Wegwerf-Verzeichnis")
    sys.exit(2)

ALT = time.time() - 3600          # eine Stunde alt
NEU = time.time() - 60            # eine Minute alt


def mk(name, mtime, inhalt=b"x"):
    p = _tmp / name
    p.write_bytes(inhalt)
    os.utime(p, (mtime, mtime))
    return p


print("\n1. Frist greift")
a_alt = mk("anhang_0123456789ab_tabelle.xlsx", ALT)
a_neu = mk("anhang_0123456789ac_tabelle.xlsx", NEU)
weg = at.cleanup(ttl_min=30)
check(a_alt.name in weg and not a_alt.exists(), "alte Arbeitskopie entfernt")
check(a_neu.exists() and a_neu.name not in weg, "junge Arbeitskopie bleibt")

print("\n2. Fremde Dateien bleiben unberuehrt")
fremd = [
    mk("wichtig.xlsx", ALT),                       # kein Praefix
    mk("anhang_kurz_x.xlsx", ALT),                 # Praefix ohne 12 Hex
    mk("anhang_0123456789abcd_x.xlsx", ALT),       # 14 Hex -> nicht unser Muster
    mk("anhangs_0123456789ab_x.xlsx", ALT),        # anderer Wortstamm
    mk("Anhang_0123456789ab_x.xlsx", ALT),         # Grossschreibung (Muster ist exakt)
    mk("chart.py", ALT),                           # fremdes Agent-Skript
]
weg = at.cleanup(ttl_min=30)
check(weg == [], f"nichts entfernt (Rueckgabe {weg})")
check(all(p.exists() for p in fremd), "alle fremden Dateien noch da")

print("\n3. Verzeichnis und Symlink werden nicht angefasst")
d = _tmp / "anhang_0123456789ad_ordner"
d.mkdir()
os.utime(d, (ALT, ALT))
ziel = _tmp / "geheim.txt"
ziel.write_bytes(b"geheim")
lnk = _tmp / "anhang_0123456789ae_link.xlsx"
lnk.symlink_to(ziel)
os.utime(lnk, (ALT, ALT), follow_symlinks=False)
weg = at.cleanup(ttl_min=30)
check(d.is_dir(), "Verzeichnis bleibt")
check(lnk.is_symlink() and ziel.exists(), "Symlink und sein Ziel bleiben (lstat, nicht stat)")
check(weg == [], "keiner der beiden gemeldet")

print("\n4. Frist-Auflösung")
os.environ["JARVIS_ATTACH_TTL_MIN"] = "0"
check(at.ttl_minutes() == 0, "0 = nie loeschen")
check(at.cleanup() == [], "bei 0 wird nichts entfernt")
_uralt = mk("anhang_0123456789af_uralt.xlsx", time.time() - 999999)
check(at.cleanup() == [], "auch eine uralte Datei bleibt bei 0")
_uralt.unlink()          # nicht als Rueckstand in Abschnitt 5 mitschleppen
os.environ["JARVIS_ATTACH_TTL_MIN"] = "unsinn"
check(at.ttl_minutes() == at.DEFAULT_TTL_MIN, "Tippfehler -> Standard")
os.environ["JARVIS_ATTACH_TTL_MIN"] = "999999"
check(at.ttl_minutes() == 10080, "Deckel 7 Tage")
os.environ["JARVIS_ATTACH_TTL_MIN"] = "45"
check(at.ttl_minutes() == 45, "gueltiger Wert wird uebernommen")
del os.environ["JARVIS_ATTACH_TTL_MIN"]
check(at.ttl_minutes() == 30, "Vorgabe 30 Minuten")
check(callable(at.ttl_minutes), "ttl_minutes ist eine Funktion (nicht beim Import eingefroren)")

print("\n5. Robustheit")
at.WORK_DIR = Path("/gibt/es/nicht")
check(at.cleanup(ttl_min=30) == [], "fehlendes Verzeichnis ist kein Fehler")
at.WORK_DIR = _tmp
# Wiederholter Lauf ist folgenlos (nichts Neues abgelaufen)
check(at.cleanup(ttl_min=30) == [], "zweiter Lauf entfernt nichts mehr")
# 'now' erlaubt eine Frist-Pruefung ohne Warten
check(at.cleanup(ttl_min=1, now=NEU + 120) == [a_neu.name], "now-Parameter laesst die Frist ablaufen")

print("\n6. Verdrahtung in main.py")
_m = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
check("from backend import attachments as _attachments" in _m, "Modul importiert")
check("async def startup_attachment_cleanup" in _m, "Startup-Hook vorhanden")
check("_attachments.cleanup" in _m, "Hook ruft cleanup()")
check("asyncio.to_thread(_attachments.cleanup)" in _m, "laeuft im Thread (blockiert den Loop nicht)")
check("await asyncio.sleep(300)" in _m.split("startup_attachment_cleanup")[1][:3000],
      "wiederholt sich alle 5 Minuten")
# Der Anhang-Block selbst darf die Kopie NICHT direkt loeschen (Folgeanfragen!)
_block = _m.split("ARBEITSKOPIE in /tmp")[1][:2000] if "ARBEITSKOPIE in /tmp" in _m else ""
check("_work.unlink()" not in _block, "Anhang-Block loescht die Kopie nicht sofort")

import shutil                                                          # noqa: E402
shutil.rmtree(_tmp, ignore_errors=True)
print(f"\n{'='*60}\n{_ok} OK, {_fail} FAIL\n{'='*60}")
sys.exit(1 if _fail else 0)
