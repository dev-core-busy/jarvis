#!/usr/bin/env python3
"""Gegenproben zur AUSGEFUEHRTEN Worker-Messung (`live_uia_worker_dev.py`).

⚠ WOZU: eine Messung, die den gemeldeten Fehler gar nicht zeigen KANN, beweist
nichts. `live_uia_worker_dev.py` meldet „kein weiterer Thread" – hier wird
belegt, dass es genau das auch zu melden aufhoert, sobald die Schranke faellt.

Die Proben liegen absichtlich HIER und nicht in `gegen_am_beenden.py`: jene
misst den Quelltext-Waechter, diese die Ausfuehrung. Eine Gegenprobe gehoert
an den Ort der Messung, die sie prueft (Register, 2026-09-10).
"""
import atexit
import hashlib
import pathlib
import re
import shutil
import signal
import subprocess
import sys

ROOT = pathlib.Path("/home/bender/ai/projekte/jarvis")
ABL = pathlib.Path.home() / ".gegen-uia-worker"
MARKE = ABL / "LAUF"

# ⚠ Die Messdatei steht MIT drin, obwohl keine Probe sie veraendert: die Regel
#   unten verlangt jede genannte Datei, und eine zu viel zu sichern ist
#   harmlos – eine zu wenig war am 2026-09-11 der Grund, warum eine Sabotage
#   liegen blieb und der naechste Lauf einen FAIL meldete, den es nicht gab.
DATEIEN = [
    "ai-mouse/src/AiMouse/Input/ZiehbarPruefer.cs",
    "tests/live_uia_worker_dev.py",
]
ZP = DATEIEN[0]


def sichern():
    ABL.mkdir(mode=0o700, exist_ok=True)
    for rel in DATEIEN:
        shutil.copy2(ROOT / rel, ABL / rel.replace("/", "__"))
    MARKE.write_text("laeuft\n", encoding="utf-8")


def zurueck(still=False):
    for rel in DATEIEN:
        q = ABL / rel.replace("/", "__")
        if q.exists():
            shutil.copy2(q, ROOT / rel)
    if not still:
        for rel in DATEIEN:
            a = hashlib.md5((ABL / rel.replace("/", "__")).read_bytes()).hexdigest()
            b = hashlib.md5((ROOT / rel).read_bytes()).hexdigest()
            if a != b:
                print("  ⚠ NICHT wiederhergestellt: " + rel)


def ende():
    zurueck(still=True)
    if MARKE.exists():
        MARKE.unlink()


def ersetze(rel, alt, neu):
    s = (ROOT / rel).read_text(encoding="utf-8")
    assert alt in s, "Anker fehlt in %s: %r" % (rel, alt[:60])
    (ROOT / rel).write_text(s.replace(alt, neu, 1), encoding="utf-8")


def messung():
    """(fails, bilanz_da) – gemessen wird die BILANZZEILE, nicht nur der Code."""
    p = subprocess.run([sys.executable, "tests/live_uia_worker_dev.py"], cwd=ROOT,
                       capture_output=True, text=True, timeout=900)
    m = re.search(r"^(\d+) OK, (\d+) FAIL$", p.stdout, re.M)
    return (int(m.group(2)), True) if m else (-1, False)


PROBEN = []


def probe(name):
    def deko(fn):
        PROBEN.append((name, fn))
        return fn
    return deko


@probe("DER GEMELDETE FALL: Besetzt-Schranke weg -> Auftraege stapeln sich")
def _():
    # Ohne die Schranke laeuft JEDE Abfrage in die volle Zeitgrenze, und der
    # haengende Worker wird immer wieder neu beauftragt.
    #
    # ⚠ DIE BEDINGUNG WIRD ENTSCHAERFT, NICHT DER AUFRUF ENTFERNT. Ein
    #   `if (false)` haette den Text `Interlocked.CompareExchange` mit
    #   weggenommen – und die Messung steigt dann schon an ihrer
    #   Schnitt-Positivkontrolle aus, ohne je einen Thread zu zaehlen. Die
    #   Sabotage haette „gebissen", ohne zu belegen, dass die Messung den
    #   Fehler SIEHT.
    ersetze(ZP, "if (Interlocked.CompareExchange(ref _beschaeftigt, 1, 0) != 0)",
            "if (Interlocked.CompareExchange(ref _beschaeftigt, 1, 0) > 9999)")


@probe("ein Thread JE ABFRAGE (der Altstand bis 1.0.5)")
def _():
    s = (ROOT / ZP).read_text(encoding="utf-8")
    alt = """        if (Interlocked.CompareExchange(ref _beschaeftigt, 1, 0) != 0)
        {
            return false;
        }

        if (!WorkerSicherstellen())
        {
            Interlocked.Exchange(ref _beschaeftigt, 0);
            return false;
        }

        _punkt = p;
        _ergebnis = false;
"""
    assert alt in s, "Anker der Abfrage fehlt"
    # Der Altstand: jede Abfrage baut sich ihren eigenen Thread und gibt ihn
    # nach der Zeitgrenze auf.
    neu = """        _punkt = p;
        _ergebnis = false;
        var eigener = new Thread(() =>
        {
            try { _ergebnis = Attrappe.Messen(p); } catch { _ergebnis = false; }
        })
        { IsBackground = true };
        eigener.Start();
        return eigener.Join(grenze) && _ergebnis;
        #pragma warning disable CS0162
"""
    s = s.replace(alt, neu, 1)
    (ROOT / ZP).write_text(s, encoding="utf-8")


@probe("der Worker gibt sich selbst nicht frei (bleibt fuer immer besetzt)")
def _():
    ersetze(ZP,
            "            _fertig.Set();\n"
            "            Interlocked.Exchange(ref _beschaeftigt, 0);",
            "            _fertig.Set();")


def main():
    if MARKE.exists():
        print("⚠ Rueckstand eines abgebrochenen Laufs – nehme ihn zurueck.")
        zurueck(still=True)

    # REGEL: was eine Probe anfasst, muss gesichert sein.
    quelle = pathlib.Path(__file__).read_text(encoding="utf-8")
    genannt = {d for d in re.findall(r'"([\w/.-]+\.(?:cs|csproj|py))"', quelle)
               if (ROOT / d).exists()}
    fehlend = genannt - set(DATEIEN)
    if fehlend:
        print("⚠ NICHT GESICHERT: " + ", ".join(sorted(fehlend)))
        sys.exit(2)

    sichern()
    atexit.register(ende)
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(1))

    basis, da = messung()
    if not da or basis != 0:
        print("⚠ BASIS NICHT GRUEN (%s FAIL) – ohne gruene Basis ist keine "
              "Gegenprobe deutbar." % basis)
        sys.exit(2)
    print("Basis gruen (%d Proben)\n" % len(PROBEN))

    stumm = []
    for name, fn in PROBEN:
        zurueck(still=True)
        try:
            fn()
        except AssertionError as e:
            print("  ⚠ SABOTAGE VERFEHLT: %s – %s" % (name, e))
            stumm.append(name + " (verfehlt)")
            continue
        fails, bilanz = messung()
        if not bilanz:
            # ⚠ EIN ABBRUCH IST HIER EIN GUELTIGES BEISSEN, aber er muss
            #   BENANNT werden: der Altstand laesst sich gar nicht mehr
            #   schneiden, und das ist eine andere Aussage als "gemessen und
            #   fehlgeschlagen".
            print("  beisst  (Abbruch statt Bilanz)  " + name)
        elif fails == 0:
            print("  STUMM   " + name)
            stumm.append(name)
        else:
            print("  beisst  %3d FAIL  %s" % (fails, name))

    zurueck()
    print("\n%d von %d Proben beissen." % (len(PROBEN) - len(stumm), len(PROBEN)))
    if stumm:
        print("STUMM: " + "; ".join(stumm))
    sys.exit(1 if stumm else 0)


if __name__ == "__main__":
    main()
