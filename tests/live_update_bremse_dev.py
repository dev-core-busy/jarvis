#!/usr/bin/env python3
"""Die Schleifen-Bremse des Update-Wegs – AUSGEFUEHRT, nicht gelesen.

Gemeldet 2026-09-14: „es wird JETZT JEDESMAL die neue exe auf den Rechner
kopiert." Auf Platte lag bereits 1.0.6, im Speicher lief weiter 1.0.5, und
zwischen zwei Screenshots im Abstand einer Minute lagen zwei volle Zyklen zu je
66 MB.

⚠ WARUM DAS HIER UND NICHT IM QUELLTEXT-WAECHTER STEHT: ob die Bremse WIRKT,
kann eine Textpruefung nicht beantworten – eine totgelegte Bedingung
(`if (false && ...)`) laesst jede Suche gruen. Das hat eine Gegenprobe belegt.
Gemessen wird deshalb die ECHTE `Aktualisierung.cs`: sie wird mit einer
Attrappe fuer die Registry uebersetzt und der Ablauf gefahren.

⚠ DIE TESTASSEMBLY TRAEGT 1.0.5 – damit ist `Aktualisierung.EigeneAnzeige`
genau die Fassung aus der Meldung, und der Fall ist der echte, nicht ein
gedachter.

Aufruf (auf DEV, dort liegt das SDK):
    python3 tests/live_update_bremse_dev.py
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "update_bremse"
QUELLE = ROOT / "ai-mouse" / "src" / "AiMouse" / "Update" / "Aktualisierung.cs"

# Das SDK liegt nicht im PATH (Debian 13 hat kein apt-Paket dafuer).
KANDIDATEN = [ROOT / "vendor" / "dotnet", Path("/opt/jarvis/vendor/dotnet")]


def dotnet_wurzel():
    for k in KANDIDATEN:
        if (k / "dotnet").is_file():
            return k
    p = shutil.which("dotnet")
    return Path(p).parent if p else None


def main():
    wurzel = dotnet_wurzel()
    if wurzel is None:
        # ⚠ EXIT 2, NICHT 0: „konnte nicht laufen" darf nie wie „bestanden"
        # aussehen (Register).
        print("ABBRUCH: kein .NET-SDK gefunden (gesucht: %s)"
              % ", ".join(str(k) for k in KANDIDATEN))
        return 2
    if not QUELLE.is_file():
        print("ABBRUCH: %s fehlt" % QUELLE)
        return 2

    with tempfile.TemporaryDirectory() as d:
        w = Path(d) / "src"
        w.mkdir(parents=True)
        for f in FIX.iterdir():
            shutil.copy2(f, w / f.name)
        # ⚠ DIE ECHTE DATEI, nicht nachgebaut – nur der Registry-Zugriff ist
        # gestellt. Ein Nachbau wuerde die eigene Annahme pruefen.
        shutil.copy2(QUELLE, w / "Aktualisierung.cs")

        umgebung = {
            "PATH": "%s:%s" % (wurzel, "/usr/bin:/bin"),
            "DOTNET_ROOT": str(wurzel),
            "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
            "DOTNET_NOLOGO": "1",
            "HOME": d,
        }
        bau = subprocess.run(
            [str(wurzel / "dotnet"), "build", "-c", "Release", "--nologo"],
            cwd=w, env=umgebung, capture_output=True, text=True, timeout=600)
        if bau.returncode != 0:
            print("ABBRUCH: uebersetzt nicht\n" + bau.stdout[-2500:])
            return 2

        exe = w / "bin" / "Release" / "net8.0" / "brems"
        if not exe.is_file():
            print("ABBRUCH: kein Messprogramm gebaut")
            return 2

        lauf = subprocess.run([str(exe)], cwd=w, env=umgebung,
                              capture_output=True, text=True, timeout=300)
        print(lauf.stdout.rstrip())
        if lauf.stderr.strip():
            print(lauf.stderr.rstrip())
        if "Ergebnis:" not in lauf.stdout:
            print("ABBRUCH: keine Bilanzzeile – Lauf unvollstaendig")
            return 2
        return lauf.returncode


if __name__ == "__main__":
    sys.exit(main())
