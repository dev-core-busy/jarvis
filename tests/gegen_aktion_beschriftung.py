#!/usr/bin/env python3
"""Gegenproben zu ``tests/test_aktion_beschriftung.py`` – beisst der Waechter?

Anlass (2026-09-30): Abschnitt 5 bildete die Seitenkennung aus dem DATEINAMEN
und war damit blind fuer genau den Fall, in dem Route und Dateiname
auseinandergehen. ``ai_mouse.html`` liegt unter ``/ai-mouse``,
``jira_addon.html`` unter ``/jira-addon``; beide Whitelist-Eintraege trugen
Unterstriche und trafen nie. Der Waechter meldete 22/22 gruen, waehrend zwei
Seiten in der Anwesenheitsliste unter dem neutralen "Aktion" liefen.

Deshalb pruefen die Proben hier BEIDE Richtungen und die Positivkontrollen
mit: eine Probe erwartet entweder FAIL oder einen Abbruch mit BENANNTEM Grund
(Exit 2). Ein Abbruch ohne den erwarteten Grund gilt als stumm – "konnte nicht
laufen" ist kein Beweis, dass eine Zusage gebrochen ist.

Die Nachbar-Abnahme ``tests/test_activity_ui.js`` laeuft hier NICHT mit: sie
misst die Verdrahtung von activity.js, nicht die Schreibweise der Kennungen
(getrennt geprueft, 32/32 gruen). Sie braucht jsdom, und ein fehlendes jsdom
haette den ganzen Harness unbewertbar gemacht.

REGELN DES HARNESS (jede aus einem bezahlten Vorfall):
  * **Gruener Basislauf ist Pflicht** – ohne gruene Basis ist keine Gegenprobe
    deutbar.
  * **Sicherung auf PLATTE im HOME (0700), vor jedem Lauf neu**; Rueckstand
    eines abgeschossenen Laufs beim naechsten Start selbst zuruecknehmen
    (Laufmarke), danach Byte-Gleichheit per md5 pruefen.
  * **NIE `git checkout`** – das verwirft die noch nicht committete Arbeit am
    Rest des Baums.
  * **Kein Bytecode** (`PYTHONDONTWRITEBYTECODE=1`): liegen Sabotage und
    Wiederherstellung in derselben Sekunde und sind gleich gross, laedt ein
    spaeterer Lauf die `.pyc` der SABOTAGE bei byte-gleicher Quelle.
  * **Gemessen wird die Bilanzzeile**, nicht das Zaehlen von FAIL-Zeilen.
  * **Trefferkontrolle je Ersetzung** (`assert`): eine Probe, die ihren Anker
    nicht trifft, sieht wie ein zahnloser Waechter aus und ist keiner.

Lauf:  python3 tests/gegen_aktion_beschriftung.py
"""

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = [sys.executable, str(ROOT / "tests" / "test_aktion_beschriftung.py")]
SICHER = Path.home() / ".gegen-aktion-beschriftung"      # HOME (0700), NICHT /tmp
MARKE = SICHER / ".laeuft"

# Jede Datei, die eine Probe anfasst – auch die TESTDATEI selbst (sie wird von
# der Meta-Probe sabotiert; fehlte sie hier, blieb die Sabotage liegen und der
# naechste Lauf meldete FAIL, die es im Code nicht gibt).
DATEIEN = [
    "backend/main.py",
    "frontend/js/activity.js",
    "tests/test_aktion_beschriftung.py",
]

UMG = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def sichern() -> None:
    """Sicherung bei JEDEM Lauf erneuern – die Basis ist per Definition der
    richtige Stand (sie wird unmittelbar davor als gruen geprueft)."""
    SICHER.mkdir(mode=0o700, parents=True, exist_ok=True)
    for rel in DATEIEN:
        shutil.copy2(ROOT / rel, SICHER / rel.replace("/", "__"))
    MARKE.write_text("1", encoding="utf-8")


def zurueck(pruefen: bool = True) -> None:
    for rel in DATEIEN:
        q = SICHER / rel.replace("/", "__")
        if not q.exists():
            continue
        shutil.copy2(q, ROOT / rel)
        if pruefen and md5(q) != md5(ROOT / rel):
            print("ABBRUCH: %s nicht byte-gleich wiederhergestellt" % rel)
            sys.exit(2)


def lauf() -> tuple[int, str, str]:
    """(FAIL-Zahl, Bilanzzeile, ganze Ausgabe). -1 heisst: keine Bilanz."""
    r = subprocess.run(WAECHTER, capture_output=True, text=True, cwd=str(ROOT),
                       env=UMG, timeout=300)
    aus = r.stdout + r.stderr
    for z in aus.splitlines():
        # Die Bilanz steht nicht immer am Zeilenanfang (ANSI-Escapes, Praefixe).
        if "ERGEBNIS:" in z:
            try:
                teil = z.split("ERGEBNIS:")[1].strip().split("/")
                ok, ges = int(teil[0]), int(teil[1].split()[0])
                return ges - ok, z.strip(), aus
            except (IndexError, ValueError):
                break
    grund = next((z for z in aus.splitlines()
                  if "NICHT PRUEFBAR" in z or "Error" in z), "")
    return -1, "KEINE BILANZ (%s)" % grund[:150], aus


def ersetze(rel: str, alt: str, neu: str, anzahl: int = 1) -> None:
    p = ROOT / rel
    s = p.read_text(encoding="utf-8")
    assert s.count(alt) == anzahl, \
        "Anker trifft %dx statt %dx in %s – Probe waere wertlos" % (
            s.count(alt), anzahl, rel)
    p.write_text(s.replace(alt, neu), encoding="utf-8")


# ── Die Proben ──────────────────────────────────────────────────────────────
# Der gemeldete Fehler selbst: Eintrag zurueck auf Unterstrich. Er muss in
# BEIDEN Richtungen auffallen – die Kennung aus dem Pfad findet keinen Eintrag,
# und der Eintrag mit Unterstrich ist toter Text.

def p_ai_mouse_unterstrich():
    ersetze("backend/main.py",
            '    "ai-mouse": "AI-Maus",\n', '    "ai_mouse": "AI-Maus",\n')


def p_jira_addon_unterstrich():
    ersetze("backend/main.py",
            '    "jira-addon": "Jira",\n', '    "jira_addon": "Jira",\n')


def p_toter_eintrag():
    """Ein Eintrag, den keine Route erzeugt – nur die Gegenrichtung sieht ihn."""
    ersetze("backend/main.py",
            '    "confluence-addon": "Confluence",\n}',
            '    "confluence-addon": "Confluence",\n    "gibtsnicht": "Nirgendwo",\n}')


def p_eintrag_fehlt():
    """Eine Seite ohne Beschriftung – die Richtung "Kennung sucht Eintrag"."""
    ersetze("backend/main.py", '    "confluence-addon": "Confluence",\n', "")


def p_bereich_ohne_label():
    """Abschnitt 4: ein veraendernder Endpunkt ohne Beschriftung."""
    ersetze("backend/main.py",
            '    ("/api/kundenverwaltung/", "Einstellungen · Kundenverwaltung"),\n', "")


def p_seite_js_verdreht():
    """activity.js bildet die Kennung anders als der Abschnitt annimmt.
    Positivkontrolle B muss das MELDEN statt weiterzurechnen – sonst prueft der
    Abschnitt gegen eine Umrechnung, die es nicht mehr gibt."""
    ersetze("frontend/js/activity.js",
            ".toLowerCase();\n", ".toLowerCase().replace(/-/g, '_');\n")


def p_keine_abweichung():
    """Alle drei Bindestrich-Routen auf Unterstrich – danach gleicht jede
    gepruefte Kennung ihrem Dateinamen, und der Abschnitt kann die beiden nicht
    mehr unterscheiden. Positivkontrolle C muss abbrechen."""
    for weg in ("ai-mouse", "jira-addon", "confluence-addon"):
        ersetze("backend/main.py", '@app.get("/%s")\n' % weg,
                '@app.get("/%s")\n' % weg.replace("-", "_"))


def p_seite_ohne_route():
    """Eine Seite mit activity.js, zu der keine Route gefunden wird.
    Positivkontrolle A muss abbrechen – still uebersehen waere schlimmer."""
    ersetze("backend/main.py", '@app.get("/ai-mouse")\n', "")


def p_waechter_nimmt_dateinamen():
    """META: der Waechter selbst zurueck auf den Dateinamen – die Vorfassung.
    Sie muss am KORREKTEN Code scheitern; genau das belegt, dass Abschnitt 5
    wirklich an der Route haengt und nicht am Namen der Datei."""
    ersetze("tests/test_aktion_beschriftung.py",
            "ANKOMMEND = {KENNUNG[r] for r, _ in PRUEFPAARE}\n",
            "ANKOMMEND = {h[:-5].lower() for _, h in PRUEFPAARE}\n")


# (Name, Funktion, Erwartung) – "fail" oder ein Textbaustein des Abbruchgrunds.
PROBEN = [
    ("ai-mouse zurueck auf Unterstrich", p_ai_mouse_unterstrich, "fail"),
    ("jira-addon zurueck auf Unterstrich", p_jira_addon_unterstrich, "fail"),
    ("toter Eintrag ergaenzt", p_toter_eintrag, "fail"),
    ("Eintrag einer Seite entfernt", p_eintrag_fehlt, "fail"),
    ("Endpunkt ohne Beschriftung", p_bereich_ohne_label, "fail"),
    ("Waechter nimmt wieder den Dateinamen", p_waechter_nimmt_dateinamen, "fail"),
    ("seite() rechnet anders als angenommen", p_seite_js_verdreht,
     "liefert 'ai_mouse'"),
    ("keine Route weicht mehr vom Dateinamen ab", p_keine_abweichung,
     "nicht mehr unterscheiden"),
    ("Seite ohne Route", p_seite_ohne_route, "keine Route gefunden"),
]


def main() -> int:
    if MARKE.exists():
        print("Rueckstand eines frueheren Laufs gefunden – nehme ihn zurueck.")
        zurueck(pruefen=False)
        MARKE.unlink()

    fehlt = [r for r in DATEIEN if not (ROOT / r).exists()]
    if fehlt:
        print("ABBRUCH: Datei(en) fehlen: %s" % fehlt)
        return 2

    basis_fail, basis_zeile, _ = lauf()
    print("Basislauf: %s" % basis_zeile)
    if basis_fail != 0:
        print("ABBRUCH: ohne gruenen Basislauf ist keine Gegenprobe deutbar.")
        return 2

    sichern()
    stumm = []
    try:
        for name, fn, erwartung in PROBEN:
            try:
                fn()
            except AssertionError as e:
                print("  ⚠ TRIFFT NICHT  %-42s %s" % (name, e))
                stumm.append(name + " (Anker)")
                zurueck()
                continue
            f, zeile, aus = lauf()
            zurueck()
            if erwartung == "fail":
                if f > 0:
                    print("  beisst  %-44s %d FAIL" % (name, f))
                elif f < 0:
                    # Ein Abbruch ist hier KEIN Beweis: die Sabotage kann den
                    # Lauf zerlegt haben, statt eine Zusage zu brechen.
                    print("  ABBRUCH %-44s %s" % (name, zeile))
                    stumm.append(name + " (Abbruch statt FAIL)")
                else:
                    print("  STUMM   %-44s 0 FAIL" % name)
                    stumm.append(name)
            elif f >= 0:
                # Erwartet war ein Abbruch – ein Lauf mit Bilanz heisst, die
                # Positivkontrolle hat nicht angesprochen.
                print("  STUMM   %-44s kein Abbruch (%s)" % (name, zeile))
                stumm.append(name + " (kein Abbruch)")
            elif erwartung in aus:
                print("  bricht  %-44s %s" % (name, erwartung))
            else:
                print("  FALSCHER GRUND %-35s %s" % (name, zeile))
                stumm.append(name + " (anderer Abbruchgrund)")
    finally:
        zurueck()
        if MARKE.exists():
            MARKE.unlink()

    print("\n%d von %d Proben beissen." % (len(PROBEN) - len(stumm), len(PROBEN)))
    if stumm:
        print("STUMM: %s" % ", ".join(stumm))
        print("Eine stumme Gegenprobe ist ein Testmangel – oder die Zusage "
              "existiert nicht. Beides gehoert geklaert, nicht weggelassen.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
