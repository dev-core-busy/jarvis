#!/usr/bin/env python3
"""Gegenprobe zu tests/test_csp_h4.py und tests/test_csp_h4_frontend.py: beissen die Waechter?

Jede Probe dreht EINEN Fix zurueck (Ersetzung eines exakten Textstuecks), laesst
den zugehoerigen Waechter laufen und erwartet mindestens einen FAIL. Vorher
gruener Basislauf beider Waechter, danach Byte-Gleichheit aller Dateien per md5.

⚠ Veraendert Dateien im Arbeitsbaum fuer die Dauer einer Probe. Nicht parallel
zu anderen Arbeiten an denselben Dateien laufen lassen.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACK = ROOT / "tests" / "test_csp_h4.py"
FRONT = ROOT / "tests" / "test_csp_h4_frontend.py"
CSP = "backend/csp.py"
MAIN = "backend/main.py"
LR = "backend/log_retention.py"
CHAT = "frontend/chat.html"
I18N = "frontend/js/i18n.js"

PROBEN = [
    # (Name, Waechter, Datei, alt, neu)
    ("script-src mit 'unsafe-inline'", BACK, CSP,
     '''    skript = "'self'" + (" " + _OFFICE_JS if addin else "")\n''',
     '''    skript = "'self' 'unsafe-inline'" + (" " + _OFFICE_JS if addin else "")\n'''),
    ("office.js auf allen Seiten", BACK, CSP,
     '''    skript = "'self'" + (" " + _OFFICE_JS if addin else "")\n''',
     '''    skript = "'self' " + _OFFICE_JS\n'''),
    ("Office-Rahmen auf allen Seiten", BACK, CSP,
     '''        "frame-src 'self' blob: data:" + (" " + _OFFICE_RAHMEN if addin else ""),\n''',
     '''        "frame-src 'self' blob: data: " + _OFFICE_RAHMEN,\n'''),
    ("Vorgabe zurueck auf melden", BACK, CSP,
     'MODUS_VORGABE = "erzwingen"\n',
     'MODUS_VORGABE = "melden"\n'),
    ("unbekannter Modus schaltet ab", BACK, CSP,
     "    return wert if wert in MODI else MODUS_VORGABE\n",
     '    return wert if wert in MODI else "aus"\n'),
    ("erzwingen setzt nur Report-Only", BACK, CSP,
     '    name = "Content-Security-Policy" if m == "erzwingen" else "Content-Security-Policy-Report-Only"\n',
     '    name = "Content-Security-Policy-Report-Only"\n'),
    ("Host ungeprueft in die Kopfzeile", BACK, CSP,
     "    if host and _HOST_OK.match(host):\n",
     "    if host:\n"),
    ("Ausnahme fuer alle Pfade", BACK, CSP,
     '_AUSGENOMMEN = ("/novnc/",)\n',
     '_AUSGENOMMEN = ("/",)\n'),
    ("Query/Token bleibt in der Meldung", BACK, CSP,
     '    for z in ("?", "#"):\n',
     '    for z in ():\n'),
    ("kein Tages-Dedupe", BACK, CSP,
     "                if _gesehen_tag.get(schluessel) == tag:\n",
     "                if False:\n"),
    ("keine Lastbremse", BACK, CSP,
     "    if len(liste) >= RATE_JE_MINUTE:\n",
     "    if False:\n"),
    ("Datei ohne 0640", BACK, CSP,
     "        if neu:\n            try:\n                os.chmod(p, DATEI_MODUS)\n",
     "        if False:\n            try:\n                os.chmod(p, DATEI_MODUS)\n"),
    ("Middleware fuer jeden Inhaltstyp", BACK, MAIN,
     '    if response.headers.get("content-type", "").lower().startswith("text/html"):\n'
     '        for name, wert in _csp.kopfzeilen(',
     '    if True:\n'
     '        for name, wert in _csp.kopfzeilen('),
    ("Admin-Endpunkt nur mit Anmeldung", BACK, MAIN,
     "async def security_csp_setzen(request: Request, user: str = Depends(require_local_auth)):\n",
     "async def security_csp_setzen(request: Request, user: str = Depends(require_auth)):\n"),
    ("Aufbewahrung vergisst die Meldungen", BACK, LR,
     '                     ("csp_berichte", _prune_csp_berichte)):\n',
     '                     ):\n'),
    # Frontend-Waechter
    ("Inline-Handler in einer Seite", FRONT, CHAT,
     ' id="ctx-indicator-clear"',
     ' id="ctx-indicator-clear" onclick="window._clearUserContext()"'),
    ("Inline-Skript in einer Seite", FRONT, CHAT,
     '<script src="/static/js/theme_frueh.js?v=1"></script>',
     "<script>try{document.body.classList.add('light');}catch(e){}</script>"),
    ("Inline-Handler in JS-Markup", FRONT, I18N,
     "// ─── Auto-Apply nach DOM-Ready",
     "function _probe(x) { return `<button class=\"a\" onclick=\"go('${x}')\">x</button>`; }\n"
     "// ─── Auto-Apply nach DOM-Ready"),
    ("setAttribute('onclick') in JS", FRONT, I18N,
     "// ─── Auto-Apply nach DOM-Ready",
     "function _probe2(b) { b.setAttribute('onclick', 'x()'); }\n"
     "// ─── Auto-Apply nach DOM-Ready"),
]

DATEIEN = sorted({p[2] for p in PROBEN})


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def lauf(waechter: Path) -> tuple[int, int]:
    r = subprocess.run([sys.executable, str(waechter)], capture_output=True, text=True,
                       timeout=300, cwd=str(ROOT))
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", r.stdout)
    if r.returncode == 2 or not m:
        return -1, r.returncode
    return int(m.group(1)), int(m.group(2))


def main() -> int:
    vorher = {d: md5(d) for d in DATEIEN}
    for w in (BACK, FRONT):
        ok, fail = lauf(w)
        if ok < 0 or fail:
            print("ABBRUCH (Exit 2): Basislauf %s nicht gruen (%s OK, %s FAIL)" % (w.name, ok, fail))
            return 2
        print("Basislauf %s: %d OK, 0 FAIL" % (w.name, ok))
    for name, w, datei, alt, neu in PROBEN:
        if (ROOT / datei).read_text(encoding="utf-8").count(alt) != 1:
            print("ABBRUCH (Exit 2): Probe '%s' – Stelle in %s nicht genau einmal gefunden" % (name, datei))
            return 2
    nicht = 0
    for name, w, datei, alt, neu in PROBEN:
        p = ROOT / datei
        original = p.read_bytes()
        try:
            p.write_text(original.decode("utf-8").replace(alt, neu, 1), encoding="utf-8")
            ok, fail = lauf(w)
        finally:
            p.write_bytes(original)
        # Ein Abbruch (Exit 2) ist KEIN Biss – der Waechter hat dann nichts gemessen.
        beisst = ok >= 0 and fail > 0
        if not beisst:
            nicht += 1
        print("  %s %-40s -> %s" % ("OK  " if beisst else "FAIL", name,
                                    "%d FAIL" % fail if ok >= 0 else "Abbruch"))
    nachher = {d: md5(d) for d in DATEIEN}
    if nachher != vorher:
        print("ABBRUCH (Exit 2): Dateien nach der Gegenprobe nicht byte-gleich: %s"
              % [d for d in DATEIEN if nachher[d] != vorher[d]])
        return 2
    print("\nErgebnis: %d von %d Proben beissen" % (len(PROBEN) - nicht, len(PROBEN)))
    return 0 if nicht == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
