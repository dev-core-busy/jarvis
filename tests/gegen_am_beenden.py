#!/usr/bin/env python3
"""Gegenproben zu 1.0.6: die Anwendung laesst sich beenden (2026-09-14).

Jede Probe dreht GENAU EINE Zusage zurueck. Eine Gegenprobe, die nicht beisst,
ist ein Testmangel - kein Beweis.

⚠ DER HARNESS SICHERT JEDE DATEI, DIE ANGEFASST WIRD - auch `Vorgaben.cs`, die
der WAECHTER selbst beschreibt (er ruft `paket_bauen`), und `test_ai_mouse.py`,
die eine Probe hier sabotiert. Am 2026-09-11 hat genau diese Auslassung eine
Sabotage stehen lassen, und der naechste Lauf meldete einen FAIL, den es im
Code nicht gab. Die Liste wird deshalb unten als REGEL geprueft, nicht
gepflegt.
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
ABL = pathlib.Path.home() / ".gegen-am-beenden"
MARKE = ABL / "LAUF"

DATEIEN = [
    "ai-mouse/src/AiMouse/Program.cs",
    "ai-mouse/src/AiMouse/Input/ZiehbarPruefer.cs",
    "ai-mouse/src/AiMouse/Start/Prozessende.cs",
    "ai-mouse/src/AiMouse/Interop/NativeMethods.cs",
    "ai-mouse/src/AiMouse/AiMouse.csproj",
    "ai-mouse/src/AiMouse/Configuration/Vorgaben.cs",
    "tests/test_ai_mouse.py",
]


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


def lies(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def ersetze(rel, alt, neu, anzahl=1):
    s = lies(rel)
    assert s.count(alt) >= anzahl, "Anker fehlt in %s: %r" % (rel, alt[:60])
    (ROOT / rel).write_text(s.replace(alt, neu, anzahl), encoding="utf-8")


def waechter():
    """(fails, bilanz_da) - gemessen wird die BILANZZEILE, nicht nur der Code.

    Ein Lauf, der ohne Bilanz abbricht, ist von 'nicht gelaufen' nicht zu
    unterscheiden.
    """
    p = subprocess.run([sys.executable, "tests/test_ai_mouse.py"], cwd=ROOT,
                       capture_output=True, text=True, timeout=300)
    m = re.search(r"^(\d+) OK, (\d+) FAIL$", p.stdout, re.M)
    return (int(m.group(2)), True) if m else (-1, False)


PROBEN = []


def probe(name):
    def deko(fn):
        PROBEN.append((name, fn))
        return fn
    return deko


PROG = "ai-mouse/src/AiMouse/Program.cs"
ZP = "ai-mouse/src/AiMouse/Input/ZiehbarPruefer.cs"
PE = "ai-mouse/src/AiMouse/Start/Prozessende.cs"
NM = "ai-mouse/src/AiMouse/Interop/NativeMethods.cs"


# ── a) Der gemeldete Fall: ein Thread je Abfrage ──────────────────────────
@probe("DER GEMELDETE FALL: wieder ein Thread JE ABFRAGE")
def _():
    s = lies(ZP)
    alt = """        if (Interlocked.CompareExchange(ref _beschaeftigt, 1, 0) != 0)
        {
            return false;
        }

        if (!WorkerSicherstellen())
        {
            Interlocked.Exchange(ref _beschaeftigt, 0);
            return false;
        }
"""
    assert alt in s, "Anker der Besetzt-Schranke fehlt"
    # Der Altstand: jede Abfrage baut sich ihren eigenen STA-Thread.
    neu = """        var t = new Thread(() => { }) { IsBackground = true };
        t.SetApartmentState(ApartmentState.STA);
        t.Start();
        if (!t.Join(grenze)) { return false; }
"""
    (ROOT / ZP).write_text(s.replace(alt, neu, 1), encoding="utf-8")


@probe("die Besetzt-Schranke faellt weg (Auftraege stapeln sich)")
def _():
    ersetze(ZP, "if (Interlocked.CompareExchange(ref _beschaeftigt, 1, 0) != 0)",
            "if (false)")


@probe("der Aufrufer gibt den Worker nach dem Timeout frei")
def _():
    ersetze(ZP, "        return _fertig.WaitOne(grenze) && _ergebnis;",
            "        bool r = _fertig.WaitOne(grenze) && _ergebnis;\n"
            "        Interlocked.Exchange(ref _beschaeftigt, 0);\n"
            "        return r;")


@probe("der Worker gibt sich NICHT selbst frei")
def _():
    # ⚠ GEZIELT AUF DIE ZEILE IM WORKER. Die Freigabe steht ZWEIMAL in der
    #    Datei und beide Male gleich eingerueckt - die erste Fassung dieser
    #    Probe traf die im Aufrufer-Zweig und war dadurch stumm. Nicht der
    #    Waechter war zahnlos, die Sabotage hat ihr Ziel verfehlt (Register).
    #    Der Anker ist deshalb das vorangehende `_fertig.Set()`.
    ersetze(ZP,
            "            _fertig.Set();\n"
            "            Interlocked.Exchange(ref _beschaeftigt, 0);",
            "            _fertig.Set();")


@probe("im Worker wird erst freigegeben, dann gemeldet")
def _():
    s = lies(ZP)
    alt = """            _fertig.Set();
            Interlocked.Exchange(ref _beschaeftigt, 0);"""
    assert alt in s, "Anker der Reihenfolge fehlt"
    neu = """            Interlocked.Exchange(ref _beschaeftigt, 0);
            _fertig.Set();"""
    (ROOT / ZP).write_text(s.replace(alt, neu, 1), encoding="utf-8")


@probe("das Alt-Signal wird nicht verworfen (Ergebnis des VORIGEN Punktes)")
def _():
    ersetze(ZP, "        _fertig.Reset();\n", "")


@probe("der Worker ist ein Vordergrund-Thread (verhindert das Beenden)")
def _():
    ersetze(ZP, "                    IsBackground = true,", "                    IsBackground = false,")


@probe("kein STA (COM verlangt es)")
def _():
    ersetze(ZP, "                t.SetApartmentState(ApartmentState.STA);", "")


# ── b) Das Netz darunter: hartes Prozessende ──────────────────────────────
@probe("Main beendet wieder ueber den normalen Rueckweg (ExitProcess)")
def _():
    ersetze(PROG, "        Prozessende.Hart(0);", "")


@probe("Hart() benutzt Environment.Exit statt TerminateProcess")
def _():
    s = lies(PE)
    alt = "            NativeMethods.TerminateProcess(NativeMethods.GetCurrentProcess(), (uint)code);"
    assert alt in s, "Anker von TerminateProcess fehlt"
    (ROOT / PE).write_text(s.replace(alt, "            Environment.Exit(code);", 1),
                           encoding="utf-8")


@probe("TerminateProcess ist gar nicht erst deklariert")
def _():
    s = lies(NM)
    i = s.find("    internal static extern bool TerminateProcess")
    assert i > 0, "Anker der Deklaration fehlt"
    j = s.find(";", i)
    (ROOT / NM).write_text(s[:i] + s[j + 2:], encoding="utf-8")


@probe("der Rumpf liegt wieder in Main (jedes return laeuft am Ende vorbei)")
def _():
    ersetze(PROG, "    private static void Starten()", "    private static void Starten_UNBENUTZT()")


# ── c) Der Wachhund ───────────────────────────────────────────────────────
@probe("kein Wachhund ueber dem Aufraeumen")
def _():
    ersetze(PROG, "            Prozessende.WachhundStarten();\n", "")


@probe("der Wachhund startet ERST NACH dem Aufraeumen (zu spaet)")
def _():
    s = lies(PROG)
    alt = """            Prozessende.WachhundStarten();
            context.Dispose();"""
    assert alt in s, "Anker der Reihenfolge fehlt"
    neu = """            context.Dispose();
            Prozessende.WachhundStarten();"""
    (ROOT / PROG).write_text(s.replace(alt, neu, 1), encoding="utf-8")


@probe("das Aufraeumen laeuft nicht mehr im finally")
def _():
    s = lies(PROG)
    alt = """        try
        {
            Application.Run(context);
        }
        finally
        {"""
    assert alt in s, "Anker des finally fehlt"
    neu = """        {
            Application.Run(context);
        }
        {"""
    (ROOT / PROG).write_text(s.replace(alt, neu, 1), encoding="utf-8")


@probe("der Wachhund ist ein Pool-Timer (feuert im Ernstfall nicht)")
def _():
    ersetze(PE, "            var t = new Thread(() =>",
            "            var _timer = new System.Threading.Timer(_ =>")


@probe("der Wachhund ist ein Vordergrund-Thread")
def _():
    ersetze(PE, "                IsBackground = true,", "                IsBackground = false,")


@probe("der Wachhund laeuft mehrfach (nicht idempotent)")
def _():
    ersetze(PE, "        if (Interlocked.Exchange(ref _wachhundLaeuft, 1) != 0)",
            "        if (false)")


# ── d) Version und Chronik ────────────────────────────────────────────────
@probe("die Version ist nicht hochgezaehlt")
def _():
    ersetze("ai-mouse/src/AiMouse/AiMouse.csproj",
            "<Version>1.0.6</Version>", "<Version>1.0.5</Version>")


@probe("der Fehler ist in der Chronik nicht benannt")
def _():
    ersetze("ai-mouse/src/AiMouse/AiMouse.csproj",
            "nicht ohne System-Neustart", "irgendwas anderes")


# ── e) Der Waechter selbst ────────────────────────────────────────────────
@probe("der Waechter prueft wieder die Schreibweise statt der Eigenschaft")
def _():
    ersetze("tests/test_ai_mouse.py",
            'check("und der Aufrufer wartet nur mit Zeitgrenze",\n'
            '      re.search(r"\\b(Join|WaitOne)\\(\\s*grenze\\s*\\)", pruef_code) is not None)',
            'check("und der Aufrufer wartet nur mit Zeitgrenze",\n'
            '      "Join(grenze)" in pruef_code)')


def main():
    if MARKE.exists():
        print("⚠ Rueckstand eines abgebrochenen Laufs - nehme ihn zurueck.")
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

    basis, da = waechter()
    if not da or basis != 0:
        print("⚠ BASIS NICHT GRUEN (%s FAIL) - ohne gruene Basis ist keine "
              "Gegenprobe deutbar." % basis)
        sys.exit(2)
    print("Basis gruen (%d Proben)\n" % len(PROBEN))

    stumm = []
    for name, fn in PROBEN:
        zurueck(still=True)
        try:
            fn()
        except AssertionError as e:
            print("  ⚠ SABOTAGE VERFEHLT: %s - %s" % (name, e))
            stumm.append(name + " (verfehlt)")
            continue
        fails, bilanz = waechter()
        if not bilanz:
            print("  ABBRUCH ohne Bilanz: " + name)
            stumm.append(name + " (ohne Bilanz)")
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
