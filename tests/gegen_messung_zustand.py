#!/usr/bin/env python3
"""Gegenproben zu test_messung_zustand.py – beisst der Waechter noch?

Eine Verschaerfung, die Fehlalarme beseitigt, ist wertlos, wenn sie dabei die
Zaehne verliert. Geprueft wird deshalb in BEIDE Richtungen:

  * ein Skript, das blind einschaltet, MUSS gemeldet werden (Abschnitt 1),
  * ein Skript, das blind abschaltet, MUSS gemeldet werden (Abschnitt 2),
  * ein hermetisches Skript mit Attrappe darf NICHT gemeldet werden,
  * ein Skript, das es richtig macht, darf NICHT gemeldet werden.

⚠ DIE PROBEN ARBEITEN MIT WEGWERF-DATEIEN in tests/, nicht mit echten Skripten.
Der Waechter durchsucht `tests/*.py` selbst – eine Wegwerfdatei ist damit eine
vollwertige Probe, und es kann kein Rueckstand in einer echten Datei bleiben.
Zusaetzlich eine Probe an einer ECHTEN Datei (mit Sicherung auf Platte und
Byte-Kontrolle danach), weil eine synthetische Datei nicht beweist, dass die
Regel auf gewachsenem Code greift.

    python3 tests/gegen_messung_zustand.py
"""
import atexit
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
WAECHTER = TESTS / "test_messung_zustand.py"

ok = fail = 0
_wegwerf = []
_sicherung = {}


def check(text, bedingung, zusatz=""):
    global ok, fail
    if bedingung:
        ok += 1
        print("  OK   %s" % text)
    else:
        fail += 1
        print("  FAIL %s%s" % (text, ("  [" + str(zusatz) + "]") if zusatz else ""))


def aufraeumen():
    for p in _wegwerf:
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    for p, inhalt in _sicherung.items():
        p.write_text(inhalt, encoding="utf-8")


atexit.register(aufraeumen)


def lauf():
    """(exit_code, bilanzzeile_gefunden, fail_anzahl)."""
    r = subprocess.run([sys.executable, str(WAECHTER)],
                       capture_output=True, text=True, timeout=300)
    aus = r.stdout
    bilanz = [z for z in aus.splitlines() if "Ergebnis:" in z]
    # ⚠ AM EXIT-CODE **UND** AN DER BILANZ MESSEN. Ein Waechter, der abbricht,
    # liefert keine Bilanz – das ist von "bestanden" nicht zu unterscheiden.
    return r.returncode, bool(bilanz), aus.count("✗")


def wegwerf(name, inhalt):
    p = TESTS / name
    if p.exists():
        print("ABBRUCH: %s existiert bereits – keine Wegwerfdatei" % name)
        sys.exit(2)
    p.write_text(inhalt, encoding="utf-8")
    _wegwerf.append(p)
    return p


# ── Basislauf: ohne gruene Basis ist keine Gegenprobe deutbar ───────────────
rc, bilanz, fails = lauf()
if rc != 0 or not bilanz:
    print("ABBRUCH: Basislauf ist nicht gruen (rc=%s, Bilanz=%s, FAIL=%d) – "
          "eine Gegenprobe waere nicht deutbar" % (rc, bilanz, fails))
    sys.exit(2)
print("Basislauf gruen (rc=0, Bilanzzeile vorhanden)\n")

print("1. Synthetische Proben (Wegwerfdateien in tests/)")

# (a) blindes Einschalten, kein Lesen des Vorzustands -> MUSS melden
wegwerf("live_zz_probe_blind_dev.py",
        "import requests\n"
        "S = requests.Session()\n"
        "BASIS = 'https://127.0.0.1'\n"
        "S.post(BASIS + '/api/skills/probe/enable', timeout=90)\n")
rc, bilanz, fails = lauf()
check("blindes Einschalten wird gemeldet", rc != 0 and bilanz, "rc=%s" % rc)
aufraeumen(); _wegwerf.clear()

# (b) Einschalten MIT gelesenem Vorzustand -> darf NICHT melden
wegwerf("live_zz_probe_gut_dev.py",
        "import requests\n"
        "S = requests.Session()\n"
        "BASIS = 'https://127.0.0.1'\n"
        "vorgefunden = S.get(BASIS + '/api/skills').json()\n"
        "war_an = any(x.get('enabled') for x in vorgefunden)\n"
        "S.post(BASIS + '/api/skills/probe/enable', timeout=90)\n"
        "if not war_an:\n"
        "    S.post(BASIS + '/api/skills/probe/disable', timeout=90)\n")
rc, bilanz, fails = lauf()
check("ein korrektes Skript wird NICHT gemeldet", rc == 0 and bilanz, "rc=%s" % rc)
aufraeumen(); _wegwerf.clear()

# (c) ⚠ DER GEMELDETE FALL: blindes Abschalten im finally -> MUSS melden
wegwerf("live_zz_probe_disable_dev.py",
        "import requests\n"
        "S = requests.Session()\n"
        "BASIS = 'https://127.0.0.1'\n"
        "vorgefunden = S.get(BASIS + '/api/skills').json()\n"
        "war_an = any(x.get('enabled') for x in vorgefunden)\n"
        "try:\n"
        "    S.post(BASIS + '/api/skills/probe/enable', timeout=90)\n"
        "finally:\n"
        "    S.post(BASIS + '/api/skills/probe/disable', timeout=90)\n")
rc, bilanz, fails = lauf()
check("blindes Abschalten im Aufraeumen wird gemeldet", rc != 0 and bilanz, "rc=%s" % rc)
aufraeumen(); _wegwerf.clear()

# (d) hermetisch: Attrappe statt echtem Zustand -> darf NICHT melden
wegwerf("test_zz_probe_attrappe.py",
        "import sys, types\n"
        "_m = types.ModuleType('backend.config')\n"
        "class _C:\n"
        "    def get_skill_states(self):\n"
        "        return {}\n"
        "    def save_skill_state(self, name, state):\n"
        "        pass\n"
        "_m.config = _C()\n"
        "sys.modules['backend.config'] = _m\n")
rc, bilanz, fails = lauf()
check("⚠ eine reine Attrappe wird NICHT gemeldet (der behobene Fehlalarm)",
      rc == 0 and bilanz, "rc=%s" % rc)
aufraeumen(); _wegwerf.clear()

print("\n2. Probe an einer ECHTEN Datei (mit Sicherung)")

# ⚠ TREFFERKONTROLLE: eine Ersetzung ohne assert ist kein Messwert – sie
# "beisst" sonst scheinbar nicht, weil sie gar nicht gegriffen hat.
echt = TESTS / "live_vemas_dev.py"
inhalt = echt.read_text(encoding="utf-8")
vorher_md5 = hashlib.md5(inhalt.encode()).hexdigest()
_sicherung[echt] = inhalt

# ⚠ DIE GEFORDERTE GEGENPROBE: den ZURUECKSTELL-Schritt entfernen, also aus der
# fallabhaengigen Wiederherstellung ein blindes Abschalten machen. Genau das ist
# der gemeldete Fehler vom 2026-09-09.
#
# ⚠ EIN FRUEHERER ANLAUF HAT HIER ETWAS ANDERES SABOTIERT (die Zuweisung des
# Vorzustands) und daraus "Waechter blind" geschlossen – falsch: die Datei liest
# den Skill-Zustand an weiteren Stellen (`sk`, `eintrag`), die Eigenschaft aus
# Abschnitt 1 blieb also zu Recht erfuellt. Eine Gegenprobe muss die Stelle
# treffen, die sie meint.
ALT = ('        if not _vemas_war_an:      # nur abschalten, wenn er vorher AUS war\n'
       '            S.post(BASIS + "/api/skills/vemas/disable", timeout=60)\n')
NEU = '        S.post(BASIS + "/api/skills/vemas/disable", timeout=60)\n'

if ALT not in inhalt:
    check("der fallabhaengige Rueckstell-Block wurde gefunden", False,
          "Anker passt nicht mehr – Probe nicht durchfuehrbar")
else:
    neu = inhalt.replace(ALT, NEU, 1)
    check("Sabotage hat gegriffen (Trefferkontrolle)", neu != inhalt)
    echt.write_text(neu, encoding="utf-8")
    rc, bilanz, fails = lauf()
    check("⚠ entfernter Zurueckstell-Schritt an ECHTER Datei wird gemeldet",
          rc != 0 and bilanz, "rc=%s" % rc)
    echt.write_text(inhalt, encoding="utf-8")
    check("Datei byte-gleich wiederhergestellt",
          hashlib.md5(echt.read_text(encoding='utf-8').encode()).hexdigest() == vorher_md5)

print("\n3. Abschlusslauf: der Waechter ist wieder gruen")
rc, bilanz, fails = lauf()
check("Abschlusslauf gruen (kein Rueckstand)", rc == 0 and bilanz and fails == 0,
      "rc=%s FAIL=%d" % (rc, fails))

print("\nErgebnis: %d OK, %d FAIL" % (ok, fail))
sys.exit(1 if fail else 0)
