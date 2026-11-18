#!/usr/bin/env python3
"""Gegenprobe zu tests/test_zugang_probe_ui.js (Fachprobe im Zugangs-Container).

EINE GEGENPROBE, DIE NICHT BEISST, IST EIN TESTMANGEL – KEIN BEWEIS. Jede Probe
dreht GENAU EINE Zusage zurueck und zaehlt die FAIL des Waechters.

⚠ DER ARBEITSBAUM WIRD NICHT ANGEFASST. Sabotiert werden KOPIEN in einem
Wegwerf-Verzeichnis; der Waechter liest sie ueber die Umgebungsvariablen
PROBE_*_JS / PROBE_*_HTML / PROBE_I18N / PROBE_JA_CSS. Damit kann kein Rueckstand
liegen bleiben – die Lehre aus dem Vorfall, bei dem ein abgeschossener
Gegenproben-Harness eine sabotierte Datei im Baum hinterliess (Register).

OHNE GRUENEN BASISLAUF IST KEINE GEGENPROBE DEUTBAR: der Lauf beginnt mit dem
unveraenderten Stand und bricht mit Exit 2 ab, wenn der nicht gruen ist.

Jede Probe prueft mit einer TREFFERKONTROLLE, dass ihre Ersetzung ueberhaupt
gegriffen hat – sonst saehe eine wirkungslose Sabotage wie ein zahnloser
Waechter aus.

Aufruf: python3 tests/gegen_zugang_probe.py
"""

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_zugang_probe_ui.js"

# Kennung -> (Quelldatei im Repo, Name der Umgebungsvariablen)
DATEIEN = {
    "jira_js": ("frontend/js/jira_addon.js", "PROBE_JIRA_JS"),
    "conf_js": ("frontend/js/confluence_addon.js", "PROBE_CONF_JS"),
    "sap_js": ("frontend/js/sap_portal.js", "PROBE_SAP_JS"),
    "vemas_js": ("frontend/js/vemas_portal.js", "PROBE_VEMAS_JS"),
    "jira_html": ("frontend/jira_addon.html", "PROBE_JIRA_HTML"),
    "conf_html": ("frontend/confluence_addon.html", "PROBE_CONF_HTML"),
    "sap_html": ("frontend/sap.html", "PROBE_SAP_HTML"),
    "vemas_html": ("frontend/vemas.html", "PROBE_VEMAS_HTML"),
    "i18n": ("frontend/js/i18n.js", "PROBE_I18N"),
    "ja_css": ("frontend/css/jira_addon.css", "PROBE_JA_CSS"),
}

# (Beschreibung, Kennung, alt, neu)  –  `alt` muss GENAU EINMAL vorkommen.
PROBEN = [
    ("Jira: Probe-Knopf nicht verdrahtet", "jira_js",
     "        if (pb) pb.addEventListener('click', probeLaufen);",
     "        if (pb) { /* sabotiert: kein Zuhoerer */ }"),

    ("Jira: Leerfall meldet nichts (stumme Null)", "jira_js",
     "                probeMeld(T('jaddon.probe_leer',",
     "                probeMeld('', 'x') || probeMeld2(T('jaddon.probe_leer',"),

    ("Jira: Doppelklick-Schranke raus", "jira_js",
     "        if (_probeLaeuft) return;          // Doppelklick: ein Lauf genuegt\n"
     "        var btn = $('ja-acc-probe');",
     "        var btn = $('ja-acc-probe');"),

    ("Jira: Fremdtext wird nicht maskiert", "jira_js",
     "    function probeEsc(s) {\n"
     "        return String(s == null ? '' : s).replace(/[&<>\"]/g, function (c) {",
     "    function probeEsc(s) {\n"
     "        if (s !== undefined) return String(s == null ? '' : s);\n"
     "        return String(s == null ? '' : s).replace(/[&<>\"]/g, function (c) {"),

    ("Jira: kein Deckel in der Anfrage", "jira_js",
     "                                + encodeURIComponent('ORDER BY updated DESC') + '&limit=5',",
     "                                + encodeURIComponent('ORDER BY updated DESC'),"),

    ("Jira: Knopf steht VOR dem Speichern-Knopf", "jira_html",
     '            <div class="ja-dl">\n'
     '                <button type="button" class="ja-btn ja-btn-haupt" id="ja-acc-save"',
     '            <div class="ja-probe-zeile">\n'
     '                <button type="button" class="ja-btn" id="ja-acc-probe"\n'
     '                        data-i18n="jaddon.probe_btn">Sichtbare Tickets anzeigen</button>\n'
     '            </div>\n'
     '            <div class="ja-dl">\n'
     '                <button type="button" class="ja-btn ja-btn-haupt" id="ja-acc-save"'),

    ("Confluence: Serverfehler wird verschluckt", "conf_js",
     "                throw new Error((d && (d.error || d.detail))\n"
     "                                || T('caddon.probe_fail', 'Abfrage fehlgeschlagen.'));",
     "                throw new Error(T('caddon.probe_fail', 'Abfrage fehlgeschlagen.'));"),

    ("Confluence: Kasten traegt kein hidden", "conf_html",
     '            <div class="ja-probe" id="ca-acc-probe-out" hidden></div>',
     '            <div class="ja-probe" id="ca-acc-probe-out"></div>'),

    ("SAP: probeZiel liest das Pulldown statt den Status", "sap_js",
     "        var s = _status || {};\n"
     "        if (s.odata) return { art: 'odata', pfad: '/api/sap/odata/services' };\n"
     "        if (s.hana) return { art: 'hana', pfad: '/api/sap/tables?limit=' + PROBE_MAX };\n"
     "        if (s.rfc) return { art: 'rfc', pfad: '' };",
     "        var tsel = $('sp-acc-type') ? $('sp-acc-type').value : '';\n"
     "        if (tsel === 'odata') return { art: 'odata', pfad: '/api/sap/odata/services' };\n"
     "        if (tsel === 'hana') return { art: 'hana', pfad: '/api/sap/tables?limit=' + PROBE_MAX };\n"
     "        if (tsel === 'rfc') return { art: 'rfc', pfad: '' };"),

    ("SAP: Sperre fuer RFC/ohne Zugang raus", "sap_js",
     "        var z = probeZiel();\n"
     "        if (z.art === 'rfc') {",
     "        var z = probeZiel();\n"
     "        if (false) {"),

    ("SAP: Sperrgrund ohne Text", "sap_js",
     "            b.title = T('sap.probe_rfc',\n"
     "                'Für RFC gibt es keine Katalog-Abfrage. „Verbindung testen\" prüft den Zugang.');",
     "            b.title = '';"),

    ("SAP: Kasten mit eigenem display (hidden wirkungslos)", "sap_html",
     "        .sp-probe { background: var(--bg-secondary); border: 1px solid var(--border);",
     "        .sp-probe { display: block; background: var(--bg-secondary); border: 1px solid var(--border);"),

    ("VEMAS: fehlende Ressourcen gelten als Fehlschlag", "vemas_js",
     "                probeMeld(T('vemas.probe_keine_res',",
     "                probeMeld(T('vemas.probe_fail', 'Abfrage fehlgeschlagen.')) || probeMeld2(T('vemas.probe_keine_res',"),

    ("VEMAS: kein Deckel (top) in der Anfrage", "vemas_js",
     "                                 + '&top=' + PROBE_TOP, { headers: authHeaders() });",
     "                                 , { headers: authHeaders() });"),

    ("VEMAS: Knopf ohne data-i18n", "vemas_html",
     '                    <button type="button" class="vm-hist-btn" id="vm-acc-probe"\n'
     '                            data-i18n="vemas.probe_btn">Sichtbare Daten abfragen</button>',
     '                    <button type="button" class="vm-hist-btn" id="vm-acc-probe">Sichtbare Daten abfragen</button>'),

    ("i18n: ein englischer Schluessel fehlt", "i18n",
     "        'sap.probe_head_hana': 'Tables and views in the schema:',\n",
     ""),

    ("CSS: .ja-probe[hidden] raus", "ja_css",
     ".ja-probe[hidden] { display: none; }\n",
     ""),
]


def basislauf(umgebung):
    """Der unveraenderte Stand MUSS gruen sein – sonst ist nichts deutbar."""
    r = subprocess.run([shutil.which("node") or "node", str(WAECHTER)],
                       capture_output=True, text=True, env=umgebung, timeout=300)
    letzte = [z for z in r.stdout.splitlines() if z.startswith("Ergebnis:")]
    return r.returncode, (letzte[-1] if letzte else ""), r.stdout


def fails(ausgabe):
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", ausgabe)
    return int(m.group(2)) if m else -1


def main():
    node = shutil.which("node")
    if not node:
        print("ABBRUCH: node nicht gefunden – „konnte nicht laufen\" ist kein Bestanden.")
        return 2
    if not WAECHTER.exists():
        print("ABBRUCH: %s fehlt." % WAECHTER)
        return 2

    arbeit = Path(tempfile.mkdtemp(prefix="gegen-zugang-probe-"))
    try:
        # Unveraenderte Kopien + Umgebung, die auf sie zeigt.
        basis_env = dict(os.environ)
        for kennung, (rel, var) in DATEIEN.items():
            quelle = ROOT / rel
            if not quelle.exists():
                print("ABBRUCH: %s fehlt." % rel)
                return 2
            ziel = arbeit / (kennung + "_" + quelle.name)
            shutil.copy2(quelle, ziel)
            basis_env[var] = str(ziel)

        code, bilanz, roh = basislauf(basis_env)
        if code != 0 or fails(roh) != 0:
            print("ABBRUCH: Basislauf nicht gruen (%s, Exit %d)." % (bilanz or "keine Bilanz", code))
            print(roh[-2000:])
            return 2
        print("Basislauf gruen: %s\n" % bilanz)

        # Regel statt gepflegter Liste: jede Probe muss eine bekannte Datei
        # nennen – ein Tippfehler darf nicht als "beisst nicht" durchgehen.
        unbekannt = {k for _, k, _, _ in PROBEN} - set(DATEIEN)
        if unbekannt:
            print("ABBRUCH: Proben nennen unbekannte Dateien: %s" % ", ".join(sorted(unbekannt)))
            return 2

        beissen = 0
        for nr, (titel, kennung, alt, neu) in enumerate(PROBEN, 1):
            rel, var = DATEIEN[kennung]
            orig = (ROOT / rel).read_text(encoding="utf-8")
            if orig.count(alt) != 1:
                print("%2d. %-55s ANKER TRIFFT NICHT (%dx) – Probenmangel"
                      % (nr, titel, orig.count(alt)))
                continue
            ziel = arbeit / (kennung + "_sab_" + Path(rel).name)
            ziel.write_text(orig.replace(alt, neu), encoding="utf-8")
            env = dict(basis_env)
            env[var] = str(ziel)
            r = subprocess.run([node, str(WAECHTER)], capture_output=True, text=True,
                               env=env, timeout=300)
            n = fails(r.stdout)
            if n > 0 and r.returncode == 1:
                beissen += 1
                print("%2d. %-55s BEISST (%d FAIL)" % (nr, titel, n))
            elif n == 0:
                print("%2d. %-55s STUMM (0 FAIL) ⚠" % (nr, titel))
            else:
                # Exit 2 / keine Bilanz: der Waechter ist abgebrochen. Das ist
                # KEIN Biss – ein abgebrochener Lauf ist von einem bestandenen
                # nicht zu unterscheiden (Register).
                print("%2d. %-55s ABGEBROCHEN (Exit %d) ⚠" % (nr, titel, r.returncode))
                print(r.stdout[-800:] or r.stderr[-800:])
        print("\nErgebnis: %d von %d Proben beissen" % (beissen, len(PROBEN)))
        return 0 if beissen == len(PROBEN) else 1
    finally:
        shutil.rmtree(arbeit, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
