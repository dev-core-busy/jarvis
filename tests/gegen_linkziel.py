#!/usr/bin/env python3
"""Gegenproben zu den klickbaren Links im Ergebnisfenster der AI-Maus.

Zwei Waechter, zwei Ebenen:
  * `tests/test_ai_mouse.py`  – die Verdrahtung (Quelltext-Regeln),
  * `tests/live_linkziel_dev.py` – die Regel selbst, AUSGEFUEHRT gegen echte
    Angriffsfaelle (nur auf DEV, dort steht das .NET SDK).

Gemessen wird am EXIT-CODE und an der Bilanzzeile, nie am Zaehlen von FAILs.

⚠ Sicherung auf Platte + atexit + SIGTERM: wird das Skript per Timeout
   abgeschossen, laeuft ein `finally` NICHT – im Projekt ist so schon ein
   sabotierter Arbeitsbaum liegengeblieben.
"""
import atexit
import re
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ABLAGE = Path.home() / ".gegen-linkziel"
DEV = "root@191.100.144.1"

DATEIEN = ["ai-mouse/src/AiMouse/Ui/ResultWindow.cs",
           "ai-mouse/src/AiMouse/Ui/LinkZiel.cs",
           "ai-mouse/src/AiMouse/Localization/Texte.cs",
           "ai-mouse/src/AiMouse/Input/MouseGestureHook.cs",
           "ai-mouse/src/AiMouse/Input/GestenTaste.cs",
           "ai-mouse/src/AiMouse/Interop/NativeMethods.cs",
           "ai-mouse/src/AiMouse/Configuration/AppSettings.cs",
           "ai-mouse/src/AiMouse/Configuration/ConfigStore.cs",
           "ai-mouse/src/AiMouse/Ui/SettingsWindow.cs",
           "ai-mouse/src/AiMouse/TrayApplicationContext.cs"]


def sichern():
    ABLAGE.mkdir(mode=0o700, exist_ok=True)
    for rel in DATEIEN:
        (ABLAGE / rel.replace("/", "__")).write_bytes((ROOT / rel).read_bytes())


def zurueck():
    for rel in DATEIEN:
        q = ABLAGE / rel.replace("/", "__")
        if q.exists():
            (ROOT / rel).write_bytes(q.read_bytes())


def rueckstand():
    if ABLAGE.exists() and any(ABLAGE.iterdir()):
        abw = [r for r in DATEIEN
               if (ABLAGE / r.replace("/", "__")).exists()
               and (ABLAGE / r.replace("/", "__")).read_bytes() != (ROOT / r).read_bytes()]
        if abw:
            print(f"⚠ Rueckstand eines frueheren Laufs – nehme zurueck: {abw}")
            zurueck()


def ersetze(rel, alt, neu, anzahl=1):
    p = ROOT / rel
    s = p.read_text(encoding="utf-8")
    assert s.count(alt) >= anzahl, f"Sabotage verfehlt ihr Ziel in {rel}: {alt[:70]!r}"
    p.write_text(s.replace(alt, neu, anzahl), encoding="utf-8")


def lauf_lokal():
    p = subprocess.run([sys.executable, "tests/test_ai_mouse.py"], cwd=ROOT,
                       capture_output=True, text=True, timeout=420)
    aus = p.stdout + p.stderr
    m = re.search(r"(\d+)\s*OK,\s*(\d+)\s*FAIL", aus)
    return p.returncode, bool(m), int(m.group(2)) if m else -1


PROBE = "tests/live_linkziel_dev.py"


def lauf_dev():
    """Die AUSGEFUEHRTE Probe – die Dateien muessen dafuer nach DEV.

    ⚠ DAS PROBE-SKRIPT MUSS MIT. Ein erster Anlauf uebertrug nur die
    C#-Dateien und mass gegen eine VERALTETE Fassung von
    `live_linkziel_dev.py` auf dem Server – eine gerade erst ergaenzte
    Pruefung lief dort gar nicht, und die Gegenprobe sah zahnlos aus.
    """
    t = subprocess.run("tar czf - " + " ".join(DATEIEN)
                       + " tests/live_linkziel_dev.py tests/live_gestentaste_dev.py"
                       + f" | ssh -o ConnectTimeout=10 {DEV} 'cd /opt/jarvis && tar xzf - "
                         "--no-same-owner && chown -R jarvis:jarvis ai-mouse tests'",
                       shell=True, cwd=ROOT, capture_output=True, text=True, timeout=180)
    if t.returncode != 0:
        return 2, False, -1
    p = subprocess.run(["ssh", DEV, "cd /opt/jarvis && python3 " + PROBE],
                       capture_output=True, text=True, timeout=600)
    aus = p.stdout + p.stderr
    m = re.search(r"Ergebnis:\s*(\d+)\s*OK,\s*(\d+)\s*FAIL", aus)
    return p.returncode, bool(m), int(m.group(2)) if m else -1


PROBEN = [
    # ── Verdrahtung (lokal messbar) ─────────────────────────────────────────
    ("TextBox statt RichTextBox (Altstand: gar keine Links)", "lokal", lambda: (
        ersetze("ai-mouse/src/AiMouse/Ui/ResultWindow.cs",
                "private readonly RichTextBox _output;",
                "private readonly TextBox _output;"),
        ersetze("ai-mouse/src/AiMouse/Ui/ResultWindow.cs",
                "_output = new RichTextBox\n        {\n            Dock = DockStyle.Fill,\n"
                "            ReadOnly = true,\n            DetectUrls = true,\n"
                "            ScrollBars = RichTextBoxScrollBars.Vertical,",
                "_output = new TextBox\n        {\n            Dock = DockStyle.Fill,\n"
                "            Multiline = true,\n            ReadOnly = true,\n"
                "            ScrollBars = ScrollBars.Vertical,"))),

    ("Linkerkennung aus", "lokal", lambda: ersetze(
        "ai-mouse/src/AiMouse/Ui/ResultWindow.cs",
        "DetectUrls = true,", "DetectUrls = false,")),

    ("Klick nicht verdrahtet (Link blau und tot)", "lokal", lambda: ersetze(
        "ai-mouse/src/AiMouse/Ui/ResultWindow.cs",
        "_output.LinkClicked += (_, e) => LinkOeffnen(e.LinkText);", "")),

    ("Rohtext statt gepruefter Adresse gestartet", "lokal", lambda: ersetze(
        "ai-mouse/src/AiMouse/Ui/ResultWindow.cs",
        "new ProcessStartInfo(adresse.AbsoluteUri)", "new ProcessStartInfo(ziel!)")),

    ("Ablehnung bleibt still (kein Hinweis im Kopf)", "lokal", lambda: ersetze(
        "ai-mouse/src/AiMouse/Ui/ResultWindow.cs",
        "_header.Text = Texte.LinkNichtGeoeffnet;", "")),

    ("zweite Schema-Regel im Fenster (Regel an zwei Orten)", "lokal", lambda: ersetze(
        "ai-mouse/src/AiMouse/Ui/ResultWindow.cs",
        "        if (!LinkZiel.IstWeb(ziel, out Uri? adresse) || adresse is null)",
        "        var _u = new Uri(ziel!);\n"
        "        if (_u.Scheme != Uri.UriSchemeHttp || !LinkZiel.IstWeb(ziel, out Uri? adresse)"
        " || adresse is null)")),

    ("Absage ohne Ausweg (nur Verbot)", "lokal", lambda: ersetze(
        "ai-mouse/src/AiMouse/Localization/Texte.cs",
        '"Nur Web-Adressen (http/https) werden geöffnet – diese nicht. '
        'Text markieren und kopieren.",\n        "Only web addresses (http/https) are opened '
        '– this one is not. Select the text and copy it.");',
        '"Nicht erlaubt.", "Not allowed.");')),

    # ── Die Regel selbst (nur AUSGEFUEHRT messbar) ──────────────────────────
    ("Erlaubnisliste raus: jedes Schema wird geoeffnet", "dev", lambda: ersetze(
        "ai-mouse/src/AiMouse/Ui/LinkZiel.cs",
        "        if (u.Scheme != Uri.UriSchemeHttp && u.Scheme != Uri.UriSchemeHttps)\n"
        "        {\n            return false;\n        }\n",
        "")),

    # ⚠ GESTRICHEN: "UNC/Datei-Guertel raus". Die Zeile `if (u.IsFile ||
    #    u.IsUnc)` gab es kurz und sie war NACHWEISLICH TOT – ihr Entfernen
    #    aenderte keinen einzigen Fall, weil UNC und C:\… in .NET das Schema
    #    `file` tragen und schon an der Erlaubnisliste scheitern. Sie ist
    #    deshalb aus dem Code heraus, statt eine Gegenprobe zu behalten, die
    #    per Konstruktion nicht beissen kann. Die EIGENSCHAFT (UNC wird
    #    abgewiesen) misst `live_linkziel_dev.py` weiterhin.

    ("schemenlos wird http statt https", "dev", lambda: ersetze(
        "ai-mouse/src/AiMouse/Ui/LinkZiel.cs",
        'roh = "https://" + roh;', 'roh = "http://" + roh;')),

    ("Leerraum wird nicht abgeschnitten", "dev", lambda: ersetze(
        "ai-mouse/src/AiMouse/Ui/LinkZiel.cs",
        "string roh = text.Trim();", "string roh = text;")),

    # ── Rechtsziehen per Taste (2026-09-10) ─────────────────────────────────
    ("Gestentaste: Pruefung ganz raus", "gtaste", lambda: ersetze(
        "ai-mouse/src/AiMouse/Input/MouseGestureHook.cs",
        "                if (TasteGehalten(Durchreichen))\n                {\n"
        "                    _pressWithheld = false;\n                    break;\n                }\n",
        "")),

    ("⚠ Gestentaste: _pressWithheld bleibt stehen (Klick geht verloren)",
     "gtaste", lambda: ersetze(
        "ai-mouse/src/AiMouse/Input/MouseGestureHook.cs",
        "                if (TasteGehalten(Durchreichen))\n                {\n"
        "                    _pressWithheld = false;\n                    break;\n                }",
        "                if (TasteGehalten(Durchreichen))\n                {\n"
        "                    break;\n                }")),

    # Reihenfolge: die Pruefung muss VOR dem Zurueckhalten stehen. Verschoben
    # hinter `_pressWithheld = true` kompiliert es noch – und genau das soll
    # der lokale Waechter melden.
    ("Gestentaste: Pruefung erst NACH dem Zurueckhalten", "lokal", lambda: (
        ersetze("ai-mouse/src/AiMouse/Input/MouseGestureHook.cs",
                "                if (TasteGehalten(Durchreichen))\n                {\n"
                "                    _pressWithheld = false;\n                    break;\n                }\n\n",
                ""),
        ersetze("ai-mouse/src/AiMouse/Input/MouseGestureHook.cs",
                "                _pressWithheld = true;\n                _start = point;",
                "                _pressWithheld = true;\n                _start = point;\n\n"
                "                if (TasteGehalten(Durchreichen))\n                {\n"
                "                    _pressWithheld = false;\n                    break;\n                }"))),

    ("Gestentaste: auch das NIEDRIGE Bit zaehlt (losgelassene Taste wirkt nach)",
     "gtaste", lambda: ersetze(
        "ai-mouse/src/AiMouse/Input/MouseGestureHook.cs",
        "(NativeMethods.GetAsyncKeyState(vk) & 0x8000) != 0",
        "NativeMethods.GetAsyncKeyState(vk) != 0")),

    ("Gestentaste: falsche Zuordnung (Alt liefert Strg)", "gtaste", lambda: ersetze(
        "ai-mouse/src/AiMouse/Input/MouseGestureHook.cs",
        "GestenTaste.Alt => NativeMethods.VK_MENU,",
        "GestenTaste.Alt => NativeMethods.VK_CONTROL,")),

    ("alles abgelehnt (waere 'sicher' und wertlos)", "dev", lambda: ersetze(
        "ai-mouse/src/AiMouse/Ui/LinkZiel.cs",
        "        adresse = u;\n        return true;", "        return false;")),
]


def main():
    rueckstand()
    sichern()
    atexit.register(zurueck)
    signal.signal(signal.SIGTERM, lambda *a: (zurueck(), sys.exit(143)))

    print("=" * 74)
    print("BASISLAUF")
    print("=" * 74)
    rc, bil, f = lauf_lokal()
    print(f"  lokal  exit={rc} bilanz={bil} FAIL={f}")
    rc2, bil2, f2 = lauf_dev()
    print(f"  DEV    exit={rc2} bilanz={bil2} FAIL={f2}")
    if rc or not bil or f or rc2 or not bil2 or f2:
        print("ABBRUCH: Basis ist nicht gruen – keine Gegenprobe deutbar.")
        zurueck()
        lauf_dev()          # DEV wieder auf den sauberen Stand
        return 2

    print("\n" + "=" * 74)
    print("GEGENPROBEN")
    print("=" * 74)
    zahnlos = []
    for name, wo, fn in PROBEN:
        zurueck()
        try:
            fn()
        except AssertionError as e:
            print(f"  ⚠ {name}: {e}")
            zahnlos.append(name + " (Sabotage verfehlt)")
            continue
        if wo == "lokal":
            rc, bil, f = lauf_lokal()
        else:
            global PROBE
            PROBE = ("tests/live_gestentaste_dev.py" if wo == "gtaste"
                     else "tests/live_linkziel_dev.py")
            rc, bil, f = lauf_dev()
        gebissen = rc != 0
        print(("  ✔ " if gebissen else "  ✗ ZAHNLOS ") + f"[{wo}] {name}"
              + f"  [exit={rc} " + (f"FAIL={f}]" if bil else "OHNE BILANZ]"))
        if not gebissen:
            zahnlos.append(name)

    zurueck()
    lauf_dev()              # DEV zuletzt wieder auf den sauberen Stand bringen
    schlecht = [r for r in DATEIEN
                if (ROOT / r).read_bytes() != (ABLAGE / r.replace("/", "__")).read_bytes()]
    print("\n" + "=" * 74)
    print(f"Wiederhergestellt: {'OK' if not schlecht else 'ABWEICHUNG ' + str(schlecht)}")
    print(f"Gebissen: {len(PROBEN) - len(zahnlos)} von {len(PROBEN)}"
          + (f" · ZAHNLOS: {zahnlos}" if zahnlos else ""))
    print("=" * 74)
    for f in ABLAGE.iterdir():
        f.unlink()
    return 1 if (zahnlos or schlecht) else 0


if __name__ == "__main__":
    sys.exit(main())
