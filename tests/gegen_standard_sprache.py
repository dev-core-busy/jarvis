#!/usr/bin/env python3
"""Gegenprobe zu test_standard_sprache.py und test_standard_sprache_ui.js.

Jede Probe baut EINE Rueckentwicklung in eine KOPIE (sprache.py, main.py oder
i18n.js – der Arbeitsbaum wird nicht angefasst) und laesst den zustaendigen
Waechter ueber JARVIS_PRUEFLING_* gegen sie laufen; erwartet wird mindestens
ein FAIL (Exit 1). Vorher gruene Basislaeufe gegen die Originale.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
# Schreibschutz: kein Zurueckschreiben ueber fremde Aenderungen (Pflicht fuer
# jeden Harness). Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / "tests" / "test_standard_sprache.py"
JS = ROOT / "tests" / "test_standard_sprache_ui.js"
DATEIEN = {
    "sprache": (ROOT / "backend" / "sprache.py", "JARVIS_PRUEFLING_SPRACHE", PY),
    "main": (ROOT / "backend" / "main.py", "JARVIS_PRUEFLING_MAIN", PY),
    "i18n": (ROOT / "frontend" / "js" / "i18n.js", "JARVIS_PRUEFLING_I18N", JS),
}

PROBEN = [
    ("sprache", "Vorgabe faellt in aus_anfrage weg",
     'return normieren(request.cookies.get(COOKIE)) or vorgabe() or "de"',
     'return normieren(request.cookies.get(COOKIE)) or "de"'),
    ("sprache", "Vorgabe auf oberster Ebene gelesen",
     'extra = json.loads(EINSTELLUNGEN.read_text(encoding="utf-8")).get("extra") or {}',
     'extra = json.loads(EINSTELLUNGEN.read_text(encoding="utf-8")) or {}'),
    ("sprache", "Vorgabe ungeprueft (normieren fehlt)",
     'wert = normieren(extra.get("standard_sprache")) if isinstance(extra, dict) else ""',
     'wert = str(extra.get("standard_sprache") or "") if isinstance(extra, dict) else ""'),
    ("sprache", "Cache ohne Aenderungszeit",
     '    if _vorgabe_cache.get("stempel") == stempel:\n        return _vorgabe_cache["wert"]',
     '    if "wert" in _vorgabe_cache:\n        return _vorgabe_cache["wert"]'),
    ("sprache", "eigene Wahl wird ueberschrieben",
     '        if normieren(request.cookies.get(COOKIE)):\n            return ""',
     '        pass'),
    ("main", "Middleware setzt kein Cookie",
     '            response.set_cookie(_sprache.COOKIE, vg,',
     '            (lambda *a, **k: None)(_sprache.COOKIE, vg,'),
    ("main", "Cookie HttpOnly (Skript kann es nicht lesen)",
     'secure=request.url.scheme == "https", httponly=False)',
     'secure=request.url.scheme == "https", httponly=True)'),
    ("main", "Cookie auf jeder Antwort statt nur HTML",
     'if vg and response.headers.get("content-type", "").startswith("text/html"):',
     'if vg:'),
    ("i18n", "i18n.js ignoriert das Cookie (Stand vor dem Fix)",
     "window._lang = localStorage.getItem('jarvis_lang') || _sprachAusCookie() || 'de';",
     "window._lang = localStorage.getItem('jarvis_lang') || 'de';"),
    ("i18n", "Cookie vor der eigenen Wahl",
     "window._lang = localStorage.getItem('jarvis_lang') || _sprachAusCookie() || 'de';",
     "window._lang = _sprachAusCookie() || localStorage.getItem('jarvis_lang') || 'de';"),
    ("i18n", "jede Sprache aus dem Cookie angenommen",
     "return (m && ['de', 'en', 'fr', 'nl'].indexOf(m[1]) >= 0) ? m[1] : null;",
     "return m ? m[1] : null;"),
    ("i18n", "fremdes Cookie zaehlt mit",
     "var m = document.cookie.match(/(?:^|;\\s*)jarvis_lang=([a-z]{2})(?:;|$)/);",
     "var m = document.cookie.match(/=([a-z]{2})(?:;|$)/);"),
]


def lauf(waechter, env_name=None, pfad=None):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    if env_name:
        env[env_name] = str(pfad)
    befehl = ["node", str(waechter)] if waechter.suffix == ".js" else [sys.executable, str(waechter)]
    r = subprocess.run(befehl, capture_output=True, text=True, timeout=300, env=env)
    return r.returncode, r.stdout


def main():
    for w in (PY, JS):
        rc, aus = lauf(w)
        if rc != 0:
            print("ABBRUCH: Basislauf %s nicht gruen (rc=%d)\n%s" % (w.name, rc, aus[-600:]))
            return 2
    print("Basislaeufe gruen.\n")
    beissen = 0
    with tempfile.TemporaryDirectory(prefix="gegen_std_sprache_") as d:
        for art, name, alt, neu in PROBEN:
            orig, env_name, waechter = DATEIEN[art]
            text = orig.read_text(encoding="utf-8")
            if text.count(alt) != 1:
                print("  ???  %s – Anker %dx gefunden" % (name, text.count(alt)))
                continue
            kopie = Path(d) / orig.name
            kopie.write_text(text.replace(alt, neu, 1), encoding="utf-8")
            rc, aus = lauf(waechter, env_name, kopie)
            fails = aus.count("  FAIL ")
            if rc == 1 and fails:
                beissen += 1
                print("  BISS %-50s %d FAIL" % (name, fails))
            else:
                print("  ---- %-50s beisst NICHT (rc=%d)" % (name, rc))
    print("\n%d/%d Proben beissen" % (beissen, len(PROBEN)))
    return 0 if beissen == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
