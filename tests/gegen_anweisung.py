#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gegenproben zu "Eigene Anweisung" im Dialog Prompt optimieren.

Jede Probe dreht GENAU EINE Zusage zurueck und misst, ob die Waechter das
melden. Eine Gegenprobe, die nicht beisst, ist ein Testmangel - kein Beweis.

⚠ SICHERUNG AUF PLATTE + LAUFMARKE. Wird dieser Harness abgeschossen, bleibt
der Arbeitsbaum sabotiert zurueck; der naechste Start nimmt das dann selbst
zurueck. Die Marke wird beim geordneten Ende abgeraeumt - ohne sie stellte ein
spaeterer Lauf einen VERALTETEN Stand her und machte fertige Arbeit zunichte.
"""
import atexit
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ABLAGE = Path.home() / ".gegen-anweisung"
MARKE = ABLAGE / ".laeuft"

DATEIEN = [
    "backend/wissen_aufraeumen.py",
    "backend/main.py",
    "frontend/js/knowledge.js",
    "frontend/js/i18n.js",
    "frontend/css/style.css",
    # ⚠ AUCH DIE TESTDATEIEN: eine Probe sabotiert einen Waechter, um zu
    # zeigen, dass er die Eigenschaft und nicht die Schreibweise prueft.
    # Fehlte sie hier, bliebe die Sabotage stehen und der naechste Lauf meldete
    # FAIL, die es im Code nicht gibt (im Projekt zweimal passiert).
    "tests/test_wissen_aufraeumen.py",
    "tests/test_aufraeumen_ui.js",
]


def sichern():
    ABLAGE.mkdir(mode=0o700, exist_ok=True)
    for rel in DATEIEN:
        ziel = ABLAGE / rel.replace("/", "__")
        shutil.copy2(REPO / rel, ziel)
    MARKE.write_text("1", encoding="utf-8")


def zurueck():
    for rel in DATEIEN:
        q = ABLAGE / rel.replace("/", "__")
        if q.is_file():
            shutil.copy2(q, REPO / rel)


def aufraeumen():
    zurueck()
    if MARKE.exists():
        MARKE.unlink()


# Rueckstand eines abgeschossenen Laufs zuerst zuruecknehmen.
if MARKE.exists():
    print("Rueckstand eines frueheren Laufs gefunden - wird zurueckgenommen.")
    zurueck()
    MARKE.unlink()

WAECHTER = {
    "py": [sys.executable, str(REPO / "tests/test_wissen_aufraeumen.py")],
    "js": ["node", str(REPO / "tests/test_aufraeumen_ui.js")],
}


def lauf(welcher):
    """(FAIL-Zahl, bilanz_da). Ohne Bilanzzeile gilt der Lauf als ABGEBROCHEN -
    ein abgebrochener Lauf ist von einem bestandenen nicht zu unterscheiden."""
    r = subprocess.run(WAECHTER[welcher], capture_output=True, text=True,
                       cwd=str(REPO), timeout=600)
    aus = r.stdout + r.stderr
    fails, bilanz = 0, False
    for z in aus.splitlines():
        if "Ergebnis:" in z:
            bilanz = True
            import re
            m = re.search(r"(\d+)\s+FAIL", z)
            if m:
                fails = int(m.group(1))
    return fails, bilanz


def patch(rel, alt, neu, anzahl=1):
    d = REPO / rel
    s = d.read_text(encoding="utf-8")
    assert s.count(alt) >= anzahl, f"ANKER VERFEHLT in {rel}: {alt[:60]!r}"
    d.write_text(s.replace(alt, neu, anzahl), encoding="utf-8")


PROBEN = []


def probe(name, welcher, fn):
    PROBEN.append((name, welcher, fn))


# ── Backend ───────────────────────────────────────────────────────────────
probe("Anweisung nicht an _auftrag_bauen durchgereicht", "py", lambda: patch(
    "backend/wissen_aufraeumen.py",
    "        auftrag = _auftrag_bauen(art, alt, kennung, konflikthinweis=khinweis,\n"
    "                                 anweisung=anweisung)",
    "        auftrag = _auftrag_bauen(art, alt, kennung, konflikthinweis=khinweis)"))

probe("blockweiser Weg bekommt sie nicht", "py", lambda: patch(
    "backend/wissen_aufraeumen.py",
    "                                 teilhinweis=True, anweisung=anweisung)",
    "                                 teilhinweis=True)"))

probe("Aufraeum-Vorspann gilt auch mit Anweisung", "py", lambda: patch(
    "backend/wissen_aufraeumen.py",
    "    vorspann = _VORSPANN_ANWEISUNG if anweisung else _VORSPANN",
    "    vorspann = _VORSPANN"))

probe("Anweisung wird entschaerft wie Fremdtext", "py", lambda: patch(
    "backend/wissen_aufraeumen.py",
    "f\"BEGINN ANWEISUNG-{kennung}\\n{text.strip()}\\n\"",
    "f\"BEGINN ANWEISUNG-{kennung}\\n{_entschaerfen(text.strip())}\\n\""))

probe("Anweisung steht HINTER dem Dateiinhalt", "py", lambda: patch(
    "backend/wissen_aufraeumen.py",
    'f"{vorspann}\\n{aufgabe}\\n{teil}{konflikthinweis}{eigen}\\n"',
    'f"{vorspann}\\n{aufgabe}\\n{teil}{konflikthinweis}\\n"'))

probe("Deckel fuer die Anweisung entfernt", "py", lambda: patch(
    "backend/wissen_aufraeumen.py",
    "    if len(anweisung) > MAX_ANWEISUNG:",
    "    if False:"))

probe("Schluesselpaar-Hinweis auch im Anweisungs-Modus", "py", lambda: patch(
    "backend/wissen_aufraeumen.py",
    '    if art == "gedaechtnis" and not anweisung:',
    '    if art == "gedaechtnis":'))

probe("Antwortformat bleibt fest (Aufraeum-Schubladen)", "py", lambda: patch(
    "backend/wissen_aufraeumen.py",
    "    fundart = ('\"<Schlagwort>\"' if anweisung\n"
    "               else '\"dopplung|widerspruch|straffung\"')",
    "    fundart = '\"dopplung|widerspruch|straffung\"'"))

probe("neu_objekt kehrt zurueck", "py", lambda: patch(
    "backend/wissen_aufraeumen.py",
    '"⚠ Das Ergebnis ist wieder ein JSON-OBJEKT und steht ROH zwischen den "',
    '"⚠ Gib das Ergebnis im Feld neu_objekt zurueck. "'))

probe("Endpunkt reicht die Anweisung nicht durch", "py", lambda: patch(
    "backend/main.py",
    "    erg = await _wa.analysiere(schluessel, user=user, konflikte=konflikte or None,\n"
    "                               anweisung=anweisung)",
    "    erg = await _wa.analysiere(schluessel, user=user, konflikte=konflikte or None)"))

probe("Lauf mit Anweisung steht nicht im Audit", "py", lambda: patch(
    "backend/main.py",
    '            _al.log_tool(user, "knowledge_cleanup_anweisung",',
    '            _al.log_tool(user, "knowledge_cleanup_x",'))

# ⚠ HIER STAND EINE PROBE, DIE NICHT BEISSEN KONNTE: sie schwaechte die
# neu_objekt-Pruefung zu "... and True". Dass ein WAECHTER geschwaecht wurde,
# kann nur ein Waechter ueber den Waechter melden - den gibt es nicht, und er
# waere hier auch nicht angemessen. Eine schlecht platzierte Gegenprobe gehoert
# korrigiert, nicht als "zahnloser Waechter" ausgegeben.
#
# Was sich WIRKLICH pruefen laesst: liest der Waechter die kommentarfreie
# Fassung? Faellt der Filter aus, findet er den alten Feldnamen in der
# Begruendung wieder - und meldet einen Fehler, den es im Code nicht gibt.
probe("der Kommentar-Filter des Waechters faellt aus", "py", lambda: patch(
    "tests/test_wissen_aufraeumen.py",
    "    except Exception:                                         # noqa: BLE001\n"
    "        return quelle          # fail-open: lieber zu streng als blind\n"
    '    return "\\n".join(raus)',
    "    except Exception:                                         # noqa: BLE001\n"
    "        return quelle          # fail-open: lieber zu streng als blind\n"
    "    return quelle"))

probe("Widerspruch Kopf/Block wird wieder verschwiegen", "py", lambda: patch(
    "backend/wissen_aufraeumen.py",
    "        if gemeldet and not geaendert:",
    "        if False:"))

# ── Client ────────────────────────────────────────────────────────────────
probe("Eingabefeld wird nicht gezeichnet", "js", lambda: patch(
    "frontend/js/knowledge.js",
    '            <textarea id="kb-cl-anw-text" class="kb-cl-anw-text" rows="3" spellcheck="false"',
    '            <textarea id="kb-cl-anw-text-x" class="kb-cl-anw-text" rows="3" spellcheck="false"'))

probe("Knopf ist nicht gesperrt, solange das Feld leer ist", "js", lambda: patch(
    "frontend/js/knowledge.js",
    "            knopf.disabled = leer;",
    "            knopf.disabled = false;"))

probe("die Verdrahtung wird gar nicht gerufen", "js", lambda: patch(
    "frontend/js/knowledge.js",
    "        this._cleanupAnweisungVerdrahten();",
    "        // this._cleanupAnweisungVerdrahten();"))

probe("Analysieren liest das Feld selbst aus", "js", lambda: patch(
    "frontend/js/knowledge.js",
    "    async cleanupAnalysieren(anweisung = '') {",
    "    async cleanupAnalysieren(anweisung = (document.getElementById('kb-cl-anw-text')||{}).value || '') {"))

probe("Anweisung geht nicht im Rumpf mit", "js", lambda: patch(
    "frontend/js/knowledge.js",
    "body: JSON.stringify({ dateien: teil, anweisung })",
    "body: JSON.stringify({ dateien: teil })"))

probe("zweiter Knopf bleibt waehrend des Laufs bedienbar", "js", lambda: patch(
    "frontend/js/knowledge.js",
    "        if (knopf2) { knopf2.disabled = true; }",
    "        if (knopf2) { knopf2.disabled = false; }"))

# ⚠ DIE SABOTAGE MUSS DAS ECHO WIRKLICH ENTFERNEN. Ein blosses Umbenennen der
# Klasse liess den TEXT stehen - die Pruefung "die Anweisung steht ueber dem
# Ergebnis" blieb damit gruen, und es sah nach einem zahnlosen Waechter aus.
# Nicht der Waechter war stumpf, die Probe hat ihr Ziel verfehlt.
probe("Echo der Anweisung wird nicht gezeigt", "js", lambda: patch(
    "frontend/js/knowledge.js",
    "        if (anweisung) {\n            html += `<div class=\"kb-cl-anw-echo\">",
    "        if (false) {\n            html += `<div class=\"kb-cl-anw-echo\">"))

probe("Echo verliert seine Klasse (das CSS greift dann nicht)", "js", lambda: patch(
    "frontend/js/knowledge.js",
    'html += `<div class="kb-cl-anw-echo"><span class="kb-cl-anw-echo-titel">${',
    'html += `<div><span class="kb-cl-anw-echo-titel">${'))

probe("Echo wird nicht maskiert", "js", lambda: patch(
    "frontend/js/knowledge.js",
    "                 + `<span>${this._escHtml(anweisung)}</span></div>`;",
    "                 + `<span>${anweisung}</span></div>`;"))

probe("Begruendung bei 'nichts geaendert' faellt wieder weg", "js", lambda: patch(
    "frontend/js/knowledge.js",
    "                    ${r.begruendung ? `<p class=\"kb-cl-grund\">${this._escHtml(r.begruendung)}</p>` : ''}\n"
    "                    ${fundeU ? `<ul class=\"kb-cl-funde\">${fundeU}</ul>` : ''}\n"
    "                    </div>`;",
    "                    </div>`;"))

probe("kein Weg zurueck zur Auswahl", "js", lambda: patch(
    "frontend/js/knowledge.js",
    '            <button class="btn-secondary" id="kb-cl-zurueck"',
    '            <button class="btn-secondary" id="kb-cl-zurueck-x"'))

probe("box-sizing am Eingabefeld entfernt", "js", lambda: patch(
    "frontend/css/style.css",
    "    box-sizing: border-box;\n    min-height: 62px;",
    "    min-height: 62px;"))

probe("min-width am Echo entfernt", "js", lambda: patch(
    "frontend/css/style.css",
    "    min-width: 0; overflow-wrap: anywhere;",
    "    overflow-wrap: anywhere;"))

probe("englischer Text fehlt", "js", lambda: patch(
    "frontend/js/i18n.js",
    "        'knowledge.cleanup.anw_echo':     'Your instruction:',\n",
    ""))


def main():
    sichern()
    atexit.register(aufraeumen)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *a: sys.exit(2))

    # ⚠ REGEL: jede Datei, die eine Probe anfasst, MUSS gesichert sein.
    import inspect
    for name, _w, fn in PROBEN:
        try:
            q = inspect.getsource(fn)
        except Exception:                                     # noqa: BLE001
            continue
        for rel in ("backend/", "frontend/", "tests/"):
            for stueck in q.split('"'):
                if stueck.startswith(rel) and stueck not in DATEIEN:
                    sys.exit(f"ABBRUCH: '{stueck}' wird sabotiert, steht aber "
                             f"nicht in DATEIEN (Sicherung)")

    basis = {}
    for w in ("py", "js"):
        f, b = lauf(w)
        basis[w] = f
        print(f"Basis {w}: {f} FAIL, Bilanz={b}")
        if f or not b:
            sys.exit("ABBRUCH: ohne gruene Basis ist keine Gegenprobe deutbar.")

    beisst = 0
    for name, w, fn in PROBEN:
        zurueck()
        try:
            fn()
        except AssertionError as e:
            print(f"  \033[31m✗\033[0m {name}: {e}")
            continue
        f, b = lauf(w)
        gut = (f > 0) or (not b)
        beisst += 1 if gut else 0
        marke = "\033[32m✓\033[0m" if gut else "\033[31m✗ BEISST NICHT\033[0m"
        print(f"  {marke} {name} -> {f} FAIL" + ("" if b else " (ABGEBROCHEN)"))
    zurueck()

    # Nach dem Wiederherstellen: ist der Baum wirklich sauber?
    f, b = lauf("py")
    f2, b2 = lauf("js")
    print(f"\nNach dem Zuruecknehmen: py {f} FAIL, js {f2} FAIL")
    print(f"\n\033[1m{beisst} von {len(PROBEN)} Gegenproben beissen\033[0m")
    sys.exit(0 if (beisst == len(PROBEN) and f == 0 and f2 == 0) else 1)


main()
