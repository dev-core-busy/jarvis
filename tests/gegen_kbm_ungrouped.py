#!/usr/bin/env python3
"""Gegenproben zum Kaestchen "nicht zugeordnet" in der Wissensgruppen-Tabelle.

Jede Probe dreht GENAU EINE Zusage zurueck und muss den Waechter zum Beissen
bringen. Beisst eine nicht, ist der Waechter zahnlos - oder die Sabotage hat ihr
Ziel verfehlt; beides gehoert geprueft, nicht weggeredet.

⚠ Gesichert wird auf PLATTE, VOR jeder Probe, und die Dateiliste wird als REGEL
gegen die Proben geprueft: was eine Probe anfasst, MUSS in der Sicherung stehen -
sonst bleibt nach einem Abbruch ein sabotierter Arbeitsbaum liegen und der
naechste Lauf meldet einen Fehler, den es im Code nicht gibt.
"""
import atexit
import hashlib
import os
import pathlib
import re
import signal
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ABLAGE = pathlib.Path.home() / ".gegen-kbm-ungrouped"
MARKE = ABLAGE / "LAUF"
WAECHTER = ["node", str(ROOT / "tests" / "test_kbmatrix_ungrouped_ui.js")]

DATEIEN = [
    "frontend/js/kbmatrix.js",
    "frontend/js/i18n.js",
    "frontend/css/style.css",
    "tests/test_kbmatrix_ungrouped_ui.js",
]


def _p(rel):
    return ROOT / rel


def sichern():
    ABLAGE.mkdir(mode=0o700, exist_ok=True)
    for rel in DATEIEN:
        ziel = ABLAGE / rel.replace("/", "__")
        ziel.write_bytes(_p(rel).read_bytes())
    MARKE.write_text("laeuft\n")


def zurueck():
    fehler = []
    for rel in DATEIEN:
        q = ABLAGE / rel.replace("/", "__")
        if not q.exists():
            continue
        _p(rel).write_bytes(q.read_bytes())
        if hashlib.md5(_p(rel).read_bytes()).hexdigest() != hashlib.md5(q.read_bytes()).hexdigest():
            fehler.append(rel)
    if fehler:
        print("⚠ NICHT byte-gleich wiederhergestellt: " + ", ".join(fehler))
    return not fehler


def lauf():
    r = subprocess.run(WAECHTER, capture_output=True, text=True, cwd=str(ROOT), timeout=120)
    aus = r.stdout + r.stderr
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", aus)
    if not m:
        return None, None, aus
    return int(m.group(1)), int(m.group(2)), aus


def patch(rel, alt, neu, anzahl=1):
    """Ersetzt und BELEGT den Treffer - eine Sabotage, die nicht greift, sieht
    aus wie ein zahnloser Waechter."""
    p = _p(rel)
    s = p.read_text(encoding="utf-8")
    assert s.count(alt) >= anzahl, f"Anker nicht gefunden in {rel}: {alt[:60]!r}"
    p.write_text(s.replace(alt, neu, anzahl), encoding="utf-8")


# ── Proben ──────────────────────────────────────────────────────────────────
PROBEN = [
    ("Vorgabe AUS statt AN", "frontend/js/kbmatrix.js",
     lambda: patch("frontend/js/kbmatrix.js",
                   "let _nurUngruppiert = true;", "let _nurUngruppiert = false;")),

    ("Kaestchen gar nicht gerendert", "frontend/js/kbmatrix.js",
     lambda: patch("frontend/js/kbmatrix.js",
                   '<input type="checkbox" class="kbm-nogrp"',
                   '<input type="checkbox" class="kbm-nogrp-weg"')),

    ("Gruppen-Bedingung aus der Filterregel", "frontend/js/kbmatrix.js",
     lambda: patch("frontend/js/kbmatrix.js",
                   "const grpOk = !_nurUngruppiert || (_assign[pfad] || []).length === 0;",
                   "const grpOk = true;")),

    ("Text und Kaestchen ODER-verknuepft statt UND", "frontend/js/kbmatrix.js",
     lambda: patch("frontend/js/kbmatrix.js",
                   "const sichtbar = textOk && grpOk;",
                   "const sichtbar = textOk || grpOk;")),

    ("Zaehler nennt nur die gezeigte Zahl", "frontend/js/kbmatrix.js",
     lambda: patch("frontend/js/kbmatrix.js",
                   """        el.textContent = (gezeigt === ges)
            ? ges + ' ' + T('kbmatrix.docs', 'Dokumente')
            : T('kbmatrix.count_of', '{n} von {m} Dokumenten')
                .replace('{n}', gezeigt).replace('{m}', ges);""",
                   "        el.textContent = gezeigt + ' ' + T('kbmatrix.docs', 'Dokumente');")),

    ("change-Handler des Kaestchens raus", "frontend/js/kbmatrix.js",
     lambda: patch("frontend/js/kbmatrix.js",
                   "        if (nogrp) nogrp.addEventListener('change', () => {",
                   "        if (false) nogrp.addEventListener('change', () => {")),

    ("Kaestchen schaltet zusaetzlich SELBST um (Doppel-Toggle)", "frontend/js/kbmatrix.js",
     lambda: patch("frontend/js/kbmatrix.js",
                   "            _nurUngruppiert = nogrp.checked;",
                   "            nogrp.checked = !nogrp.checked;\n            _nurUngruppiert = nogrp.checked;")),

    # ⚠ Hier muss der ECHTE Aufruf weg. Eine tote Zeile DANEBEN zu setzen laesst
    # den Aufruf stehen - die Probe saehe dann wie ein zahnloser Waechter aus.
    ("Filter beim ersten Zeichnen nicht angewandt", "frontend/js/kbmatrix.js",
     lambda: patch("frontend/js/kbmatrix.js",
                   "        // ungefiltert da, obwohl das Kaestchen angehakt ist.\n        _filterAnwenden(ov);\n    }",
                   "        // ungefiltert da, obwohl das Kaestchen angehakt ist.\n    }")),

    ("Zuordnen zieht die Ansicht nicht nach", "frontend/js/kbmatrix.js",
     lambda: patch("frontend/js/kbmatrix.js",
                   "        // sie sichtbar und der Zaehler nennte eine Zahl, die nicht mehr stimmt.\n        _filterAnwenden(ov);",
                   "        // sie sichtbar und der Zaehler nennte eine Zahl, die nicht mehr stimmt.")),

    ("Loeschen setzt den Zaehler wieder von Hand", "frontend/js/kbmatrix.js",
     lambda: patch("frontend/js/kbmatrix.js",
                   """            // Zaehler ueber die Filterregel, nicht von Hand: sonst stuende dort
            // die Gesamtzahl, waehrend die Liste gefiltert ist.
            _filterAnwenden(ov);""",
                   """            const cnt = ov.querySelector('.kbm-count');
            if (cnt) cnt.textContent = _rows.length + ' ' + T('kbmatrix.docs', 'Dokumente');""")),

    ("i18n nur deutsch (EN fehlt)", "frontend/js/i18n.js",
     lambda: patch("frontend/js/i18n.js",
                   "        'kbmatrix.only_ungrouped':       'unassigned',\n",
                   "")),

    ("count_of ohne Gesamt-Platzhalter", "frontend/js/i18n.js",
     lambda: patch("frontend/js/i18n.js",
                   "'kbmatrix.count_of':             '{n} von {m} Dokumenten',",
                   "'kbmatrix.count_of':             '{n} Dokumente',")),

    ("CSS des Labels ganz raus", "frontend/css/style.css",
     lambda: patch("frontend/css/style.css", ".kbm-nogrp-lbl {", ".kbm-nogrp-lbl-weg {")),

    ("Filterfeld behaelt sein margin-left:auto", "frontend/css/style.css",
     lambda: patch("frontend/css/style.css",
                   ".kbm-nogrp-lbl + .kbm-filter { margin-left: 0; }",
                   "/* entfernt */")),

    ("Zaehler zurueck auf --text-muted", "frontend/css/style.css",
     lambda: patch("frontend/css/style.css",
                   ".kbm-count { font-weight: 400; font-size: 0.8rem; color: var(--text-secondary);",
                   ".kbm-count { font-weight: 400; font-size: 0.8rem; color: var(--text-muted);")),
]


def main():
    # Rueckstand eines abgeschossenen Laufs zuerst zuruecknehmen.
    if MARKE.exists():
        print("⚠ Rueckstand eines frueheren Laufs gefunden – stelle wieder her")
        zurueck()
        MARKE.unlink(missing_ok=True)

    # REGEL: jede von einer Probe angefasste Datei muss gesichert werden.
    fehlend = {rel for _, rel, _ in PROBEN} - set(DATEIEN)
    if fehlend:
        print("ABBRUCH: nicht gesicherte Dateien in den Proben: " + ", ".join(sorted(fehlend)))
        sys.exit(2)

    sichern()
    atexit.register(lambda: (zurueck(), MARKE.unlink(missing_ok=True)))
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *a: sys.exit(1))

    b_ok, b_fail, aus = lauf()
    if b_fail is None:
        print("ABBRUCH: Basislauf ohne Bilanzzeile\n" + aus[-2000:])
        sys.exit(2)
    if b_fail != 0:
        print(f"ABBRUCH: Basis ist NICHT gruen ({b_ok} OK, {b_fail} FAIL) – "
              "ohne gruene Basis ist keine Gegenprobe deutbar\n" + aus[-2000:])
        sys.exit(2)
    print(f"Basis: {b_ok} OK, 0 FAIL\n")

    beisst = 0
    for name, rel, tun in PROBEN:
        zurueck()
        try:
            tun()
        except AssertionError as e:
            print(f"  ✗ {name}: SABOTAGE VERFEHLT – {e}")
            continue
        o, f, a = lauf()
        if f is None:
            print(f"  ✓ {name}: Waechter bricht ab (kein Ergebnis) – zaehlt als Beissen")
            beisst += 1
        elif f > 0:
            beisst += 1
            print(f"  ✓ {name}: {f} FAIL")
        else:
            print(f"  ✗ {name}: BEISST NICHT ({o} OK)")

    zurueck()
    MARKE.unlink(missing_ok=True)
    print(f"\nErgebnis: {beisst} von {len(PROBEN)} Proben beissen")
    sys.exit(0 if beisst == len(PROBEN) else 1)


if __name__ == "__main__":
    main()
