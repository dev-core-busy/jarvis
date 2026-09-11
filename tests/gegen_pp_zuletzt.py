#!/usr/bin/env python3
"""Gegenproben: die Anweisung des Benutzers steht ZULETZT im System-Prompt.

Jede Probe dreht GENAU EINE Zusage zurueck und misst, ob der Waechter beisst.
Eine Probe, die nicht beisst, ist ein Testmangel – kein Beweis.

⚠ SICHERUNG AUF PLATTE, nicht im Speicher: wird dieser Lauf abgeschossen
(Zeitlimit), bliebe der Arbeitsbaum sonst sabotiert zurueck, und der naechste
Testlauf meldete Fehler, die der Code nicht hat. Ein Rueckstand wird beim
naechsten Start selbst zurueckgenommen; nach dem Wiederherstellen wird auf
BYTE-Gleichheit geprueft.

⚠ GEMESSEN WIRD EXIT-CODE UND BILANZZEILE, nicht die Zahl der FAIL-Zeilen: ein
Waechter, der abbricht, liefert 0 FAIL und sieht wie ein bestandener aus.
"""
import atexit
import hashlib
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ZIEL = ROOT / "backend" / "agent.py"
WAECHTER = ROOT / "tests" / "test_chat_prompt.py"
ABLAGE = Path.home() / ".gegen-pp-zuletzt"


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


# Rueckstand eines abgeschossenen Vorlaufs zuerst zuruecknehmen.
ABLAGE.mkdir(mode=0o700, exist_ok=True)
sicherung = ABLAGE / "agent.py"
if sicherung.exists():
    if md5(sicherung) != md5(ZIEL):
        print("⚠ Rueckstand eines frueheren Laufs gefunden – stelle her.")
        shutil.copy2(sicherung, ZIEL)
    sicherung.unlink()

shutil.copy2(ZIEL, sicherung)
SOLL = md5(ZIEL)


def zurueck(*_a):
    if sicherung.exists():
        shutil.copy2(sicherung, ZIEL)
        if md5(ZIEL) != SOLL:
            print("⚠⚠ WIEDERHERSTELLUNG NICHT BYTE-GLEICH!")
        sicherung.unlink()


atexit.register(zurueck)
signal.signal(signal.SIGTERM, lambda *a: (zurueck(), sys.exit(2)))

ORIG = ZIEL.read_text(encoding="utf-8")


def lauf() -> tuple[int, int, str]:
    """(exitcode, FAIL-Zahl, Bilanzzeile) des Waechters."""
    p = subprocess.run([sys.executable, str(WAECHTER)], capture_output=True,
                       text=True, timeout=300)
    bilanz = ""
    for z in reversed((p.stdout or "").splitlines()):
        if z.startswith("Ergebnis:"):
            bilanz = z.strip()
            break
    fails = (p.stdout or "").count("  FAIL ")
    return p.returncode, fails, bilanz


def probe(name: str, alt: str, neu: str, anzahl: int = 1):
    s = ORIG
    if alt not in s:
        print("  ⚠ %-46s ANKER NICHT GETROFFEN – Probe ungueltig" % name)
        return
    ZIEL.write_text(s.replace(alt, neu, anzahl), encoding="utf-8")
    rc, fails, bilanz = lauf()
    ZIEL.write_text(ORIG, encoding="utf-8")
    if not bilanz:
        print("  ⚠ %-46s ABBRUCH OHNE BILANZ (rc=%d)" % (name, rc))
    elif rc == 0:
        print("  ✗ %-46s BEISST NICHT (%s)" % (name, bilanz))
    else:
        print("  ✓ %-46s %d FAIL  (%s)" % (name, fails, bilanz))


print("=" * 78)
print("Basis zuerst – ohne gruene Basis ist keine Gegenprobe deutbar")
rc, fails, bilanz = lauf()
print("  Basis: rc=%d  %s" % (rc, bilanz))
if rc != 0:
    print("ABBRUCH: Basis ist nicht gruen.")
    sys.exit(2)
print("=" * 78)

# 1) Der ganze Fix zurueck: der Block haengt wieder selbst an (alte Stelle).
probe("Altstand: Block haengt selbst an (77 %)",
      """                _pre_block = (
                    "\\n\\n[PERSÖNLICHE ANWEISUNG DES BENUTZERS""",
      """                system_prompt += (
                    "\\n\\n[PERSÖNLICHE ANWEISUNG DES BENUTZERS""")

# 2) Anhaeng-Schritt ganz weg -> die Anweisung erreicht den Prompt NIE.
probe("Anhaeng-Schritt entfernt",
      "        if _pre_block:\n            system_prompt += _pre_block\n",
      "")

# 3) Anhaengen VOR dem Gedaechtnis-Block -> nicht mehr zuletzt.
probe("angehaengt VOR dem Gedaechtnis-Block",
      """        memory_context = load_selective_memory(task_text, username=username)""",
      """        if _pre_block:
            system_prompt += _pre_block
        memory_context = load_selective_memory(task_text, username=username)""")

# 4) Nachtrag-Zweig zurueck -> nach werkzeuge_anfordern nicht mehr zuletzt.
probe("Buendel-Nachtrag haengt wieder stumpf an",
      """                _nachtrag = self._buendel_prompt_nachtrag()
                if _nachtrag and _pre_block and system_prompt.endswith(_pre_block):
                    system_prompt = (system_prompt[:-len(_pre_block)]
                                     + _nachtrag + _pre_block)
                else:
                    system_prompt += _nachtrag""",
      """                system_prompt += self._buendel_prompt_nachtrag()""")

# 5) Initialisierung weg -> Sub-Agenten-Lauf wirft UnboundLocalError.
probe("`_pre_block = \"\"` entfernt",
      '        _pre_block = ""\n        if not self.is_sub_agent and username:',
      "        if not self.is_sub_agent and username:")

print("=" * 78)
print("✓ = beisst · ✗ = Testmangel · ⚠ = Probe/Waechter untauglich")
