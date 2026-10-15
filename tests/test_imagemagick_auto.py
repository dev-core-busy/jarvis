"""Waechter: ImageMagick wird beim Broker-Start nachinstalliert (start_jarvis_root.sh, 6i).

⚠ DER GEMELDETE FALL (ECHT, 2026-10-12): ein Benutzer liess ein PDF in ein Bild
umwandeln, das Modell rief ``convert`` auf -> "convert: Kommando nicht gefunden",
Exit 127. Auf DEV und ECHT lag nur ``imagemagick-7-common`` (Daten, kein
Programm). Derselbe Fehler stand schon am 2026-10-06 in einer Lernnotiz – die
hat den zweiten Fall nicht verhindert.

Gemessen wird die WIRKUNG des Abschnitts, nicht sein Text: der Block wird aus
dem Skript geschnitten und unter bash mit einem Attrappen-PATH ausgefuehrt
(``apt-get`` protokolliert nur, ``convert``/``magick`` liegen je nach Fall da
oder nicht). Ausserdem: der Systemprompt nennt ImageMagick und pdftoppm.

Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
``JARVIS_TEST_QUELLE`` ersetzt das Skript (fuer die Gegenprobe).
"""
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
QUELLE = Path(os.environ.get("JARVIS_TEST_QUELLE") or WURZEL / "start_jarvis_root.sh")
AGENT = WURZEL / "backend" / "agent.py"

ok = fail = 0


def pruef(name, bed, info=""):
    global ok, fail
    if bed:
        ok += 1
        print(f"  OK    {name}")
    else:
        fail += 1
        print(f"  FAIL  {name}" + (f"  [{info}]" if info else ""))


# --- Positivkontrolle: Werkzeuge und Abschnitt vorhanden ---------------------
BASH = shutil.which("bash")
HILFEN = {n: shutil.which(n) for n in ("tail", "sed", "cat")}
if not BASH or not all(HILFEN.values()):
    print(f"ABBRUCH: bash/tail/sed/cat fehlen ({HILFEN})")
    sys.exit(2)

skript = QUELLE.read_text(encoding="utf-8")
m = re.search(r"^# 6i\..*?(?=^# \d+[a-z]?\. )", skript, re.S | re.M)
if not m:
    print("ABBRUCH: Abschnitt '# 6i.' nicht gefunden – nichts zu messen")
    sys.exit(2)
block = m.group(0)

APT_STUB = r'''#!/bin/sh
printf '%s|%s\n' "$DEBIAN_FRONTEND" "$*" >> "$PROTOKOLL"
if [ "$APT_RC" = "0" ] && [ "$APT_LIEFERT" = "1" ]; then
    printf '#!/bin/sh\nexit 0\n' > "$STUBDIR/convert"; chmod +x "$STUBDIR/convert"
fi
exit "$APT_RC"
'''


def lauf(vorhanden=(), env_zusatz=None, apt_rc=0, apt_liefert=True):
    """Fuehrt den Block aus. Rueckgabe: (rc, stdout, stderr, apt-Aufrufe)."""
    with tempfile.TemporaryDirectory() as td:
        stub = Path(td) / "bin"
        stub.mkdir()
        for name, ziel in HILFEN.items():
            (stub / name).symlink_to(ziel)
        apt = stub / "apt-get"
        apt.write_text(APT_STUB)
        apt.chmod(apt.stat().st_mode | stat.S_IEXEC)
        for name in vorhanden:
            p = stub / name
            p.write_text("#!/bin/sh\nexit 0\n")
            p.chmod(0o755)
        protokoll = Path(td) / "apt.log"
        env = {"PATH": str(stub), "PROTOKOLL": str(protokoll), "STUBDIR": str(stub),
               "APT_RC": str(apt_rc), "APT_LIEFERT": "1" if apt_liefert else "0"}
        env.update(env_zusatz or {})
        r = subprocess.run([BASH, "-c", block + "\nwait\n"], env=env,
                           capture_output=True, text=True, timeout=30)
        aufrufe = protokoll.read_text().splitlines() if protokoll.exists() else []
        return r.returncode, r.stdout, r.stderr, aufrufe


print("1. Beides fehlt -> Nachinstallation")
rc, out, err, auf = lauf()
pruef("apt-get genau einmal aufgerufen", len(auf) == 1, str(auf))
pruef("Aufruf ist 'install -y imagemagick'",
      any(a.split("|", 1)[-1].split() == ["install", "-y", "imagemagick"] for a in auf), str(auf))
pruef("nicht-interaktiv (DEBIAN_FRONTEND=noninteractive)",
      bool(auf) and all(a.split("|", 1)[0] == "noninteractive" for a in auf), str(auf))
pruef("Erfolg wird gemeldet", "[ImageMagick] installiert" in out, out[-200:])
pruef("keine Warnung bei Erfolg", "WARNUNG" not in err, err[-200:])

print("2. Bereits vorhanden -> nichts tun")
for vorh in (("convert",), ("magick",), ("convert", "magick")):
    rc, out, err, auf = lauf(vorhanden=vorh)
    pruef(f"mit {'+'.join(vorh)}: kein apt-get", auf == [], str(auf))

print("3. Abschaltbar")
rc, out, err, auf = lauf(env_zusatz={"JARVIS_IMAGEMAGICK_AUTO": "0"})
pruef("JARVIS_IMAGEMAGICK_AUTO=0: kein apt-get", auf == [], str(auf))

print("4. Fail-open mit Meldung")
rc, out, err, auf = lauf(apt_rc=100, apt_liefert=False)
pruef("apt scheitert: Block endet trotzdem mit 0", rc == 0, f"rc={rc}")
pruef("apt scheitert: WARNUNG auf stderr", "[ImageMagick] WARNUNG" in err, err[-200:])
pruef("apt scheitert: kein Erfolg gemeldet", "[ImageMagick] installiert" not in out, out[-200:])
rc, out, err, auf = lauf(apt_rc=0, apt_liefert=False)
pruef("apt meldet 0, Programm fehlt trotzdem: WARNUNG", "[ImageMagick] WARNUNG" in err, err[-200:])

print("5. Lage im Skript")
pos_block = m.start()
m7 = re.search(r"^# 7\. Root-Broker starten", skript, re.M)
pruef("Abschnitt steht VOR dem Broker-Start (Abschnitt 7)",
      m7 is not None and pos_block < m7.start(), "Abschnitt 7 nicht gefunden" if not m7 else "")
pruef("apt laeuft im Hintergrund (haelt den Broker-Start nicht auf)",
      re.search(r"\)\s*&\s*\nfi\s*$", block.rstrip() + "\n") is not None)

print("6. Systemprompt nennt die Werkzeuge")
agent = AGENT.read_text(encoding="utf-8")
zeile = next((z for z in agent.splitlines() if "Auf dem Server sind installiert" in z), "")
if not zeile:
    print("ABBRUCH: Liste 'Auf dem Server sind installiert' im Prompt nicht gefunden")
    sys.exit(2)
pruef("ImageMagick mit convert/magick genannt", "ImageMagick" in zeile and "`convert`" in zeile)
pruef("pdftoppm -singlefile als Weg PDF -> Bild genannt", "pdftoppm -singlefile" in zeile)

print(f"\n{ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
