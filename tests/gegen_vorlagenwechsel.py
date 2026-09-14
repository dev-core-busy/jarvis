#!/usr/bin/env python3
"""Gegenproben zu "Vorlagenwechsel automatisch ausfuehren" (2026-09-14).

Jede Probe dreht GENAU EINE Zusage zurueck und misst, ob der Waechter beisst.
Eine Gegenprobe, die nicht beisst, ist ein Testmangel - kein Beweis.

⚠ DER HARNESS SICHERT JEDE DATEI, DIE EINE PROBE ANFASST, und prueft das als
REGEL (Exit 2). Am 2026-09-11 hat genau diese Liste eine Datei nicht enthalten,
die eine Probe sabotiert - die letzte Sabotage blieb stehen, und der naechste
Lauf meldete einen FAIL, den es im Code nicht gab.

⚠ DIE LAUFMARKE ist der zweite Teil davon: bricht der Lauf hart ab (kill -9),
bleibt sie liegen und der naechste Start nimmt den Rueckstand zurueck. Beim
geordneten Ende wird sie abgeraeumt - sonst stellte ein spaeterer Lauf einen
VERALTETEN Stand her und machte fertige Arbeit zunichte.
"""
import atexit
import hashlib
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys

ROOT = pathlib.Path("/home/bender/ai/projekte/jarvis")
ABL = pathlib.Path.home() / ".gegen-vorlagenwechsel"
MARKE = ABL / "LAUF"

DATEIEN = [
    "browser-addon/popup.html",
    "browser-addon/popup.js",
    "browser-addon/popup.css",
    "browser-addon/background.js",
    "browser-addon/manifest.json",
    "browser-addon/manifest.firefox.json",
    "frontend/js/i18n.js",
    "tests/test_browser_addon.js",
]


def sichern():
    ABL.mkdir(mode=0o700, exist_ok=True)
    for rel in DATEIEN:
        ziel = ABL / rel.replace("/", "__")
        shutil.copy2(ROOT / rel, ziel)
    MARKE.write_text("laeuft\n", encoding="utf-8")


def zurueck(still=False):
    for rel in DATEIEN:
        q = ABL / rel.replace("/", "__")
        if q.exists():
            shutil.copy2(q, ROOT / rel)
    if not still:
        # Byte-Gleichheit belegen, nicht annehmen.
        for rel in DATEIEN:
            a = hashlib.md5((ABL / rel.replace("/", "__")).read_bytes()).hexdigest()
            b = hashlib.md5((ROOT / rel).read_bytes()).hexdigest()
            if a != b:
                print(f"  ⚠ NICHT wiederhergestellt: {rel}")


def ende():
    zurueck(still=True)
    if MARKE.exists():
        MARKE.unlink()


def lies(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def schreib(rel, text):
    (ROOT / rel).write_text(text, encoding="utf-8")


def ersetze(rel, alt, neu, anzahl=1):
    """Ersetzt MIT Trefferkontrolle - eine Ersetzung ohne assert ist kein Messwert."""
    s = lies(rel)
    assert s.count(alt) >= anzahl, f"Anker nicht gefunden in {rel}: {alt[:60]!r}"
    schreib(rel, s.replace(alt, neu, anzahl))


def resub(rel, muster, neu, mindestens=1):
    s = lies(rel)
    s2, n = re.subn(muster, neu, s)
    assert n >= mindestens, f"Regex traf nicht in {rel}: {muster[:60]!r} ({n})"
    schreib(rel, s2)


def waechter():
    """Laeuft den Waechter und gibt (fails, bilanz_da) zurueck.

    ⚠ GEMESSEN WIRD DIE BILANZZEILE, NICHT NUR DER EXIT-CODE. Ein Lauf, der
    ohne Bilanz abbricht, ist von "nicht gelaufen" nicht zu unterscheiden - und
    genau so sahen im Projekt mehrfach Gegenproben aus, die scheinbar nicht
    bissen.
    """
    p = subprocess.run([sys.executable and "node", "tests/test_browser_addon.js"],
                       cwd=ROOT, capture_output=True, text=True, timeout=300)
    m = re.search(r"^(\d+) OK, (\d+) FAIL$", p.stdout, re.M)
    if not m:
        return (-1, False)
    return (int(m.group(2)), True)


# ── Die Proben ──────────────────────────────────────────────────────────────
PROBEN = []


def probe(name):
    def deko(fn):
        PROBEN.append((name, fn))
        return fn
    return deko


@probe("Markup: das checked ist weg (Vorgabe kippt ins Gegenteil)")
def _():
    ersetze("browser-addon/popup.html",
            'id="f-vorl-wechsel" checked>', 'id="f-vorl-wechsel">')


@probe("Hintergrund: === true statt !== false (Altbestand still AUS)")
def _():
    ersetze("browser-addon/background.js",
            "auto_wechsel: e.auto_wechsel !== false,",
            "auto_wechsel: e.auto_wechsel === true,")


@probe("Fenster: _autoWechsel startet auf false")
def _():
    ersetze("browser-addon/popup.js", "let _autoWechsel = true;",
            "let _autoWechsel = false;")


@probe("einstSchreiben kennt das Feld nicht (wortlos verworfen)")
def _():
    ersetze("browser-addon/background.js",
            "  if (teil.auto_wechsel !== undefined) neu.auto_wechsel = !!teil.auto_wechsel;",
            "  // entfernt")


@probe("kein Verzug: der Wechsel startet sofort (Steppen kostet drei Laeufe)")
def _():
    s = lies("browser-addon/popup.js")
    alt = "  _wechselTimer = setTimeout(() => {\n    _wechselTimer = null;"
    assert alt in s
    # Sofort ausfuehren statt planen.
    s = s.replace(alt, "  _wechselTimer = null;\n  (() => {\n    _wechselTimer = null;", 1)
    s = s.replace("  }, WECHSEL_VERZUG);", "  })();", 1)
    schreib("browser-addon/popup.js", s)


@probe("die _key-Pruefung im Timer ist weg (laeuft ohne Ticket)")
def _():
    ersetze("browser-addon/popup.js",
            "    if (!_autoWechsel || !_key || _laeuft) return;",
            "    if (!_autoWechsel) return;")


@probe("die _laeuft-Pruefung ist weg (zweiter Lauf in den ersten hinein)")
def _():
    ersetze("browser-addon/popup.js",
            "    if (!_autoWechsel || !_key || _laeuft) return;",
            "    if (!_autoWechsel || !_key) return;")


@probe("der Ticketbezug des Timers ist weg (laeuft auf dem neuen Tab)")
def _():
    ersetze("browser-addon/popup.js",
            "    if (_key !== _wechselKey) return;", "")


@probe("die Arbeitsbereich-Pruefung ist weg (laeuft abgemeldet)")
def _():
    ersetze("browser-addon/popup.js",
            "    if (el.arbeit && el.arbeit.hidden) return;\n    /* Die ART ist nur ein Wunsch",
            "    /* Die ART ist nur ein Wunsch")


@probe("der change-Handler stoesst nicht mehr an")
def _():
    ersetze("browser-addon/popup.js",
            "  wechselAnstossen();\n});", "});")


@probe("felderLeeren raeumt den wartenden Wechsel nicht ab")
def _():
    ersetze("browser-addon/popup.js",
            "  wechselAbbrechen();\n  anzeigeLeeren();", "  anzeigeLeeren();")


@probe("wechselZeigen kippt bei fehlendem Feld ins Gegenteil")
def _():
    ersetze("browser-addon/popup.js", "  _autoWechsel = (wert !== false);",
            "  _autoWechsel = (wert === true);")


@probe("das Kaestchen wandert ins Bearbeiten-Formular")
def _():
    s = lies("browser-addon/popup.html")
    block = re.search(r'      <div class="vorl-fuss">[\s\S]*?      </div>\n', s)
    assert block, "Fusszeile nicht gefunden"
    txt = block.group(0)
    s = s.replace(txt, "", 1)
    anker = '      <div class="knopfreihe">\n        <button type="button" id="btn-vorl-speichern"'
    assert s.count(anker) == 1
    schreib("browser-addon/popup.html", s.replace(anker, txt + anker, 1))


@probe("der Haken schaltet zusaetzlich selbst um (Doppel-Toggle im <label>)")
def _():
    ersetze("browser-addon/popup.js",
            "  const an = !!ereignis.target.checked;",
            "  ereignis.target.checked = !ereignis.target.checked;\n"
            "  const an = !!ereignis.target.checked;")


@probe("ein Fehlschlag nimmt den Haken NICHT zurueck")
def _():
    ersetze("browser-addon/popup.js",
            "    _autoWechsel = !an;\n    ereignis.target.checked = !an;", "")


@probe("STAND nicht hochgezaehlt (halb aktualisiertes Paket faellt nicht auf)")
def _():
    ersetze("browser-addon/background.js", "const STAND = 9;", "const STAND = 8;")


@probe("Version nicht hochgezaehlt (niemand erfaehrt vom neuen Haken)")
def _():
    for f in ("browser-addon/manifest.json", "browser-addon/manifest.firefox.json"):
        ersetze(f, '"version": "0.10.0"', '"version": "0.9.0"')


@probe("die Anleitung im Portal nennt den Haken nicht")
def _():
    resub("frontend/js/i18n.js", r"Vorlagenwechsel automatisch ausführen", "XXX", 2)


@probe("das CSS der Fusszeile fehlt (Trennstrich + min-width)")
def _():
    s = lies("browser-addon/popup.css")
    blk = re.search(r"\.vorl-fuss \{[\s\S]*?#vorl-wechsel-hinweis[^\n]*\n", s)
    assert blk, "CSS-Block nicht gefunden"
    schreib("browser-addon/popup.css", s.replace(blk.group(0), "", 1))


@probe("KOMPLETTER ALTSTAND (popup.*, background.js)")
def _():
    for rel in ("browser-addon/popup.html", "browser-addon/popup.js",
                "browser-addon/popup.css", "browser-addon/background.js"):
        alt = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout
        schreib(rel, alt)


# ── Lauf ────────────────────────────────────────────────────────────────────
def main():
    if MARKE.exists():
        print("⚠ Rueckstand eines abgebrochenen Laufs - nehme ihn zurueck.")
        zurueck(still=True)

    # REGEL: jede Datei, die eine Probe anfasst, muss in DATEIEN stehen.
    quelle = pathlib.Path(__file__).read_text(encoding="utf-8")
    genannt = set(re.findall(r'["\'](\w[\w/.-]*\.(?:js|html|css|json|py))["\']', quelle))
    fehlend = {d for d in genannt
               if (ROOT / d).exists() and d not in DATEIEN and "/" in d}
    if fehlend:
        print("⚠ NICHT GESICHERT: " + ", ".join(sorted(fehlend)))
        sys.exit(2)

    sichern()
    atexit.register(ende)
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(1))

    basis_fails, basis_ok = waechter()
    if not basis_ok or basis_fails != 0:
        print(f"⚠ BASIS IST NICHT GRUEN ({basis_fails} FAIL) - "
              "ohne gruene Basis ist keine Gegenprobe deutbar.")
        sys.exit(2)
    print(f"Basis gruen ({len(PROBEN)} Proben)\n")

    stumm = []
    for name, fn in PROBEN:
        zurueck(still=True)
        try:
            fn()
        except AssertionError as e:
            print(f"  ⚠ SABOTAGE VERFEHLT: {name} - {e}")
            stumm.append(name + " (Sabotage verfehlt)")
            continue
        fails, bilanz = waechter()
        if not bilanz:
            print(f"  ABBRUCH ohne Bilanz: {name}")
            stumm.append(name + " (ohne Bilanz)")
        elif fails == 0:
            print(f"  STUMM   {name}")
            stumm.append(name)
        else:
            print(f"  beisst  {fails:3d} FAIL  {name}")

    zurueck()
    print(f"\n{len(PROBEN) - len(stumm)} von {len(PROBEN)} Proben beissen.")
    if stumm:
        print("STUMM: " + "; ".join(stumm))
    sys.exit(1 if stumm else 0)


if __name__ == "__main__":
    main()
