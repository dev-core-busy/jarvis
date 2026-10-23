#!/usr/bin/env python3
"""Gegenproben zu den Excel-Objekten: beisst jeder Waechter EINZELN?

Eine Gegenprobe, die nicht beisst, ist ein TESTMANGEL – kein Beweis. Gemessen
wird am **Exit-Code UND an der Bilanzzeile**, nie am Zaehlen von FAIL-Zeilen:
ein Lauf, der ohne Bilanz abbricht, ist von „bestanden" nicht zu unterscheiden.

⚠ DIE SICHERUNGSLISTE WIRD ALS REGEL GEPRUEFT. Faehrt eine Probe eine Datei an,
die nicht gesichert ist, bleibt die Sabotage liegen – und der naechste Lauf
meldet einen Fehler, den es im Code nicht gibt. Das ist im Projekt zweimal
passiert (Register).
"""
from __future__ import annotations

import atexit
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ABLAGE = Path.home() / ".gegen-excel-objekte"
MARKE = ABLAGE / "laeuft"

DATEIEN = [
    "frontend/excel-addin/taskpane.html",
    "backend/excel_objekte.py",
    "backend/excel_ask.py",
    "backend/excel_addin.py",
    "backend/main.py",
    "backend/tools/excel_vorschlag.py",
    "frontend/excel-addin/excel.js",
    "frontend/js/i18n.js",
]

WAECHTER = [
    ("py", "tests/test_excel_objekte.py"),
    ("py", "tests/test_excel_spalten_hinweis.py"),
    ("py", "tests/test_excel_leerlauf.py"),
    ("py", "tests/test_excel_fuellwert.py"),
    ("js", "tests/test_excel_leerlauf_ui.js"),
    ("js", "tests/test_excel_reiter_ui.js"),
    ("js", "tests/test_excel_objekte_ui.js"),
    ("js", "tests/test_excel_kommentar_ui.js"),
]


def sichern() -> None:
    """Sichert bei JEDEM Lauf neu – eine alte Sicherung stellte sonst beim
    zweiten Durchgang einen VERALTETEN Stand her und machte fertige Arbeit
    zunichte (Register, 2026-09-05)."""
    ABLAGE.mkdir(parents=True, exist_ok=True)
    for rel in DATEIEN:
        ziel = ABLAGE / rel.replace("/", "__")
        shutil.copy2(ROOT / rel, ziel)
    MARKE.write_text("1")


def zurueck() -> None:
    for rel in DATEIEN:
        q = ABLAGE / rel.replace("/", "__")
        if q.exists():
            shutil.copy2(q, ROOT / rel)


def aufraeumen() -> None:
    zurueck()
    if MARKE.exists():
        MARKE.unlink()


def lauf(art: str, pfad: str) -> tuple[int, str]:
    cmd = ([sys.executable, pfad] if art == "py" else ["node", pfad])
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=120)
    return (p.returncode, p.stdout + p.stderr)


def bilanz_fails(ausgabe: str) -> int | None:
    """Liest die FAIL-Zahl aus der Bilanzzeile. ``None`` = keine Bilanz."""
    for zeile in reversed(ausgabe.strip().splitlines()):
        if zeile.startswith("Ergebnis:"):
            if "ABGEBROCHEN" in zeile:
                return None
            try:
                return int(zeile.split(",")[1].strip().split()[0])
            except Exception:  # noqa: BLE001
                return None
    return None


def patch(rel: str, alt: str, neu: str) -> None:
    p = ROOT / rel
    s = p.read_text()
    # TREFFERKONTROLLE: eine Ersetzung ohne assert ist kein Messwert – die
    # Probe saehe wie ein zahnloser Waechter aus, waehrend sie gar nicht griff.
    assert alt in s, "Anker nicht gefunden in %s: %r" % (rel, alt[:70])
    p.write_text(s.replace(alt, neu, 1))


# ── Proben ────────────────────────────────────────────────────────────────
# (Name, Dateien die sie anfasst, Funktion)
PROBEN = []


def probe(name: str, *dateien):
    def deko(fn):
        PROBEN.append((name, list(dateien), fn))
        return fn
    return deko


@probe("Objekt-Zweig aus excel_ask entfernt", "backend/excel_ask.py")
def _p1():
    patch("backend/excel_ask.py",
          "        if _objekte.ist_objekt(eintrag):",
          "        if False and _objekte.ist_objekt(eintrag):")


@probe("Blatt-Anlage nur ueber die Zellen", "frontend/excel-addin/excel.js")
def _p2():
    patch("frontend/excel-addin/excel.js",
          "            var angelegt = [];\n            alle.forEach(function (a) {",
          "            var angelegt = [];\n            aenderungen.forEach(function (a) {")


@probe("Objekte VOR den Zellen", "frontend/excel-addin/excel.js")
def _p3():
    # Den Objekt-Schritt vor die Kosmetik ziehen heisst hier: vor das
    # Zellschreiben, weil der Kosmetik-Schritt erst nach dem Schreiben laeuft.
    patch("frontend/excel-addin/excel.js",
          "        var objekte = alle.filter(istObjekt);",
          "        var objekte = [];  // sabotiert: keine Objekte mehr")


@probe("Tabelle wird GELOESCHT statt zurueckverwandelt",
       "frontend/excel-addin/excel.js")
def _p4():
    patch("frontend/excel-addin/excel.js",
          "s.tables.getItem(a._objName || a.name).convertToRange();",
          "s.tables.getItem(a._objName || a.name).delete();")


@probe("bedingtes Format per clearAll entfernt", "frontend/excel-addin/excel.js")
def _p5():
    patch("frontend/excel-addin/excel.js",
          "s.getRange(a.adresse).conditionalFormats.getItemAt(0).delete();",
          "s.getRange(a.adresse).conditionalFormats.clearAll();")


@probe("1.8-Pruefung entfernt (Wurf statt Absage)",
       "frontend/excel-addin/excel.js")
def _p6():
    patch("frontend/excel-addin/excel.js",
          "        if (a.typ === 'pivot' && !_kann18) {",
          "        if (a.typ === 'pivot' && false) {")


@probe("summarizeBy wird nicht gesetzt", "frontend/excel-addin/excel.js")
def _p7():
    patch("frontend/excel-addin/excel.js",
          "                    try { dh.summarizeBy = w.funktion; } catch (e) { }",
          "                    try { dh._x = w.funktion; } catch (e) { }")


@probe("Vergleichswert ohne fuehrendes =", "frontend/excel-addin/excel.js")
def _p8():
    patch("frontend/excel-addin/excel.js",
          "var regel = { formula1: '=' + String(a.wert), operator:",
          "var regel = { formula1: String(a.wert), operator:")


@probe("Name wird nicht zurueckgelesen (kein Rueckweg)",
       "frontend/excel-addin/excel.js")
def _p9():
    patch("frontend/excel-addin/excel.js",
          "            try { erzeugt.load('name'); } catch (e) { }",
          "            /* sabotiert: kein load */")


@probe("_angelegt wird nicht gesetzt", "frontend/excel-addin/excel.js")
def _p10():
    patch("frontend/excel-addin/excel.js",
          "Ruecknahmen mit.\n                    a._angelegt = true;\n                    return { a: a, ok: true };",
          "Ruecknahmen mit.\n                    return { a: a, ok: true };")


@probe("Fehlermeldung nennt Werte, die selbst abgelehnt wuerden",
       "backend/excel_objekte.py")
def _p11():
    # ⚠ NICHT bei den Operatoren ansetzen: dort sind die Office-Namen seit
    # 2026-09-15 ZUSAETZLICH gueltige Eingaben, die Sabotage waere also
    # harmlos und die Probe ein falscher Alarm. Bei den Diagrammarten ist
    # `"ColumnClustered".lower()` dagegen KEIN Schluessel – die Meldung
    # schickte den Leser dann im Kreis.
    patch("backend/excel_objekte.py",
          '% (art[:30], ", ".join(HAUPT_ARTEN)))',
          '% (art[:30], ", ".join(sorted(set(DIAGRAMM_ARTEN.values())))))')


@probe("api_min fuer pivot faelschlich auf 1.7", "backend/excel_objekte.py")
def _p12():
    patch("backend/excel_objekte.py", '"pivot": "1.8",', '"pivot": "1.7",')


@probe("Manifest wird auf 1.8 hochgezogen", "backend/excel_addin.py")
def _p13():
    patch("backend/excel_addin.py", 'EXCEL_API_MIN = "1.7"', 'EXCEL_API_MIN = "1.8"')


@probe("kopfzeile per Falsyness statt is False", "backend/excel_objekte.py")
def _p14():
    patch("backend/excel_objekte.py",
          'ziel["kopfzeile"] = e.get("kopfzeile") is not False',
          'ziel["kopfzeile"] = bool(e.get("kopfzeile"))')


@probe("Tabellenname wird nicht geprueft", "backend/excel_objekte.py")
def _p15():
    patch("backend/excel_objekte.py",
          '    if typ == "tabelle":\n        if _WIE_ZELLE_RE.match(name):',
          '    if False:\n        if _WIE_ZELLE_RE.match(name):')


@probe("Pivot ohne Wertfeld wird durchgelassen", "backend/excel_objekte.py")
def _p16():
    patch("backend/excel_objekte.py",
          "    if not werte_roh:\n        return (\"Eine Pivot-Tabelle braucht mindestens ein Wertfeld \"",
          "    if False:\n        return (\"Eine Pivot-Tabelle braucht mindestens ein Wertfeld \"")


@probe("jeder typ gilt wieder als Objekt (Stand vor 2026-10-23)",
       "backend/excel_objekte.py")
def _p18():
    # Der ALTE Zustand: das blosse Vorhandensein des Feldes entschied. Ein
    # mit `typ: "werte"` etikettierter Zell-Eintrag wird dann abgelehnt.
    patch("backend/excel_objekte.py",
          "    if typ in API_MIN:\n        return True",
          "    if typ:\n        return True")


@probe("unbekannter typ gilt immer als Zelle (Gegenrichtung)",
       "backend/excel_objekte.py")
def _p19():
    # Die gefaehrlichere Haelfte: ein verschriebenes 'bedingt' liefe damit in
    # den Zell-Zweig und schriebe seinen Vergleichswert in den Bereich.
    patch("backend/excel_objekte.py",
          "    if _hat_eines(eintrag, _OBJEKT_FELDER):\n        return True",
          "    if False:\n        return True")


@probe("Kommentar-Deduplizierung entfernt (Stand vor 2026-10-23)",
       "frontend/excel-addin/excel.js")
def _p20():
    # Der ALTE Zustand: jedes Ziel bekommt seinen `add`. Bei drei Eintraegen
    # auf dieselbe Ankerzelle wirft der zweite InvalidOperation.
    patch("frontend/excel-addin/excel.js",
          "                var kommentiert = Object.keys(jeAnker).map(function (k) {\n"
          "                    return jeAnker[k];\n"
          "                });",
          "                var kommentiert = ziele.filter(function (z) {\n"
          "                    return !!z.a.begruendung;\n"
          "                });")


@probe("Dedup ueber die ADRESSE statt die Ankerzelle",
       "frontend/excel-addin/excel.js")
def _p21():
    # Die subtilere Haelfte: B12:AN12 und B12:B20 sind verschiedene Adressen
    # mit DERSELBEN Ankerzelle – `comments.add` traefe trotzdem zweimal B12.
    patch("frontend/excel-addin/excel.js",
          "            String(a.adresse || '').split(':')[0].replace(/\\$/g, '').toUpperCase();",
          "            String(a.adresse || '').replace(/\\$/g, '').toUpperCase();")


@probe("Spalten-Hinweis ganz weg (Stand vor 2026-10-23)",
       "backend/excel_ask.py")
def _p22():
    patch("backend/excel_ask.py",
          "    if gesamt <= MAX_SPALTEN_ANZEIGE:\n        return \"\"",
          "    if True:\n        return \"\"")


@probe("Hinweis ohne die ZAHL (nur 'gekuerzt')", "backend/excel_ask.py")
def _p23():
    # Eine Kuerzung ohne Bezifferung laesst das Modell raten, WIE viel fehlt.
    # ⚠ DIE ZAHL MUSS WIRKLICH WEG. Der erste Versuch liess `%d` stehen und
    # beiss deshalb nicht – gleichzeitig deckte er auf, dass der Waechter die
    # Zahl im ganzen BLOCK suchte, wo der Blattkopf sie ohnehin nennt.
    patch("backend/excel_ask.py",
          '    return ("    ⚠ Unten sind nur die Spalten %s–%s von %d gelistet (das Blatt "\n'
          '            "geht bis %s). Die Tabelle endet NICHT bei %s – die übrigen "\n'
          '            "Spaltenköpfe wurden nur nicht mitgeschickt. Brauchst du sie, "\n'
          '            "fordere sie nach: [[EXCEL_BRAUCHE: %s]]"\n'
          '            % (erste, letzte, gesamt, ende, letzte, bereich))',
          '    return ("    ⚠ Unten sind nur die Spalten %s–%s gelistet (das Blatt "\n'
          '            "geht bis %s). Die Tabelle endet NICHT bei %s – die übrigen "\n'
          '            "Spaltenköpfe wurden nur nicht mitgeschickt. Brauchst du sie, "\n'
          '            "fordere sie nach: [[EXCEL_BRAUCHE: %s]]"\n'
          '            % (erste, letzte, ende, letzte, bereich))')


@probe("Hinweis ohne Nachforderung (nennt den Weg nicht)",
       "backend/excel_ask.py")
def _p24():
    patch("backend/excel_ask.py",
          '            "fordere sie nach: [[EXCEL_BRAUCHE: %s]]"',
          '            "frage den Benutzer. %s"')


@probe("Hinweis steht NACH der Liste (Kappung schneidet ihn weg)",
       "backend/excel_ask.py")
def _p25():
    # ⚠ BEIDE Zweige umstellen – sonst beisst nur Abschnitt 3 oder nur 7, und
    # man haelt den Waechter fuer schwach statt den Code fuer halb geaendert.
    for anker in ('            if hinweis:\n'
                  '                zeilen.append(hinweis)\n'
                  '            zeilen.append("    Spalten: %s" % " | ".join(paare))\n'
                  '        for k, zeile in enumerate((b.get("beispiele") or [])[:MAX_BEISPIELE]):',
                  '            if hinweis:\n'
                  '                zeilen.append(hinweis)\n'
                  '            zeilen.append("    Spalten: %s" % " | ".join(paare))\n'
                  '\n'
                  '    # ── Datenzeilen vom oberen Rand ─────────────────────────────────────'):
        neu = anker.replace(
            '            if hinweis:\n'
            '                zeilen.append(hinweis)\n'
            '            zeilen.append("    Spalten: %s" % " | ".join(paare))',
            '            zeilen.append("    Spalten: %s" % " | ".join(paare))\n'
            '            if hinweis:\n'
            '                zeilen.append(hinweis)')
        patch("backend/excel_ask.py", anker, neu)


@probe("Alt-Zweig bleibt ohne Hinweis (zwei von drei Zweigen)",
       "backend/excel_ask.py")
def _p26():
    patch("backend/excel_ask.py",
          '            if hinweis:\n'
          '                zeilen.append(hinweis)\n'
          '            zeilen.append("    Spalten: %s" % " | ".join(paare))\n'
          '        for k, zeile in enumerate((b.get("beispiele") or [])[:MAX_BEISPIELE]):',
          '            zeilen.append("    Spalten: %s" % " | ".join(paare))\n'
          '        for k, zeile in enumerate((b.get("beispiele") or [])[:MAX_BEISPIELE]):')


@probe("Spalten ab A gezaehlt statt ab dem benutzten Bereich",
       "backend/excel_ask.py")
def _p27():
    # Der benutzte Bereich beginnt nicht immer bei A1 – die Nachforderung
    # laege sonst eine Spalte daneben, und das faellt niemandem auf.
    patch("backend/excel_ask.py",
          "    naechste = spaltenbuchstabe(spalte_ab + MAX_SPALTEN_ANZEIGE)",
          "    naechste = spaltenbuchstabe(1 + MAX_SPALTEN_ANZEIGE)")


@probe("Prompt deutet den Hinweis nicht mehr", "backend/excel_ask.py")
def _p28():
    patch("backend/excel_ask.py",
          "- **Die Spaltenliste ist gekürzt, wenn ein ⚠-Hinweis darüber steht.**",
          "- Die Spaltenliste zeigt die Spalten des Blattes.")


@probe("letzte_runde wird nicht uebergeben (Wurzel-Fix tot)",
       "backend/main.py")
def _p29():
    patch("backend/main.py",
          "        letzte_runde=runde >= grenze_runden)",
          "        letzte_runde=False)")


@probe("Auftrag warnt nicht vor der letzten Runde", "backend/excel_ask.py")
def _p30():
    patch("backend/excel_ask.py",
          "    if letzte_runde:\n"
          '        teile.append(marke % "LETZTE RUNDE – KEINE NACHFORDERUNG MEHR MÖGLICH")',
          "    if False:\n"
          '        teile.append(marke % "LETZTE RUNDE – KEINE NACHFORDERUNG MEHR MÖGLICH")')


@probe("verworfene Nachforderung laeuft wieder ins Leere (Guertel weg)",
       "backend/main.py")
def _p31():
    patch("backend/main.py",
          "        if verworfen:\n"
          '            grund = "runden_erschoepft"',
          "        if False:\n"
          '            grund = "runden_erschoepft"')


@probe("Grund wird nicht mitgeschickt (Fenster muss raten)",
       "backend/main.py")
def _p32():
    patch("backend/main.py",
          '                         "grund": grund,',
          '                         "_grund_weg": grund,')


@probe("Lauf wird nicht mehr protokolliert", "frontend/excel-addin/excel.js")
def _p33():
    patch("frontend/excel-addin/excel.js",
          "        protokoll('lauf', 'runde ' + runde + '/'",
          "        if (false) protokoll('lauf', 'runde ' + runde + '/'")


@probe("alte Schuldzuweisung kehrt zurueck", "frontend/js/i18n.js")
def _p34():
    patch("frontend/js/i18n.js",
          "'Der Assistent hat keine Antwort geliefert. Das muss nicht an deiner Frage liegen – versuche es noch einmal oder grenze die Frage auf einen kleineren Bereich ein.'",
          "'Der Assistent hat keine Antwort formuliert. Formuliere die Frage bitte anders.'")


@probe("Faelle werden im Fenster nicht unterschieden",
       "frontend/excel-addin/excel.js")
def _p35():
    patch("frontend/excel-addin/excel.js",
          "            if (d.grund === 'modell_stumm') {",
          "            if (false && d.grund === 'modell_stumm') {")


@probe("Spalten-Deckel zurueck auf 40 (Stand vor der Behebung)",
       "backend/excel_ask.py")
def _p36():
    patch("backend/excel_ask.py",
          "MAX_SPALTEN_ANZEIGE = 300      # Spalten je Blatt in der Spaltenliste",
          "MAX_SPALTEN_ANZEIGE = 40       # Spalten je Blatt in der Spaltenliste")


@probe("Fenster laedt wieder nur 40 Spalten (Drift zum Backend)",
       "frontend/excel-addin/excel.js")
def _p37():
    patch("frontend/excel-addin/excel.js",
          "    var PROBE_SPALTEN = 300;",
          "    var PROBE_SPALTEN = 40;")


@probe("Beispielzeilen wachsen mit (Koepfe werden erdrueckt)",
       "backend/excel_ask.py")
def _p38():
    patch("backend/excel_ask.py",
          "def _zeile_text(werte, spalte_ab: int, grenze: int = MAX_SPALTEN_BEISPIEL) -> str:",
          "def _zeile_text(werte, spalte_ab: int, grenze: int = MAX_SPALTEN_ANZEIGE) -> str:")


@probe("Formeln/Formate kommen wieder aus dem breiten Bereich",
       "frontend/excel-addin/excel.js")
def _p39():
    patch("frontend/excel-addin/excel.js",
          "                e.probeFormeln = i.probeDetail.formulas || [];",
          "                e.probeFormeln = i.probe.formulas || [];")


@probe("0-Verbot aus dem Prompt entfernt", "backend/excel_ask.py")
def _p40():
    patch("backend/excel_ask.py",
          "- **ERFINDE NIEMALS EINEN WERT, WEIL DU EINEN PARTNER NICHT FINDEST.**",
          "- Trage die Werte ein, die du zuordnen kannst.")


@probe("Blatt-Budget zurueck auf 4000 (schneidet die Liste ab)",
       "backend/excel_ask.py")
def _p41():
    patch("backend/excel_ask.py", "MAX_BLOCK_LEN = 14000", "MAX_BLOCK_LEN = 4000")


@probe("debug schaltet Diagnose AB statt ZU", "frontend/excel-addin/excel.js")
def _p42():
    # Die tragende Zusage des Schalters: er nimmt nichts weg. Haengte die
    # gewoehnliche Zeile an `debugAn()`, waere ein Protokoll ohne Schalter
    # leer – genau der Zustand, der am 2026-10-23 die Fehlersuche blockierte.
    patch("frontend/excel-addin/excel.js",
          "    function protokoll(bereich, text) {\n        try {",
          "    function protokoll(bereich, text) {\n        if (!debugAn()) return;\n        try {")


@probe("Debug-Zeile kommt auch ohne Schalter", "frontend/excel-addin/excel.js")
def _p43():
    patch("frontend/excel-addin/excel.js",
          "    function protokollDebug(bereich, textFn) {\n        if (!debugAn()) return;",
          "    function protokollDebug(bereich, textFn) {\n        if (false) return;")


@probe("Reiter oeffnen beide Panels", "frontend/excel-addin/excel.js")
def _p44():
    patch("frontend/excel-addin/excel.js",
          "            var zu = (p.id !== 'xl-panel-' + offen);",
          "            var zu = false;")


@probe("aria-selected wird nicht mitgefuehrt", "frontend/excel-addin/excel.js")
def _p45():
    # Optisch richtig, fuer einen Screenreader falsch – zwei Quellen fuer
    # einen Zustand.
    patch("frontend/excel-addin/excel.js",
          "            r.setAttribute('aria-selected', an ? 'true' : 'false');",
          "            r.setAttribute('aria-selected', 'false');")


@probe("Klick auf den offenen Reiter schliesst nicht",
       "frontend/excel-addin/excel.js")
def _p46():
    patch("frontend/excel-addin/excel.js",
          "        return reiterZeigen(war ? '' : name);",
          "        return reiterZeigen(name);")


@probe("debug-Zustand wird nicht gespeichert", "frontend/excel-addin/excel.js")
def _p47():
    patch("frontend/excel-addin/excel.js",
          "        try { localStorage.setItem(DEBUG_KEY, v); } catch (e) { _speicherGeht = false; }",
          "        try { /* sabotiert */ } catch (e) { }")


@probe("Protokoll-Panel liegt wieder IM Einstellungs-Panel",
       "frontend/excel-addin/taskpane.html")
def _p48():
    # Die alte Verschachtelung – der Benutzer muss erst die Einstellungen
    # aufklappen, um an das Protokoll zu kommen.
    #
    # ⚠ DER ERSTE VERSUCH SETZTE NUR EIN ZUSATZ-ATTRIBUT und veraenderte damit
    # GAR NICHTS an der Struktur: die Probe blieb stumm, und das sah nach einem
    # blinden Waechter aus. Eine Sabotage muss die Eigenschaft wirklich
    # aufheben (Register: die Sabotage war zu schwach, nicht der Waechter
    # zahnlos). Hier wird das schliessende </div> des Einstellungs-Panels
    # WEGGENOMMEN und hinter dem Protokoll-Panel wieder eingesetzt – damit
    # wird proto zum Kind von einst, genau wie vor dem Umbau.
    patch("frontend/excel-addin/taskpane.html",
          '        <div class="xl-hint" data-i18n="xl.instr_note">Vorgaben bestimmen die Form'
          ' – sie lösen keine Änderung aus und heben keine Sicherheitsregel auf.</div>\n'
          '    </div>\n',
          '        <div class="xl-hint" data-i18n="xl.instr_note">Vorgaben bestimmen die Form'
          ' – sie lösen keine Änderung aus und heben keine Sicherheitsregel auf.</div>\n')
    patch("frontend/excel-addin/taskpane.html",
          '            <span class="xl-status" id="xl-log-status"></span>\n'
          '        </div>\n'
          '    </div>\n',
          '            <span class="xl-status" id="xl-log-status"></span>\n'
          '        </div>\n'
          '    </div>\n'
          '    </div>\n')


@probe("Fuellwert-Riegel entfernt (Stand vor der Behebung)",
       "backend/excel_ask.py")
def _p49():
    patch("backend/excel_ask.py",
          "        elif _ist_fuellwert(wert) and zellen > MAX_FUELL_ZELLEN:",
          "        elif False:")


@probe("Riegel greift auch bei ECHTEN Werten (Funktionssperre)",
       "backend/excel_ask.py")
def _p50():
    # Die Gegenrichtung: ein Riegel, der zu viel faengt, macht eine normale
    # Aufgabe unmoeglich - und das faellt im Betrieb erst spaeter auf.
    patch("backend/excel_ask.py",
          "        elif _ist_fuellwert(wert) and zellen > MAX_FUELL_ZELLEN:",
          "        elif zellen > MAX_FUELL_ZELLEN:")


@probe("Fuellwert-Erkennung blind fuer die leere Zeichenkette",
       "backend/excel_ask.py")
def _p51():
    patch("backend/excel_ask.py",
          '        return wert.strip().lower() in ("", "0", "-", "n/a", "na", "null")',
          '        return wert.strip().lower() in ("x-nie-x",)')


@probe("Deckel so hoch, dass er nie greift", "backend/excel_ask.py")
def _p52():
    patch("backend/excel_ask.py", "MAX_FUELL_ZELLEN = 25",
          "MAX_FUELL_ZELLEN = 100000")


@probe("Transponierung entfernt (gemeldete Ablehnung kehrt zurueck)",
       "backend/excel_ask.py")
def _p53():
    patch("backend/excel_ask.py",
          "        matrix = [list(z) for z in zip(*matrix)]",
          "        pass  # sabotiert: nicht gedreht")


@probe("Transponierung raet auch bei Mehrdeutigkeit",
       "backend/excel_ask.py")
def _p54():
    # 2x3 gegen 3x2 - dort zu drehen schreibt Werte an falsche Stellen.
    patch("backend/excel_ask.py",
          "            and min(zeilen, spalten) == 1 \\",
          "            and True \\")


@probe("Mass-Grund nennt die Spaltenbuchstaben nicht",
       "backend/excel_ask.py")
def _p55():
    patch("backend/excel_ask.py",
          '            rahmen = (" Der Bereich umfasst die %d Spalten %s bis %s."',
          '            rahmen = ("%.0s%.0s%.0s"')


@probe("Objekt-Fehler nur ins Protokoll, nicht in den Verlauf",
       "frontend/excel-addin/excel.js")
def _p17():
    patch("frontend/excel-addin/excel.js",
          "            if (erg.objFehler && erg.objFehler.length) {",
          "            if (false && erg.objFehler && erg.objFehler.length) {")


def main() -> int:
    # Rueckstand eines abgeschossenen Laufs zuerst zuruecknehmen.
    if MARKE.exists():
        print("Rueckstand eines frueheren Laufs gefunden – nehme ihn zurueck.")
        zurueck()
        MARKE.unlink()

    # REGEL: jede angefasste Datei muss gesichert werden.
    fehlend = {d for _, ds, _ in PROBEN for d in ds} - set(DATEIEN)
    if fehlend:
        print("ABBRUCH: nicht gesicherte Dateien in Proben: %s" % sorted(fehlend))
        return 2

    sichern()
    atexit.register(aufraeumen)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(1))

    # ── Basislauf: ohne gruene Basis ist keine Gegenprobe deutbar ──────────
    print("Basislauf …")
    basis = {}
    for art, pfad in WAECHTER:
        rc, aus = lauf(art, pfad)
        f = bilanz_fails(aus)
        basis[pfad] = f
        if f is None:
            print("ABBRUCH: %s liefert keine Bilanz" % pfad)
            print(aus[-2000:])
            return 2
        if f != 0:
            print("ABBRUCH: %s ist schon ohne Sabotage rot (%d FAIL)" % (pfad, f))
            print(aus[-2000:])
            return 2
    print("  Basis gruen.\n")

    beissen = 0
    for name, dateien, fn in PROBEN:
        zurueck()
        try:
            fn()
        except AssertionError as e:
            print("  ⚠ %-52s ANKER VERFEHLT (%s)" % (name, e))
            continue
        summe = 0
        abbruch = False
        for art, pfad in WAECHTER:
            rc, aus = lauf(art, pfad)
            f = bilanz_fails(aus)
            if f is None:
                abbruch = True
            else:
                summe += f
        if abbruch:
            print("  ⚠ %-52s BRICHT AB (keine Bilanz)" % name)
        elif summe > 0:
            print("  ✓ %-52s %d FAIL" % (name, summe))
            beissen += 1
        else:
            print("  ✗ %-52s BEISST NICHT" % name)

    zurueck()
    print("\n%d von %d Proben beissen." % (beissen, len(PROBEN)))
    return 0 if beissen == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
