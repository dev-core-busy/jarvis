#!/usr/bin/env python3
"""Gegenprobe zu tests/test_bsi_m3_ui.js: beisst der Waechter?

Jede Probe dreht EINEN Teil des M3-Fixes zurueck (Python-Ersetzung ganzer
Zeilen), laesst den Waechter laufen und erwartet mindestens einen FAIL. Vorher
gruener Basislauf, danach Byte-Gleichheit aller Dateien per md5. Ohne Bytecode.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)


import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_bsi_m3_ui.js"
APP = "frontend/js/app.js"
MOD = "frontend/js/totp_admin.js"
SBTN = "frontend/js/settings_btn.js"
SET = "frontend/settings.html"
I18N = "frontend/js/i18n.js"

PROBEN = [
    # ── Anmeldemaske (Admins ohne 2FA-Abfrage, 2026-11-20) ──
    ("Erfolg blendet das Codefeld ein", APP,
     "                if (totpRow) totpRow.style.display = 'none';\n",
     "                if (totpRow) totpRow.style.display = '';\n"),
    ("requires_totp blendet das Codefeld nicht ein", APP,
     "                if (totpRow) totpRow.style.display = '';\n                if (totpInput) totpInput.focus();\n",
     "                if (totpInput) totpInput.focus();\n"),
    ("Einrichtungszweig an der Maske kehrt zurueck", APP,
     "            } else if (data.requires_totp) {\n",
     "            } else if (data.requires_totp_setup) {\n            } else if (data.requires_totp) {\n"),
    # ── Sicherheits-Reiter ──
    ("Sperrliste: Name als HTML", MOD,
     "            row.appendChild(el('strong', { 'style': 'color:var(--text-primary);' }, s.display || s.konto));\n",
     "            var _s = el('strong', {}); _s.innerHTML = s.display || s.konto; row.appendChild(_s);\n"),
    ("Aufheben laedt nicht neu", MOD,
     "                    if ((res.status === 200 && res.d.ok) || res.status === 404) { schutzLaden(); return; }\n",
     "                    if ((res.status === 200 && res.d.ok) || res.status === 404) { return; }\n"),
    ("onShow laedt den Anmeldeschutz nicht", MOD,
     "        load();\n        schutzLaden();\n", "        load();\n"),
    # ── Zahnrad ──
    ("Zahnrad nur mit Rechten statt fuer das Admin-Konto", SBTN,
     "                var an = _konto;\n", "                var an = _admin;\n"),
    ("Klick wechselt direkt nach /settings (alte Fassung)", SBTN,
     "            b.addEventListener('click', function () { klick(b); });\n",
     "            b.addEventListener('click', function () { location.href = '/settings'; });\n"),
    ("sechs Ziffern schicken nicht ab", SBTN,
     "                if (c.length === 6 && !pwFeld && !ok.disabled) { codeFeld.value = c; abschicken(); }\n",
     "                if (false) { codeFeld.value = c; abschicken(); }\n"),
    ("Einrichtung schickt schon ohne Kennwort ab", SBTN,
     "                if (c.length === 6 && !pwFeld && !ok.disabled) { codeFeld.value = c; abschicken(); }\n",
     "                if (c.length === 6 && !ok.disabled) { codeFeld.value = c; abschicken(); }\n"),
    ("Kennwort-Pflicht im Dialog fehlt", SBTN,
     "                    if (!pwFeld.value) {\n", "                    if (false) {\n"),
    ("QR verschwindet bei falscher Eingabe", SBTN,
     "                && !d.qr_code) {\n", "                && false) {\n"),
    ("Server-Aufforderung steht als Fehler da", SBTN,
     "        if (!codeFeld) meldung(d.error || '');\n", "        meldung(d.error || '');\n"),
    ("Escape schliesst den Dialog nicht", SBTN,
     "        if (ev.key === 'Escape') { ev.preventDefault(); dialogZu(); }\n",
     "        if (ev.key === 'Escape') { ev.preventDefault(); }\n"),
    ("Rueckweg wird nicht gemerkt", SBTN,
     "                rueckwegMerken(b);\n                // Auf /settings selbst",
     "                // Auf /settings selbst"),
    ("Markierung mit Rechten fehlt", SBTN,
     "            b.classList.toggle('jv-gear-erhoeht', !!_admin);\n", ""),
    ("Menue bietet auf /settings auch 'Einstellungen'", SBTN,
     "        if (!aufEinstellungen()) {\n            eintrag(",
     "        if (true) {\n            eintrag("),
    ("Beenden fragt den Server nicht", SBTN,
     "        return senden('/api/admin/erhoehung/beenden', {}).then(function (res) {\n",
     "        return Promise.resolve({ d: { ok: true } }).then(function (res) {\n"),
    ("Schliessen-Knopf ohne Symbol", SBTN,
     "        x.innerHTML = (window.JarvisIcons && window.JarvisIcons.close) ? window.JarvisIcons.close() : '';\n", ""),
    # ── Markup / i18n ──
    ("Zahnrad auf /settings fehlt", SET,
     '                            data-jarvis-settings="/settings"\n', ""),
    ("Pflicht-Schalter kehrt ins Markup zurueck", SET,
     '<h4 style="margin:18px 0 6px;" data-i18n="security.admin_zahnrad_h">',
     '<input type="checkbox" id="sec-admin-2fa-pflicht"><h4 style="margin:18px 0 6px;" data-i18n="security.admin_zahnrad_h">'),
    ("EN-Text eines Zahnrad-Schluessels fehlt", I18N,
     "        'gear.menue_beenden':   'End administration',\n", ""),
]

DATEIEN = [APP, MOD, SBTN, SET, I18N, "tests/test_bsi_m3_ui.js"]


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def lauf() -> tuple[int, int]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run(["node", str(WAECHTER)], capture_output=True, text=True,
                       timeout=300, cwd=str(ROOT), env=env)
    m = re.search(r"Ergebnis: (\d+)/(\d+)", r.stdout)
    if r.returncode == 2 or not m:
        return -1, r.returncode
    return int(m.group(2)) - int(m.group(1)), r.returncode


def main() -> int:
    if {p[1] for p in PROBEN} - set(DATEIEN):
        print("ABBRUCH: Probe fasst eine nicht gesicherte Datei an")
        return 2
    sicherung = {d: (ROOT / d).read_bytes() for d in DATEIEN}
    vorher = {d: md5(d) for d in DATEIEN}

    fails, rc = lauf()
    if fails != 0:
        print("ABBRUCH: Basislauf nicht gruen (FAIL=%s, rc=%s)" % (fails, rc))
        return 2
    print("Basislauf gruen.\n")

    beissen = 0
    try:
        for name, datei, alt, neu in PROBEN:
            pfad = ROOT / datei
            text = pfad.read_text(encoding="utf-8")
            if text.count(alt) != 1:
                print("  ???  %s – Anker %dx gefunden" % (name, text.count(alt)))
                continue
            pfad.write_text(text.replace(alt, neu), encoding="utf-8")
            try:
                fails, rc = lauf()
            finally:
                pfad.write_bytes(sicherung[datei])
            if fails > 0:
                beissen += 1
                print("  BISS %-56s %d FAIL" % (name, fails))
            elif fails < 0:
                print("  ABBR %-56s Waechter konnte nicht laufen (rc=%s)" % (name, rc))
            else:
                print("  ZAHN %-56s 0 FAIL – beisst NICHT" % name)
    finally:
        for d, inhalt in sicherung.items():
            (ROOT / d).write_bytes(inhalt)

    nachher = {d: md5(d) for d in DATEIEN}
    if nachher != vorher:
        print("\nABBRUCH: Dateien nach der Probe nicht byte-gleich: %s"
              % [d for d in DATEIEN if nachher[d] != vorher[d]])
        return 2
    print("\n%d/%d Proben beissen (Dateien byte-gleich wiederhergestellt)"
          % (beissen, len(PROBEN)))
    return 0 if beissen == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
