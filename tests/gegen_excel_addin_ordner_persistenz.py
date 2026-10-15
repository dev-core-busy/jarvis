#!/usr/bin/env python3
"""Gegenprobe: beisst test_excel_addin_ui.js noch, wenn die ORDNER-PERSISTENZ
im Produktivcode bricht?

Hintergrund (2026-10-11): der Waechter war in der CI seit dem 2026-10-06 bei
fast jedem Push rot, lokal aber gruen. Ursache war kein Produktbefund, sondern
ein FESTES Prueffenster (`warte(60)`) um eine asynchrone IndexedDB-Kette –
unter Last braucht sie nachgemessen 73-216 ms statt 7-22 ms. Das Fenster wurde
durch `warteBis(bedingung)` ersetzt.

Ein Warten auf eine Bedingung kann eine Zusage VERDECKEN: gilt sie nie, laeuft
nur der Deckel ab. Genau das wird hier gemessen – die Zusage wird im
Produktivcode (`frontend/js/excel_admin.js`) einzeln gebrochen, und jede
Sabotage MUSS als FAIL erscheinen. Beisst sie nicht, ist der Umbau ein
Testmangel und kein Fix.

Exit 0 = alle Sabotagen haben gebissen · Exit 1 = eine blieb stumm
Exit 2 = konnte nicht laufen (kein gruener Basislauf, Rueckstand, Werkzeug fehlt)
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZIEL = os.path.join(WURZEL, 'frontend/js/excel_admin.js')
TEST = os.path.join(WURZEL, 'tests/test_excel_addin_ui.js')
# Laufmarke: ein abgeschossener Lauf (kill fuehrt KEIN atexit aus) laesst die
# Sabotage im Arbeitsbaum liegen. Die Marke erkennt das beim naechsten Start.
MARKE = os.path.join(tempfile.gettempdir(), 'gegen_excel_ordner.laeuft')

# Jede Sabotage: (Name, alter Text, neuer Text, Zusagen die fallen MUESSEN)
SABOTAGEN = [
    (
        'das gemerkte Handle wird nicht mehr GELESEN',
        "            handleLesen().then(function (h) {\n"
        "                _ordner = h || null;",
        "            handleLesen().then(function (h) {\n"
        "                _ordner = null;",
        ['nach dem Neuladen nennt der Knopf den gemerkten Ordner',
         'beim zweiten Mal wird NICHT mehr nach dem Ordner gefragt'],
    ),
    (
        'das Handle wird nicht mehr GESCHRIEBEN',
        "                    handleSchreiben(h).catch(function () { });",
        "                    Promise.resolve(h).catch(function () { });",
        ['das Handle wird in IndexedDB gemerkt',
         'nach dem Neuladen nennt der Knopf den gemerkten Ordner'],
    ),
    (
        'der gemerkte Ordner wird nicht WIEDERVERWENDET',
        "        if (_ordner) return Promise.resolve(_ordner);",
        "        if (false) return Promise.resolve(_ordner);",
        ['beim zweiten Mal wird NICHT mehr nach dem Ordner gefragt'],
    ),
]


def md5(pfad):
    with open(pfad, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()


def lauf():
    """Den Waechter fahren und (bestanden, fehlgeschlagen, FAIL-Zeilen) liefern."""
    p = subprocess.run(['node', TEST], cwd=WURZEL, capture_output=True,
                       text=True, timeout=300)
    bilanz = re.search(r'Bestanden:\s*(\d+)\s*/\s*Fehlgeschlagen:\s*(\d+)', p.stdout)
    if not bilanz:
        # Kein Bilanzblock = abgestuerzt. Das ist NICHT "beisst" (CLAUDE.md:
        # eine Sabotage, die den Waechter abstuerzen laesst, hat nicht gebissen).
        return None, None, p.stdout + p.stderr
    fails = [z.strip() for z in p.stdout.splitlines() if z.strip().startswith('✗')]
    return int(bilanz.group(1)), int(bilanz.group(2)), fails


def main():
    if not os.path.exists(ZIEL) or not os.path.exists(TEST):
        print(f'ABBRUCH: {ZIEL} oder {TEST} fehlt', file=sys.stderr)
        return 2
    if shutil.which('node') is None:
        print('ABBRUCH: node nicht gefunden', file=sys.stderr)
        return 2

    sicherung = os.path.join(tempfile.gettempdir(), 'excel_admin.js.gegenprobe')
    if os.path.exists(MARKE):
        print('ABBRUCH: Laufmarke liegt noch – ein frueherer Lauf wurde '
              'abgeschossen. Arbeitsbaum pruefen (git diff frontend/js/'
              f'excel_admin.js) und {MARKE} entfernen.', file=sys.stderr)
        return 2

    shutil.copy2(ZIEL, sicherung)
    soll = md5(sicherung)
    open(MARKE, 'w').close()

    def zurueck():
        shutil.copy2(sicherung, ZIEL)
        if md5(ZIEL) != soll:
            print('ABBRUCH: Wiederherstellung NICHT byte-gleich!', file=sys.stderr)
            return False
        return True

    try:
        # ── Basislauf: ohne gruene Basis ist keine Gegenprobe deutbar ──
        ok, fail, zeilen = lauf()
        if ok is None:
            print('ABBRUCH: Basislauf ohne Bilanzzeile (abgestuerzt):',
                  file=sys.stderr)
            print(zeilen[-2000:], file=sys.stderr)
            return 2
        if fail != 0:
            print(f'ABBRUCH: Basislauf ist NICHT gruen ({ok}/{fail}). '
                  'Eine Gegenprobe darauf ist nicht deutbar.', file=sys.stderr)
            for z in zeilen:
                print('   ', z, file=sys.stderr)
            return 2
        print(f'Basislauf gruen: {ok} bestanden, 0 fehlgeschlagen\n')

        stumm = []
        for name, alt, neu, erwartet in SABOTAGEN:
            text = open(sicherung, encoding='utf-8').read()
            if text.count(alt) != 1:
                print(f'ABBRUCH: Anker fuer "{name}" kommt '
                      f'{text.count(alt)}x vor (erwartet: 1x). '
                      'Der Produktivcode hat sich geaendert.', file=sys.stderr)
                return 2
            with open(ZIEL, 'w', encoding='utf-8') as f:
                f.write(text.replace(alt, neu, 1))

            ok, fail, zeilen = lauf()
            if not zurueck():
                return 2

            if ok is None:
                print(f'  ✗ {name}: ABGESTUERZT statt FAIL – das ist kein Biss')
                stumm.append(name)
                continue
            if fail == 0:
                print(f'  ✗ {name}: 0 FAIL – STUMM')
                stumm.append(name)
                continue

            getroffen = [e for e in erwartet
                         if any(e in z for z in zeilen)]
            fehlt = [e for e in erwartet if e not in getroffen]
            if fehlt:
                print(f'  ✗ {name}: {fail} FAIL, aber nicht die erwarteten')
                for e in fehlt:
                    print(f'       nicht gemeldet: {e}')
                stumm.append(name)
            else:
                print(f'  ✓ {name}: {fail} FAIL, alle erwarteten Zusagen fallen')

        print()
        if stumm:
            print(f'ERGEBNIS: {len(stumm)} von {len(SABOTAGEN)} Sabotagen '
                  'blieben stumm – Testmangel, kein Beweis.')
            return 1
        print(f'ERGEBNIS: alle {len(SABOTAGEN)} Sabotagen beissen. Das Warten '
              'auf die Bedingung verdeckt die Zusage NICHT.')
        return 0
    finally:
        if os.path.exists(sicherung):
            shutil.copy2(sicherung, ZIEL)
            os.unlink(sicherung)
        if os.path.exists(MARKE):
            os.unlink(MARKE)


if __name__ == '__main__':
    sys.exit(main())
