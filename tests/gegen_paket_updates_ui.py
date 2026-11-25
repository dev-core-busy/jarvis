#!/usr/bin/env python3
"""Gegenprobe zu tests/test_paket_updates_ui.js: beisst der Waechter?

Jede Probe sabotiert eine KOPIE von frontend/js/security_incidents.js; der
Waechter laedt sie ueber JARVIS_SECINC_PRUEFLING. Die Repo-Datei bleibt
unberuehrt.

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
MODUL = REPO / "frontend" / "js" / "security_incidents.js"
WAECHTER = REPO / "tests" / "test_paket_updates_ui.js"

PROBEN = [
    ("Neustart-Knopf auch fuer gesperrte Dienste", "                        if (x.neustartbar) {", "                        if (true) {", 1),
    ("Knopf ohne Kennung", "ue.setAttribute('data-kennung', z.kennung || '');", "ue.setAttribute('data-kennung', '');", 1),
    ("Pfad als HTML", "l += '<div><code>' + esc(e.pfad) + '</code>", "l += '<div><code>' + e.pfad + '</code>", 1),
    ("Einspielen immer aktiv", "if (ein) ein.disabled = !pakete.length;", "if (ein) ein.disabled = false;", 1),
    ("Uebernehmen-Knopf immer sichtbar", "            if (ue) ue.style.display = 'none';\n", "", 1),
    ("Updates beim Oeffnen nicht geladen", " this.loadCve(); this.loadUpdates(); },", " this.loadCve(); },", 1),
    ("Ladefehler laesst Einspielen aktiv", "                if (ein) ein.disabled = true;\n", "", 1),
    # Drehender Kreis bei laufenden Vorgaengen (gemeldet 2026-11-25)
    ("AIDE laeuft mit Statuspunkt statt Kreis", "h += _kreisel() + esc(T('security.aide_laeuft'",
     "h += _P('warn') + esc(T('security.aide_laeuft'", 1),
    ("Laufmeldung im Knopf ohne Kreis", "if (!o.symbol) btn.innerHTML = _kreisel() + esc(o.busy);",
     "if (!o.symbol) btn.textContent = o.busy;", 1),
    ("Laufmeldung im Ergebniskasten ohne Kreis", "out.innerHTML = _kreisel() + esc(o.busy);", "out.textContent = o.busy;", 1),
    ("Trockenlauf ohne Kreis", "if (box) box.innerHTML = _kreisel() + esc(T('security.unatt_dryrun_wait',",
     "if (box) box.innerHTML = esc(T('security.unatt_dryrun_wait',", 1),
    ("Kreis ohne die gemeinsame Gestalt", """return '<span class="jv-pkg-spin" aria-hidden="true"></span>';""",
     """return '<span class="jv-spin" aria-hidden="true"></span>';""", 1),
]
SETTINGS = REPO / "frontend" / "settings.html"
# Proben an der Lage im Markup (Container seit 2026-11-24)
PROBEN_HTML = [
    ("Container ohne eigenen Kopf (wieder in den System-Einstellungen)",
     'id="prof-sect-pakete-hdr"', 'id="prof-sect-pakete-hdr-alt"', 1),
    ("Titel ohne i18n-Schluessel", '<h3 data-i18n="profile.section_pakete">', "<h3>", 1),
    ("AIDE-Gruppe ohne eigene Ueberschrift", '<h4 class="tuning-group-title" data-i18n="security.section_aide">',
     '<h4 class="tuning-group-title">', 1),
]


def waechter(modul, settings=None):
    env = dict(os.environ, JARVIS_SECINC_PRUEFLING=str(modul))
    if settings:
        env["JARVIS_SETTINGS_PRUEFLING"] = str(settings)
    p = subprocess.run(["timeout", "90", "node", str(WAECHTER)], env=env, capture_output=True, text=True)
    return p.returncode, sum(1 for z in p.stdout.splitlines() if z.startswith("  ✗"))


def main():
    original = MODUL.read_text(encoding="utf-8")
    tmp = Path(tempfile.mkdtemp(prefix="gegen_paket_updates_ui_"))
    try:
        basis = tmp / "basis.js"
        basis.write_text(original, encoding="utf-8")
        rc, f = waechter(basis)
        if rc != 0:
            print("ABBRUCH: Basislauf nicht gruen (Exit %d, %d FAIL) – keine Probe deutbar" % (rc, f))
            return 2
        print("Basislauf gruen")
        stumm = 0
        for name, alt, neu, n in PROBEN:
            if original.count(alt) != n:
                print("  PROBE KAPUTT  %-42s Anker %d statt %d Treffer" % (name, original.count(alt), n))
                stumm += 1
                continue
            kopie = tmp / "probe.js"
            kopie.write_text(original.replace(alt, neu), encoding="utf-8")
            rc, f = waechter(kopie)
            if rc == 1 and f > 0:
                print("  beisst        %-42s %d FAIL" % (name, f))
            else:
                print("  STUMM         %-42s Exit %d, %d FAIL" % (name, rc, f))
                stumm += 1
        html = SETTINGS.read_text(encoding="utf-8")
        for name, alt, neu, n in PROBEN_HTML:
            if html.count(alt) != n:
                print("  PROBE KAPUTT  %-42s Anker %d statt %d Treffer" % (name, html.count(alt), n))
                stumm += 1
                continue
            kopie = tmp / "settings.html"
            kopie.write_text(html.replace(alt, neu), encoding="utf-8")
            rc, f = waechter(basis, kopie)
            if rc == 1 and f > 0:
                print("  beisst        %-42s %d FAIL" % (name, f))
            else:
                print("  STUMM         %-42s Exit %d, %d FAIL" % (name, rc, f))
                stumm += 1
        alle = len(PROBEN) + len(PROBEN_HTML)
        print("ERGEBNIS: %d von %d Proben beissen" % (alle - stumm, alle))
        return 0 if stumm == 0 else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
