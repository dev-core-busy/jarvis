#!/usr/bin/env python3
"""Gegenproben: Version 1.0.0, Paket ohne Kurzanleitung, stilles Update.

Jede Probe dreht GENAU EINE Zusage zurueck und misst, ob der Waechter beisst.
Eine Probe, die nicht beisst, ist ein Testmangel – kein Beweis.

⚠ SICHERUNG AUF PLATTE: wird dieser Lauf abgeschossen, bliebe der Arbeitsbaum
sabotiert zurueck, und der naechste Testlauf meldete Fehler, die der Code nicht
hat (am 2026-09-04 und 2026-09-10 bezahlt). Ein Rueckstand wird beim naechsten
Start selbst zurueckgenommen, nach dem Wiederherstellen auf BYTE-Gleichheit
geprueft.

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
WAECHTER = ROOT / "tests" / "test_ai_mouse.py"
ABLAGE = Path.home() / ".gegen-aimouse-update"

ZIELE = {
    "backend": ROOT / "backend" / "ai_mouse.py",
    "main": ROOT / "backend" / "main.py",
    "csproj": ROOT / "ai-mouse" / "src" / "AiMouse" / "AiMouse.csproj",
    "upd": ROOT / "ai-mouse" / "src" / "AiMouse" / "Update" / "Aktualisierung.cs",
    "prog": ROOT / "ai-mouse" / "src" / "AiMouse" / "Program.cs",
    "tray": ROOT / "ai-mouse" / "src" / "AiMouse" / "TrayApplicationContext.cs",
    "client": ROOT / "ai-mouse" / "src" / "AiMouse" / "Vision" / "JarvisClient.cs",
}


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


ABLAGE.mkdir(mode=0o700, exist_ok=True)
# ⚠ `Vorgaben.cs` MIT SICHERN, obwohl keine Probe sie anfasst: der GEPRUEFTE
# Lauf schreibt sie (er ruft `paket_bauen`) und stellt sie selbst wieder her –
# wird er mitten darin abgeschossen, bleibt sie verbogen liegen. Am 2026-09-10
# genau so passiert.
ZIELE["vorgaben"] = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Configuration"
                     / "Vorgaben.cs")

SOLL = {}
for name, ziel in ZIELE.items():
    sich = ABLAGE / (name + ".bak")
    if sich.exists():
        if md5(sich) != md5(ziel):
            print("⚠ Rueckstand von %s gefunden – stelle her." % name)
            shutil.copy2(sich, ziel)
        sich.unlink()
    shutil.copy2(ziel, sich)
    SOLL[name] = md5(ziel)


def zurueck(*_a):
    for name, ziel in ZIELE.items():
        sich = ABLAGE / (name + ".bak")
        if sich.exists():
            shutil.copy2(sich, ziel)
            if md5(ziel) != SOLL[name]:
                print("⚠⚠ %s NICHT BYTE-GLEICH wiederhergestellt!" % name)
            sich.unlink()


atexit.register(zurueck)
signal.signal(signal.SIGTERM, lambda *a: (zurueck(), sys.exit(2)))

ORIG = {n: z.read_text(encoding="utf-8") for n, z in ZIELE.items()}


def lauf():
    p = subprocess.run([sys.executable, str(WAECHTER)], capture_output=True,
                       text=True, timeout=540)
    bilanz = ""
    for z in reversed((p.stdout or "").splitlines()):
        if " OK, " in z and "FAIL" in z:
            bilanz = z.strip()
            break
    return p.returncode, (p.stdout or "").count("  FAIL "), bilanz


def probe(name, datei, alt, neu, anzahl=1):
    s = ORIG[datei]
    if alt not in s:
        print("  ⚠ %-48s ANKER NICHT GETROFFEN" % name)
        return
    ZIELE[datei].write_text(s.replace(alt, neu, anzahl), encoding="utf-8")
    rc, fails, bilanz = lauf()
    ZIELE[datei].write_text(s, encoding="utf-8")
    if not bilanz:
        print("  ⚠ %-48s ABBRUCH OHNE BILANZ (rc=%d)" % (name, rc))
    elif rc == 0:
        print("  ✗ %-48s BEISST NICHT (%s)" % (name, bilanz))
    else:
        print("  ✓ %-48s %d FAIL  (%s)" % (name, fails, bilanz))


print("=" * 80)
rc, fails, bilanz = lauf()
print("Basis: rc=%d  %s" % (rc, bilanz))
if rc != 0:
    print("ABBRUCH: Basis ist nicht gruen.")
    sys.exit(2)
print("=" * 80)

# ── 1) Die Kurzanleitung kehrt ins Paket zurueck ────────────────────────────
probe("Kurzanleitung wieder im ZIP", "backend",
      "        z.write(p, EXE_NAME)\n",
      '        z.write(p, EXE_NAME)\n        z.writestr("LIESMICH.txt", "x")\n')

# ── 2) Version ─────────────────────────────────────────────────────────────
probe("<Version> aus der csproj entfernt", "csproj",
      "    <Version>1.0.0</Version>\n", "")

probe("klient_version liefert eine Konstante statt der csproj", "backend",
      '    m = _re.search(r"<Version>\\s*([0-9]+(?:\\.[0-9]+){0,3})\\s*</Version>", text)\n'
      "    return m.group(1) if m else \"\"",
      '    return "9.9.9"')

probe("health nennt die Version nicht", "main",
      '        "klient_version": ai_mouse.klient_version(),\n', "")

probe("die Version steht zusaetzlich als Backend-Konstante", "backend",
      "def csproj_pfad():", 'KLIENT_VERSION = "1.0.0"\n\n\ndef csproj_pfad():')

# ── 3) Der Versionsvergleich ───────────────────────────────────────────────
probe("Vergleich als ZEICHENKETTE statt als Zahl", "upd",
      "        if (!Version.TryParse(ziel.Trim(), out Version? z) || z is null)",
      "        if (false)")

probe("Normierung auf vier Teile entfernt", "upd",
      "    private static Version Normiert(Version v) => new(\n"
      "        Math.Max(v.Major, 0), Math.Max(v.Minor, 0),\n"
      "        Math.Max(v.Build, 0), Math.Max(v.Revision, 0));",
      "    private static Version Normiert(Version v) => v;")

probe("unbekannte Serverversion loest ein Update aus", "upd",
      "        if (string.IsNullOrWhiteSpace(ziel))\n        {\n            return false;\n        }",
      "        if (string.IsNullOrWhiteSpace(ziel))\n        {\n            return true;\n        }")

# ── 4) Der Einwechsel ──────────────────────────────────────────────────────
probe("Einwechsel LOESCHT die alte Fassung statt sie umzubenennen", "upd",
      "            File.Move(exe, alt, overwrite: true);",
      "            File.Delete(exe);")

probe("Fehlschlag wird NICHT zurueckgenommen", "upd",
      "                File.Move(alt, exe, overwrite: true);   // ZURUECKNEHMEN",
      "                _ = alt;")

probe("eine winzige Datei wird eingewechselt", "upd",
      "            if (new FileInfo(neu).Length < 1_000_000)",
      "            if (false)")

probe("Einwechsel nach EnableVisualStyles", "prog",
      "        if (isOnlyInstance && Aktualisierung.NeueFassungLiegtBereit())",
      "        if (false && Aktualisierung.NeueFassungLiegtBereit())")

probe("Einzelinstanz-Sperre wird nicht freigegeben", "prog",
      "                instanceLock.ReleaseMutex();", "                _ = 1;")

# ── 5) Das Holen bleibt still ──────────────────────────────────────────────
probe("das Holen startet die Anwendung neu", "upd",
      '            File.Move(teil, neu, overwrite: true);\n            return "bereitgelegt";',
      '            File.Move(teil, neu, overwrite: true);\n'
      "            Process.Start(EigenerPfad);\n"
      '            return "bereitgelegt";')

probe("schon geholte Fassung wird erneut geladen", "upd",
      "            if (File.Exists(neu))\n            {\n"
      '                return "liegt bereit";\n            }',
      "            if (false)\n            {\n"
      '                return "liegt bereit";\n            }')

probe("Schreibrecht erst NACH dem Download geprueft", "upd",
      '            string probe = exe + ".schreibprobe";',
      '            byte[] _vorab = await paketHolen(ct).ConfigureAwait(false);\n'
      '            string probe = exe + ".schreibprobe";')

probe("keine Nebendatei – direkt nach .neu schreiben", "upd",
      '            string teil = exe + ".teil";', "            string teil = neu;")

probe("die Pruefung wird abgewartet (blockiert das Menue)", "tray",
      "        _ = AktualisierungPruefenAsync();",
      "        await AktualisierungPruefenAsync().ConfigureAwait(true);")

probe("die Pruefung meldet dem Benutzer etwas", "tray",
      "        catch (Exception)\n        {\n            // Still. Siehe Docstring.\n        }",
      "        catch (Exception e)\n        {\n            ShowTrayError(e.Message);\n        }")

# ── 6) TLS ────────────────────────────────────────────────────────────────
probe("Zertifikatspruefung im Client abgeschaltet", "client",
      "        _http = new HttpClient\n        {",
      "        var h = new HttpClientHandler();\n"
      "        h.ServerCertificateCustomValidationCallback = (a, b, c, d) => true;\n"
      "        _http = new HttpClient\n        {")

probe("PaketAsync ohne eigenes Zeitlimit", "client",
      "        using var eigenesLimit = new CancellationTokenSource(TimeSpan.FromMinutes(10));",
      "        using var eigenesLimit = new CancellationTokenSource();")

probe("eigener Pfad ueber Assembly.Location", "upd",
      "                return Environment.ProcessPath ?? string.Empty;",
      "                return Assembly.Location;")

print("=" * 80)
print("✓ = beisst · ✗ = Testmangel · ⚠ = Probe/Waechter untauglich")
