#!/usr/bin/env python3
"""
Gegenproben zum Vorlagen-Pulldown in "Prompt optimieren" -> Eigene Anweisung.

Jede Probe dreht GENAU EINE Zusage zurueck und misst, ob der Waechter das
meldet. Eine Probe, die nicht beisst, ist ein Testmangel - kein Beweis.

⚠ SICHERUNG AUF PLATTE UND LAUFMARKE (Register): wird dieses Skript per
Zeitlimit abgeschossen, laeuft das `finally` nicht und der Arbeitsbaum bleibt
sabotiert - der naechste Testlauf meldet dann einen Fehler, den es nicht gibt.
Die Marke bleibt nur nach einem kill -9 liegen; dann greift das Zuruecknehmen
beim naechsten Start.

⚠ DIE SICHERUNGSLISTE WIRD ALS REGEL GEPRUEFT: jede Datei, die eine Probe
anfasst, muss darin stehen (sonst Exit 2).
"""
import subprocess, sys, shutil, atexit, signal
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ABLAGE = Path.home() / '.gegen-anw-vorlagen'
MARKE = ABLAGE / 'LAUFT'

DATEIEN = [
    'frontend/js/knowledge.js',
    'frontend/js/i18n.js',
    'frontend/css/style.css',
    'tests/test_aufraeumen_ui.js',
]


def sichern():
    ABLAGE.mkdir(mode=0o700, exist_ok=True)
    for rel in DATEIEN:
        ziel = ABLAGE / rel.replace('/', '__')       # relativer Pfad als Schluessel
        shutil.copy2(REPO / rel, ziel)
    MARKE.write_text('laeuft\n')


def zurueck():
    for rel in DATEIEN:
        q = ABLAGE / rel.replace('/', '__')
        if q.exists():
            shutil.copy2(q, REPO / rel)
    if MARKE.exists():
        MARKE.unlink()


def lauf():
    p = subprocess.run(['node', str(REPO / 'tests/test_aufraeumen_ui.js')],
                       capture_output=True, text=True, timeout=180, cwd=REPO)
    letzte = [z for z in p.stdout.strip().splitlines() if 'Ergebnis:' in z]
    if not letzte:
        return None, p.stdout[-400:]                 # kein Ergebnis = abgebrochen
    import re
    m = re.search(r'(\d+) OK, (\d+) FAIL', letzte[-1])
    return (int(m.group(2)) if m else None), letzte[-1]


def patch(rel, alt, neu, anzahl=1):
    if callable(alt):                            # Sonderfall: eigener Eingriff
        alt()
        return
    p = REPO / rel
    s = p.read_text(encoding='utf-8')
    assert s.count(alt) >= 1, f'Anker nicht gefunden in {rel}: {alt[:60]!r}'
    p.write_text(s.replace(alt, neu, anzahl), encoding='utf-8')


def vorlage_unter_das_feld():
    """Vertauscht Vorlagen-Zeile und Eingabefeld im Markup.

    ⚠ NICHT ueber `style="order:9"` - `.kb-cl-anw` ist KEIN Flex-Container,
    die Sabotage waere wirkungslos und der Waechter saehe zahnlos aus (in
    genau diese Falle bin ich beim ersten Anlauf gelaufen). Verschoben wird
    das Markup selbst, dann misst die Probe, was sie meint.
    """
    p = REPO / 'frontend/js/knowledge.js'
    s = p.read_text(encoding='utf-8')
    a0 = s.index('            <div class="kb-cl-anw-vorl-zeile">')
    a1 = s.index('            <textarea id="kb-cl-anw-text"', a0)
    b1 = s.index('</textarea>', a1) + len('</textarea>')
    block_vorl, block_feld = s[a0:a1].rstrip('\n'), s[a1:b1]
    p.write_text(s[:a0] + block_feld + '\n' + block_vorl + '\n' + s[b1:],
                 encoding='utf-8')


PROBEN = [
    # (Name, Datei, alt, neu)
    # ⚠ Die ID umbenennen, NICHT das Markup auskommentieren: ein unbalanciertes
    # <!-- zerlegt den ganzen Kasten, dann fehlt auch das Eingabefeld und der
    # Waechter bricht ab statt fehlzuschlagen - gemessen wuerde dann die
    # Robustheit des Tests, nicht die Zusage.
    ('Pulldown gar nicht gezeichnet', 'frontend/js/knowledge.js',
     '<select id="kb-cl-anw-vorlage"', '<select id="kb-cl-anw-vorlage-weg"'),
    ('das input-Ereignis faellt aus (Knopf bleibt gesperrt)', 'frontend/js/knowledge.js',
     "feld.dispatchEvent(new Event('input', { bubbles: true }));", '// kein Ereignis'),
    ('Merker steht NACH dem Ereignis (Wahl loescht sich selbst)', 'frontend/js/knowledge.js',
     "feld.value = txt;\n            this._anwVorlText = txt;",
     "feld.value = txt;"),
    ('getippter Text wird ungefragt ueberschrieben', 'frontend/js/knowledge.js',
     "if (da && feld.value !== this._anwVorlText\n                && !window.confirm(window.t('knowledge.cleanup.anw_vorl_ersetzen'))) {",
     "if (false) {"),
    ('bei "nein" faellt das Pulldown nicht zurueck', 'frontend/js/knowledge.js',
     "sel.value = '';                // die Wahl hat nicht stattgefunden",
     "// nichts"),
    ('bearbeiteter Text laesst das Pulldown die Vorlage behaupten',
     'frontend/js/knowledge.js',
     "if (sel && sel.value && feld.value !== this._anwVorlText) sel.value = '';",
     "/* nichts */"),
    ('bei jedem Vorlagenwechsel wird gefragt', 'frontend/js/knowledge.js',
     'feld.value !== this._anwVorlText\n                && !window.confirm',
     'true\n                && !window.confirm'),
    ('die Sicherheits-Vorlage fehlt', 'frontend/js/knowledge.js',
     "return ['sicherheit', 'veraltet', 'straffen', 'regeln'];",
     "return ['veraltet', 'straffen', 'regeln'];"),
    ('eine Vorlage ohne i18n-Text', 'frontend/js/knowledge.js',
     "return ['sicherheit', 'veraltet', 'straffen', 'regeln'];",
     "return ['sicherheit', 'veraltet', 'straffen', 'regeln', 'gibtesnicht'];"),
    ('der Auftragstext ist nur eine Floskel', 'frontend/js/i18n.js',
     "'knowledge.cleanup.anw_vt_regeln': 'Formuliere den Inhalt als klare Regeln",
     "'knowledge.cleanup.anw_vt_regeln': 'Mach es kurz.', 'x.y': 'Formuliere den Inhalt als klare Regeln"),
    ('eine Vorlage nur auf Deutsch', 'frontend/js/i18n.js',
     "'knowledge.cleanup.anw_v_veraltet': 'Track down outdated details',",
     "'knowledge.cleanup.anw_v_veraltet_EN': 'Track down outdated details',"),
    ('das Pulldown steht unter dem Feld', 'frontend/js/knowledge.js',
     vorlage_unter_das_feld, None),
    ('der Cursor bleibt am Textende (man liest den Schluss)', 'frontend/js/knowledge.js',
     'try { feld.setSelectionRange(0, 0); } catch (e) { /* alte Browser */ }\n            feld.scrollTop = 0;',
     '// ans Ende'),
    ('min-width am Pulldown entfaellt', 'frontend/css/style.css',
     '.kb-cl-anw-vorl {\n    flex: 1 1 240px;\n    min-width: 0;',
     '.kb-cl-anw-vorl {\n    flex: 1 1 240px;'),
    ('die Zeile bricht nicht mehr um', 'frontend/css/style.css',
     'display: flex; align-items: center; gap: 8px; flex-wrap: wrap;\n    margin: 0 0 8px;',
     'display: flex; align-items: center; gap: 8px;\n    margin: 0 0 8px;'),
    ('die Eintraege tragen den ganzen Auftragstext als Beschriftung',
     'frontend/js/knowledge.js',
     "window.t('knowledge.cleanup.anw_v_' + k))}</option>",
     "window.t('knowledge.cleanup.anw_vt_' + k))}</option>"),
]


def main():
    # Regel: keine Probe ausserhalb der Sicherungsliste.
    fremd = {rel for _, rel, _, _ in PROBEN} - set(DATEIEN)
    if fremd:
        print(f'\033[31mExit 2: Proben fassen ungesicherte Dateien an: {fremd}\033[0m')
        sys.exit(2)

    if MARKE.exists():
        print('\033[33mRueckstand eines abgebrochenen Laufs - wird zurueckgenommen.\033[0m')
        zurueck()

    sichern()
    atexit.register(zurueck)
    for s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(s, lambda *_: sys.exit(1))

    basis, zeile = lauf()
    if basis != 0:
        print(f'\033[31mExit 2: Basislauf ist NICHT gruen ({zeile}) - '
              f'ohne gruene Basis ist keine Gegenprobe deutbar.\033[0m')
        sys.exit(2)
    print(f'\033[32mBasis gruen: {zeile}\033[0m\n')

    beisst = 0
    for name, rel, alt, neu in PROBEN:
        try:
            patch(rel, alt, neu)
        except AssertionError as e:
            print(f'  \033[31m✗ {name}: ANKER VERFEHLT ({e})\033[0m')
            zurueck()
            continue
        fail, zeile = lauf()
        zurueck()
        # md5-Gleichheit nach dem Wiederherstellen
        if fail is None:
            print(f'  \033[31m✗ {name}: Lauf ohne Bilanz ({zeile})\033[0m')
        elif fail > 0:
            print(f'  \033[32m✓ {name}: {fail} FAIL\033[0m'); beisst += 1
        else:
            print(f'  \033[31m✗ {name}: beisst NICHT (0 FAIL)\033[0m')

    print(f'\n\033[1m{beisst} von {len(PROBEN)} Proben beissen\033[0m')
    sys.exit(0 if beisst == len(PROBEN) else 1)


if __name__ == '__main__':
    main()
