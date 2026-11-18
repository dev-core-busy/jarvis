#!/usr/bin/env python3
"""Gegenprobe: beisst tests/test_ad_ldaps_ui.js ueberhaupt?

Legt dem Waechter sabotierte KOPIEN von frontend/js/settings_ad.js vor
(Argument, Wegwerf-Verzeichnis) – die echte Datei wird nie angefasst.
Je Probe wird die Zahl der FAIL ausgegeben; eine Probe beisst, wenn der
Waechter mit Exit 1 UND mindestens einem FAIL endet (Exit 1 ohne Bilanz
waere ein Absturz, kein Biss).
Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen
"""

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HIER = Path(__file__).resolve().parent
WAECHTER = HIER / "test_ad_ldaps_ui.js"
MODUL = HIER.parent / "frontend" / "js" / "settings_ad.js"

PROBEN = [
    ("Speichern nimmt wieder das nackte Feld (Schalter wirkungslos)",
     "            ad_server:        _adAdresse(),",
     "            ad_server:        document.getElementById('ad-server').value.trim(),"),
    ("Laden setzt den Schalter nicht",
     "            if (_adLdapsEl()) _adLdapsEl().checked = _z.art === 'ldaps';\n",
     ""),
    ("Laden laesst das Schema im Feld stehen",
     "            document.getElementById('ad-server').value        = _z.rest;\n",
     "            document.getElementById('ad-server').value        = d.server || '';\n"),
    ("StartTLS wird mit ldap:// gespeichert (Bestand nicht mehr byte-gleich)",
     "        return ldaps ? 'ldaps://' + rest : rest;\n",
     "        return (ldaps ? 'ldaps://' : 'ldap://') + rest;\n"),
    ("Standardport der anderen Art wird mitgenommen",
     "        if (p && p[2] === (ldaps ? '389' : '636')) rest = p[1];\n",
     ""),
    ("Port wird auch bei nackter IPv6 abgeschnitten",
     "        var p = /^(\\[[^\\]]*\\]|[^:\\[\\]]+):(\\d+)$/.exec(rest);\n",
     "        var p = /^(.+):(\\d+)$/.exec(rest);\n"),
    ("fremdes Schema wird verschluckt",
     "        if (z.art === null) return z.rest;\n        var rest = z.rest.replace(/\\/+$/, '');\n        var p = /^(\\[",
     "        var rest = z.rest.replace(/\\/+$/, '').replace(/^[a-z]+:\\/\\//i, '');\n        var p = /^(\\["),
    ("getipptes Schema legt den Schalter nicht um",
     "        cb.checked = z.art === 'ldaps';\n        _adLdapsAnzeigen();\n",
     "        _adLdapsAnzeigen();\n"),
    ("Verbindungstest nimmt das nackte Feld",
     "        const srv = _adAdresse();\n",
     "        const srv = document.getElementById('ad-server').value.trim();\n"),
    ("Zertifikatspruefung nimmt das nackte Feld",
     "            ziel: function () { return { server: _adAdresse() }; },",
     "            ziel: function () { return { server: document.getElementById('ad-server').value.trim() }; },"),
    ("Anker-Warnung vergleicht den Port nicht",
     "(String(a.host).toLowerCase() !== neu.host || aPort !== neu.port)",
     "(String(a.host).toLowerCase() !== neu.host)"),
    ("Host wird nicht kleingeschrieben (Anker-Vergleich unterscheidet Gross/Klein)",
     "        return { host: p[1].replace(/^\\[|\\]$/g, '').toLowerCase(),\n",
     "        return { host: p[1].replace(/^\\[|\\]$/g, ''),\n"),
    ("Anker-Warnung haengt nicht am Schalter",
     "        if (cb) cb.addEventListener('change', _adLdapsAnzeigen);\n",
     ""),
    ("Ergebniszeile ignoriert das gemessene Ziel (fester Text)",
     "                var z = (d.ziel && typeof d.ziel === 'object') ? d.ziel : null;\n",
     "                var z = null;\n"),
    ("Ergebniszeile raet die Art aus dem Formular statt aus der Antwort",
     "window.t(z.ldaps ? 'security.ad_reachable_ldaps'",
     "window.t(srv.indexOf('ldaps') === 0 ? 'security.ad_reachable_ldaps'"),
    ("Beschriftung wechselt nicht mit dem Zustand",
     "        if (an) an.hidden = !cb.checked;\n        if (aus) aus.hidden = !!cb.checked;\n",
     ""),
]


def lauf(pfad: Path):
    r = subprocess.run(["node", str(WAECHTER), str(pfad)], capture_output=True, text=True, timeout=120)
    m = re.search(r"^(\d+) OK, (\d+) FAIL$", r.stdout, re.M)
    return r.returncode, (int(m.group(2)) if m else None)


def main() -> int:
    text = MODUL.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        kopie = Path(tmp) / "settings_ad.js"
        kopie.write_text(text, encoding="utf-8")
        rc, n = lauf(kopie)
        if rc != 0 or n != 0:
            print("ABBRUCH: Basislauf nicht gruen (Exit %s, FAIL %s)" % (rc, n))
            return 2
        print("Basislauf gruen.\n")
        treffer = 0
        for name, alt, neu in PROBEN:
            if text.count(alt) != 1:
                print("  ???  %s – Anker %dx gefunden" % (name, text.count(alt)))
                continue
            kopie.write_text(text.replace(alt, neu), encoding="utf-8")
            rc, n = lauf(kopie)
            biss = rc == 1 and bool(n)
            treffer += biss
            print("  %s %-66s Exit %d, %s FAIL" % ("OK  " if biss else "ZAHN", name, rc,
                                                   "ohne Bilanz" if n is None else n))
    print("\n%d/%d Proben beissen" % (treffer, len(PROBEN)))
    return 0 if treffer == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
