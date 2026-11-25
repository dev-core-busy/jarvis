#!/usr/bin/env python3
"""Gegenprobe zu tests/test_kreisel_laufend_ui.js: beisst der Waechter?

Jede Probe sabotiert eine KOPIE von app.js, settings_idp.js, knowledge.js,
knowledge_sync.js oder i18n.js in einem Wegwerf-Verzeichnis; der Waechter laedt
sie ueber JARVIS_PRUEFLING_<NAME>. Die Repo-Dateien werden nie angefasst.

Erwartet je Probe: Exit 1 mit FAIL (Exit 2 = konnte nicht laufen, zaehlt nicht).
Vorab muss der Basislauf gruen sein.

Exit 0 = alle Proben beissen, 1 = mindestens eine stumm, 2 = konnte nicht laufen.
"""

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WAECHTER = REPO / "tests" / "test_kreisel_laufend_ui.js"
QUELLEN = {
    "APP": REPO / "frontend" / "js" / "app.js",
    "IDP": REPO / "frontend" / "js" / "settings_idp.js",
    "KNOW": REPO / "frontend" / "js" / "knowledge.js",
    "SYNC": REPO / "frontend" / "js" / "knowledge_sync.js",
    "I18N": REPO / "frontend" / "js" / "i18n.js",
}
SP = '<span class="jv-pkg-spin" aria-hidden="true"></span>'
# (Name, Datei, alt, neu, erwartete Trefferzahl von 'alt')
PROBEN = [
    ("LLM-Test: Knopf ohne Kreis", "APP",
     "btnTestProfile.innerHTML = '%s' + escapeHtml(window.t('common.testing'));" % SP,
     "btnTestProfile.textContent = window.t('common.testing');", 1),
    ("LLM-Test: Ergebniskasten ohne Kreis", "APP",
     "profileTestResult.innerHTML = '%s' + escapeHtml(window.t('profile.testing'));" % SP,
     "profileTestResult.textContent = window.t('profile.testing');", 1),
    ("Anmeldedienst-Test: nur Text", "IDP",
     "        laeuft('idp-msg', T('security.idp_test_laeuft',", "        meldung('idp-msg', T('security.idp_test_laeuft',", 1),
    ("Anmeldedienst-Test: Kreis ohne Klasse", "IDP", "        k.className = 'jv-pkg-spin';\n", "", 1),
    ("Verdichtung: Statuszeile ohne Kreis", "KNOW",
     "this._compactStatusLine(window.t('knowledge.compact.status_running'), 'var(--text-muted)', true);",
     "this._compactStatusLine(window.t('knowledge.compact.status_running'), 'var(--text-muted)');", 1),
    ("Verdichtung: Kreis bleibt bei jeder Meldung", "KNOW", "        if (laeuft) {\n", "        if (true) {\n", 1),
    ("Verdichtung: Knopf ohne Kreis", "KNOW", "            btn.insertBefore(k, btn.firstChild);\n", "", 1),
    ("Verdichtung: gezeichneter Knopf ohne Kreis", "KNOW",
     "${cs.running ? '%s' + window.t('knowledge.compact.running')" % SP,
     "${cs.running ? window.t('knowledge.compact.running')", 1),
    ("Synchronisation: Pille ohne Kreis", "SYNC",
     "${zustand === 'running' ? '%s' : ''}" % SP, "", 1),
    ("Synchronisation: Kreis auch ohne Lauf", "SYNC",
     "${zustand === 'running' ? '%s' : ''}" % SP, SP, 1),
    ("Text: Sanduhr zurueck", "I18N", "'Verdichtung läuft…'", "'⏳ Verdichtung läuft…'", 1),
]


def waechter(pfade):
    env = dict(os.environ, **{"JARVIS_PRUEFLING_" + k: str(v) for k, v in pfade.items()})
    p = subprocess.run(["timeout", "180", "node", str(WAECHTER)], env=env, capture_output=True, text=True)
    return p.returncode, sum(1 for z in p.stdout.splitlines() if z.startswith("  ✗"))


def main():
    for f in list(QUELLEN.values()) + [WAECHTER]:
        if not f.is_file():
            print("ABBRUCH: %s fehlt" % f)
            return 2
    if {p[1] for p in PROBEN} - set(QUELLEN):
        print("ABBRUCH: Probe auf eine Datei ohne Kopie")
        return 2
    original = {k: v.read_text(encoding="utf-8") for k, v in QUELLEN.items()}
    tmp = Path(tempfile.mkdtemp(prefix="gegen_kreisel_"))
    try:
        pfade = {k: tmp / (k + "_" + v.name) for k, v in QUELLEN.items()}

        def schreiben(wer, text):
            for k in QUELLEN:
                pfade[k].write_text(text if k == wer else original[k], encoding="utf-8")

        schreiben(None, "")
        rc, f = waechter(pfade)
        if rc != 0:
            print("ABBRUCH: Basislauf nicht gruen (rc=%s, FAIL=%s) – keine Probe deutbar" % (rc, f))
            return 2
        print("Basislauf gruen")
        stumm = 0
        for name, wer, alt, neu, n in PROBEN:
            text = original[wer]
            if text.count(alt) != n:
                print("  PROBE KAPUTT  %-46s Anker %d statt %d Treffer" % (name, text.count(alt), n))
                stumm += 1
                continue
            schreiben(wer, text.replace(alt, neu))
            rc, f = waechter(pfade)
            if rc == 1 and f > 0:
                print("  beisst        %-46s %d FAIL" % (name, f))
            else:
                print("  STUMM         %-46s rc=%s, %d FAIL" % (name, rc, f))
                stumm += 1
        print("ERGEBNIS: %d von %d Proben beissen" % (len(PROBEN) - stumm, len(PROBEN)))
        return 0 if stumm == 0 else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
