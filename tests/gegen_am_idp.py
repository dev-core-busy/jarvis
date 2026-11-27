#!/usr/bin/env python3
"""Gegenproben zu Abschnitt 35 von test_ai_mouse.py: Firmenkonto (IdP) statt
Kerberos (AI-Maus 1.0.17, 2026-11-27).

Jede Probe nimmt genau EINE Zusage weg (nur Loopback, Zustand vor dem Code, nur
der Hash der Prueffolge im Browser, kein Browser beim Start, Kennwort als
Notweg, Hoehe aus dem Inhalt …) und muss den Waechter rot machen.

⚠ SICHERUNG AUF PLATTE + atexit + SIGTERM: ein per Timeout GEKILLTER Lauf laesst
   den Arbeitsbaum sonst sabotiert zurueck, und der naechste Testlauf meldet
   einen Fehler, den es nicht gibt (Register, mehrfach bezahlt).
⚠ Gemessen wird EXIT-CODE UND BILANZZEILE, nie das Zaehlen von FAIL-Zeilen:
   ein Lauf, der abbricht, hat keine Bilanz und ist von "bestanden" sonst nicht
   zu unterscheiden.
⚠ `Vorgaben.cs` gehoert in die Sicherung, obwohl keine Probe sie anfasst: der
   GEPRUEFTE Lauf schreibt sie selbst (er ruft `paket_bauen`).
"""

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)

import atexit
import pathlib
import re
import shutil
import signal
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SICHER = pathlib.Path.home() / ".gegen-am-idp"

DATEIEN = [
    "ai-mouse/src/AiMouse/Vision/IdpAnmeldung.cs",
    "ai-mouse/src/AiMouse/Vision/JarvisClient.cs",
    "ai-mouse/src/AiMouse/TrayApplicationContext.cs",
    "ai-mouse/src/AiMouse/Ui/LoginWindow.cs",
    "ai-mouse/src/AiMouse/Localization/Texte.cs",
    "ai-mouse/src/AiMouse/AiMouse.csproj",
    # Der GEPRUEFTE Lauf schreibt sie selbst (er ruft `paket_bauen`).
    "ai-mouse/src/AiMouse/Configuration/Vorgaben.cs",
    # Die Testdatei selbst – Pflicht in jeder Sicherung (Register).
    "tests/test_ai_mouse.py",
]


def sichern():
    SICHER.mkdir(mode=0o700, exist_ok=True)
    for rel in DATEIEN:
        ziel = SICHER / rel.replace("/", "__")
        shutil.copy2(ROOT / rel, ziel)   # IMMER erneuern, nie "nur wenn fehlt"


def zurueck():
    if not SICHER.is_dir():
        return
    for rel in DATEIEN:
        q = SICHER / rel.replace("/", "__")
        if q.is_file():
            shutil.copy2(q, ROOT / rel)


MARKE = SICHER / "LAEUFT"
# Ablage nach geordnetem Ende abraeumen (tests/lib/gegen_ablage.py) - VOR jedem
# atexit.register dieses Skripts, damit es als Letztes laeuft (atexit: LIFO).
import gegen_ablage  # noqa: E402
gegen_ablage.abraeumen_bei_ende(SICHER, marke=MARKE)


def abraeumen():
    """⚠ DIE SICHERUNG WIRD BEIM GEORDNETEN ENDE ENTFERNT.

    Ohne das stellt der NAECHSTE Lauf beim Start einen veralteten Stand her und
    macht Arbeit zunichte, die zwischendurch an diesen Dateien passiert ist –
    hier am 2026-09-11 bezahlt: der zweite Lauf hat die gerade gehaertete
    Fassung von `test_ai_mouse.py` ueberschrieben, und die Basis war danach rot
    aus einem Grund, der nicht im Code lag. Nach einem `kill -9` bleibt die
    Marke liegen, und dann soll das Zuruecknehmen genau greifen.
    """
    zurueck()
    if MARKE.is_file():
        MARKE.unlink()
    shutil.rmtree(SICHER, ignore_errors=True)


atexit.register(abraeumen)
signal.signal(signal.SIGTERM, lambda *_: sys.exit(2))

# Rueckstand eines ABGESCHOSSENEN Laufs zuruecknehmen – erkennbar an der Marke.
if MARKE.is_file():
    print("⚠ Rueckstand eines abgebrochenen Laufs gefunden – nehme ihn zurueck.")
    zurueck()
sichern()
MARKE.write_text("laeuft\n", encoding="utf-8")


def lauf():
    """(exit, hat_bilanz, fails)"""
    p = subprocess.run([sys.executable, str(ROOT / "tests" / "test_ai_mouse.py")],
                       capture_output=True, text=True, timeout=600)
    aus = p.stdout + p.stderr
    m = re.search(r"(\d+) OK, (\d+) FAIL", aus)
    return p.returncode, m is not None, (int(m.group(2)) if m else -1)


def probe(name, rel, alt, neu, nr=1):
    """`nr` = das wievielte Vorkommen getroffen wird (1-basiert).

    ⚠ Ein Anker, der mehrfach vorkommt, ist ohne diese Angabe eine Probe, die
      ihr Ziel verfehlen KANN – dieselbe Falle wie eine Sabotage, die den
      Kommentar statt des Aufrufs trifft.
    """
    d = ROOT / rel
    s = d.read_text(encoding="utf-8")
    n = s.count(alt)
    if n < nr:
        print(f"  ⚠ {name}: ANKER NICHT GEFUNDEN ({n}x, gesucht #{nr})")
        return False
    if nr == 1 and n != 1:
        print(f"  ⚠ {name}: ANKER NICHT EINDEUTIG ({n}x) – Probe verfehlt ihr Ziel")
        return False
    vor, _, rest = s.partition(alt) if nr == 1 else (
        alt.join(s.split(alt)[:nr]), alt, alt.join(s.split(alt)[nr:]))
    d.write_text(vor + neu + rest, encoding="utf-8")
    try:
        code, bilanz, fails = lauf()
    finally:
        zurueck()
    if not bilanz:
        print(f"  ⚠ {name}: KEINE BILANZ (Abbruch) – nicht deutbar")
        return False
    ok = code != 0 and fails > 0
    print(f"  {'✓' if ok else '✗'} {name}: {fails} FAIL")
    return ok


print("Basis …", end=" ", flush=True)
c, b, f = lauf()
if not (c == 0 and b and f == 0):
    print(f"NICHT GRUEN (exit={c}, bilanz={b}, fails={f}) – ohne gruene Basis "
          f"ist keine Gegenprobe deutbar.")
    sys.exit(2)
print("gruen\n")

PROBEN = [
    ('Kerberos-Rest zurueck (UseDefaultCredentials)',
     'ai-mouse/src/AiMouse/Vision/JarvisClient.cs',
     'internal sealed class JarvisClient : IDisposable\n{',
     'internal sealed class JarvisClient : IDisposable\n{\n    private static readonly HttpClientHandler _w = new() { UseDefaultCredentials = true };'),
    ('Lauscher auf allen Adressen',
     'ai-mouse/src/AiMouse/Vision/IdpAnmeldung.cs',
     'new TcpListener(IPAddress.Loopback, 0)',
     'new TcpListener(IPAddress.Any, 0)'),
    ('Ruecksprung auf localhost statt 127.0.0.1',
     'ai-mouse/src/AiMouse/Vision/IdpAnmeldung.cs',
     '"http://127.0.0.1:" + port + pfad',
     '"http://localhost:" + port + pfad'),
    ('Prueffolge aus nur 8 Bytes',
     'ai-mouse/src/AiMouse/Vision/IdpAnmeldung.cs',
     'RandomNumberGenerator.GetBytes(32)',
     'RandomNumberGenerator.GetBytes(8)'),
    ('challenge = Prueffolge im Klartext',
     'ai-mouse/src/AiMouse/Vision/IdpAnmeldung.cs',
     'B64Url(SHA256.HashData(Encoding.ASCII.GetBytes(verifier)))',
     'verifier'),
    ('falsche App-Kennung',
     'ai-mouse/src/AiMouse/Vision/IdpAnmeldung.cs',
     '"/api/login/oidc/start?app=ai-maus"',
     '"/api/login/oidc/start?app=ai-mouse"'),
    ('Prueffolge geht an den Browser',
     'ai-mouse/src/AiMouse/Vision/JarvisClient.cs',
     'basis, IdpAnmeldung.Challenge(verifier), zustand',
     'basis, verifier, zustand'),
    ('Einloesen ohne Prueffolge',
     'ai-mouse/src/AiMouse/Vision/JarvisClient.cs',
     '["verifier"] = verifier',
     '["verifier"] = string.Empty'),
    ('Code vor dem Zustand gewertet',
     'ai-mouse/src/AiMouse/Vision/IdpAnmeldung.cs',
     '        q.TryGetValue("zustand", out string? z);',
     '        if (q.TryGetValue("code", out string? c0) && c0.Length > 0) { return (c0, string.Empty); }\n        q.TryGetValue("zustand", out string? z);'),
    ('falscher Zustand liefert trotzdem den Code',
     'ai-mouse/src/AiMouse/Vision/IdpAnmeldung.cs',
     'await AntwortenAsync(strom, 400, Texte.IdpZustand, ct).ConfigureAwait(false);\n            return (false, string.Empty);',
     'await AntwortenAsync(strom, 400, Texte.IdpZustand, ct).ConfigureAwait(false);\n            return (true, q.GetValueOrDefault("code") ?? string.Empty);'),
    ('Browserseite ohne Maskierung',
     'ai-mouse/src/AiMouse/Vision/IdpAnmeldung.cs',
     'WebUtility.HtmlEncode(text)',
     'text'),
    ('keine Zeitgrenze',
     'ai-mouse/src/AiMouse/Vision/IdpAnmeldung.cs',
     '            zeit.CancelAfter(Zeitgrenze);\n',
     ''),
    ('Fehlerkennung ohne Text',
     'ai-mouse/src/AiMouse/Vision/IdpAnmeldung.cs',
     '        "lizenz" => Texte.IdpLizenz,\n',
     ''),
    ('Idp-Text DE = EN',
     'ai-mouse/src/AiMouse/Localization/Texte.cs',
     '"Keine Anmeldeberechtigung.", "Not authorised to sign in."',
     '"Keine Anmeldeberechtigung.", "Keine Anmeldeberechtigung."'),
    ('Browser oeffnet beim Programmstart',
     'ai-mouse/src/AiMouse/TrayApplicationContext.cs',
     '            _startAnmeldung = SicherstellenAngemeldetAsync(CancellationToken.None);',
     '            _ = FirmenkontoAnmeldenAsync(CancellationToken.None);\n            _startAnmeldung = SicherstellenAngemeldetAsync(CancellationToken.None);'),
    ('nach Fehlschlag kein Notweg',
     'ai-mouse/src/AiMouse/TrayApplicationContext.cs',
     '                kennwortOffen = true;',
     '                kennwortOffen = false;'),
    ('Firmenkonto ohne Wahl in der Maske',
     'ai-mouse/src/AiMouse/TrayApplicationContext.cs',
     '            if (!firmenkonto)\n',
     '            if (firmenkonto && false)\n'),
    ('Benutzer nach Firmenkonto nicht gemerkt',
     'ai-mouse/src/AiMouse/TrayApplicationContext.cs',
     '            _settings.Benutzer = name;\n',
     ''),
    ('Einstellungen fuehren nicht in die Maske',
     'ai-mouse/src/AiMouse/TrayApplicationContext.cs',
     '                _ = MaskeNachEinstellungenAsync();\n',
     ''),
    ('Rahmen ruft die Maske nicht',
     'ai-mouse/src/AiMouse/TrayApplicationContext.cs',
     '        return await MaskeAnmeldenAsync(ct).ConfigureAwait(true);',
     '        return false;'),
    ('Firmenkonto-Knopf schliesst mit OK',
     'ai-mouse/src/AiMouse/Ui/LoginWindow.cs',
     'Dock = DockStyle.Fill, DialogResult = DialogResult.Yes,',
     'Dock = DockStyle.Fill, DialogResult = DialogResult.OK,'),
    ('eingeklappt trotz Fehlschlag',
     'ai-mouse/src/AiMouse/Ui/LoginWindow.cs',
     'idp!.KennwortEingeklappt && !kennwortOffen;',
     'idp!.KennwortEingeklappt;'),
    ('Modus-Deutung umgedreht',
     'ai-mouse/src/AiMouse/Vision/JarvisClient.cs',
     'Aktiv && AdModus != "zusaetzlich"',
     'Aktiv && AdModus == "fallback"'),
    ('Link rechnet die Hoehe nicht neu',
     'ai-mouse/src/AiMouse/Ui/LoginWindow.cs',
     '                HoeheAnInhalt();\n',
     ''),
    ('Hoehe wieder fest',
     'ai-mouse/src/AiMouse/Ui/LoginWindow.cs',
     '_layout.GetPreferredSize(new Size(ClientSize.Width, 0)).Height',
     '200'),
    ('automatische Platzierung zurueck',
     'ai-mouse/src/AiMouse/Ui/LoginWindow.cs',
     '        layout.Controls.Add(c, 0, zeile);',
     '        layout.Controls.Add(c);'),
    ("Serverauskunft wirft statt 'aus'",
     'ai-mouse/src/AiMouse/Vision/JarvisClient.cs',
     '        catch (Exception)\n        {\n            return IdpStatus.Aus;\n        }',
     '        catch (Exception)\n        {\n            throw;\n        }'),
]

_fehlt = sorted({p[1] for p in PROBEN} - set(DATEIEN))
if _fehlt:
    print("⚠ ABBRUCH: diese Dateien werden saboteirt, aber nicht gesichert –\n"
          "  ein Lauf wuerde sie veraendert zuruecklassen:\n   " + "\n   ".join(_fehlt))
    sys.exit(2)

gut = 0
for p in PROBEN:
    if probe(*p):
        gut += 1

print(f"\n{gut}/{len(PROBEN)} Gegenproben beissen")
sys.exit(0 if gut == len(PROBEN) else 1)
