#!/usr/bin/env python3
"""Gegenprobe: beisst tests/test_zugaenge_reiter_ui.js?

Kopiert ``frontend/`` in ein Wegwerf-Verzeichnis, sabotiert dort je Probe EINE
Stelle und laesst den Waechter ueber ``ZR_ROOT`` gegen die Kopie laufen – die
echten Dateien werden nie angefasst. Vorher ein Basislauf: ohne gruene Basis
ist keine Probe deutbar.

Exit 0 = alle Proben beissen, 1 = mindestens eine stumm, 2 = konnte nicht laufen.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HIER = Path(__file__).resolve().parent
ROOT = HIER.parent
WAECHTER = HIER / "test_zugaenge_reiter_ui.js"

PROBEN = [
    ("Confluence: Verbindung wieder als lose Ueberschrift", "settings.html",
     '<div class="kb-section" id="cf-sect-conn">', '<div id="cf-sect-conn">', 1),
    ("SAP: Container Persoenliche Zugaenge fehlt", "settings.html",
     '<div class="kb-section" id="sap-sect-acc">', '<div id="sap-sect-acc">', 1),
    # Den ganzen Block des Schalters HINTER den Container "Persoenliche
    # VEMAS-Zugaenge" verschieben – ein blosses Umbenennen waere keine Aussage
    # ueber den ORT (und liess den Waechter frueher abstuerzen statt beissen).
    ("VEMAS: Schalter ausserhalb von Verbindung", "settings.html", "VERSCHIEBE", None, 1),
    ("SAP: Schalter fehlt ganz", "settings.html",
     'id="sap-persoenlich" checked>', 'id="sap-persoenlich-weg" checked>', 1),
    ("Confluence: anderer Schaltertext", "settings.html",
     '<span data-i18n="cf.persoenlich">Speichern persönlicher Zugänge auf Server erlauben</span>',
     '<span data-i18n="cf.persoenlich">Eigene Token erlauben</span>', 1),
    ("SAP: Container nicht klappbar gebunden", "js/app.js",
     "                { hdr: 'sap-sect-acc-hdr',  body: 'sap-sect-acc-body',  tog: 'sap-sect-acc-tog'  },\n", "", 1),
    ("VEMAS: Bindung beim Oeffnen nicht aufgerufen", "js/app.js",
     "                    _initVemasCollapse();\n", "", 1),
    ("skillcfg: Vorgabe kippt (Feld fehlt = aus)", "js/skillcfg.js",
     "var erlaubt = (cfg || {}).persoenliche_zugaenge !== false;",
     "var erlaubt = (cfg || {}).persoenliche_zugaenge === true;", 1),
    ("skillcfg: Container folgt nicht", "js/skillcfg.js",
     "if (s) s.style.display = erlaubt ? '' : 'none';", "", 1),
    ("skillcfg: keine Rueckfrage", "js/skillcfg.js",
     "if (jetzt || !gespeichert) return true;", "return true;", 1),
    ("SAP: Haken nicht umgekehrt gespeichert", "js/sap.js",
     "            return cb ? !cb.checked : !!(this._cfg && this._cfg.kachel_anmeldung);",
     "            return cb ? !!cb.checked : !!(this._cfg && this._cfg.kachel_anmeldung);", 1),
    ("VEMAS: Haken liest wieder persoenliche_zugaenge", "js/vemas.js",
     "if ($('vemas-persoenlich')) $('vemas-persoenlich').checked = !c.kachel_anmeldung;",
     "if ($('vemas-persoenlich')) $('vemas-persoenlich').checked = c.persoenliche_zugaenge !== false;", 1),
    ("SAP: zweiter Kachel-Haken wieder im Markup", "settings.html",
     '<input type="checkbox" id="sap-persoenlich" checked>',
     '<input type="checkbox" id="sap-persoenlich" checked><input type="checkbox" id="sap-kachel-pflicht">', 1),
    ("VEMAS: Container folgt dem Haken nicht", "js/vemas.js",
     "                    if (window.SkillCfg) window.SkillCfg.persoenlichAnwenden('vemas', !c.kachel_anmeldung);\n",
     "", 1),
    ("SAP: Container bleibt trotz Haken aus sichtbar", "js/sap.js",
     "window.SkillCfg.persoenlichAnwenden('sap', !c.kachel_anmeldung);",
     "window.SkillCfg.persoenlichAnwenden('sap', true);", 1),
    ("Confluence: Rumpf ohne Schalter", "js/confluence.js",
     "                persoenliche_zugaenge: window.SkillCfg ? window.SkillCfg.persoenlichHaken('cf') : true\n",
     "", 1),
    ("SAP: Rumpf ohne Schalter", "js/sap.js",
     "                kachel_anmeldung: this._kachelGewaehlt()\n", "", 1),
    ("VEMAS: Rueckfrage nicht aufgerufen", "js/vemas.js",
     "            if (this._kachelGewaehlt() && !(this._cfg && this._cfg.kachel_anmeldung)) {",
     "            if (false && !(this._cfg && this._cfg.kachel_anmeldung)) {", 1),
    ("SAP: Kennwortfelder folgen dem Haken nicht", "js/sap.js",
     "            var kp = $('sap-persoenlich');\n            if (kp) kp.addEventListener('change', function () { self._applyKachel(); });\n",
     "", 1),
    ("Confluence: Liste wird nicht geladen", "js/confluence.js",
     "            this.loadZugaenge();\n        },", "        },", 1),
    ("Confluence: Liste setzt Fremdtext als Markup", "js/confluence.js",
     "                        n.textContent = a.user || '';", "                        n.innerHTML = a.user || '';", 1),
]


def verschiebe_vemas_schalter(t: str):
    """Schneidet den form-group-Block mit #vemas-persoenlich aus und setzt ihn
    hinter das Ende des Containers #vemas-sect-acc."""
    i = t.find('id="vemas-persoenlich"')
    if i < 0:
        return None
    anfang = t.rfind('<div class="form-group">', 0, i)
    ende = t.find("</div>", t.find("</span>", i)) + len("</div>")
    block = t[anfang:ende]
    rest = t[:anfang] + t[ende:]
    acc = rest.find('id="vemas-sect-acc"')
    if acc < 0:
        return None
    # Ende des Containers: drei schliessende divs nach der Liste
    liste = rest.find('id="vemas-accounts-list"', acc)
    pos = liste
    for _ in range(3):
        pos = rest.find("</div>", pos) + len("</div>")
    return rest[:pos] + "\n" + block + rest[pos:]


def kopie() -> Path:
    ziel = Path(tempfile.mkdtemp(prefix="gegen-zugaenge-"))
    shutil.copytree(ROOT / "frontend", ziel / "frontend",
                    ignore=shutil.ignore_patterns("vendor", "*.png", "*.jpg", "*.svg"))
    return ziel


def lauf(wurzel: Path):
    env = dict(os.environ, ZR_ROOT=str(wurzel))
    r = subprocess.run(["node", str(WAECHTER)], capture_output=True, text=True,
                       env=env, timeout=180)
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", r.stdout)
    return r.returncode, (int(m.group(2)) if m else None)


def main():
    b = kopie()
    try:
        rc, fails = lauf(b)
    finally:
        shutil.rmtree(b, ignore_errors=True)
    if rc != 0 or fails != 0:
        print(f"ABBRUCH: Basislauf nicht gruen (Exit {rc}, FAIL {fails})")
        sys.exit(2)
    print("Basislauf gruen.\n")
    stumm = 0
    for i, (name, datei, alt, neu, anzahl) in enumerate(PROBEN, 1):
        w = kopie()
        try:
            p = w / "frontend" / datei
            t = p.read_text(encoding="utf-8")
            if alt == "VERSCHIEBE":
                t2 = verschiebe_vemas_schalter(t)
                if t2 is None:
                    print(f"  ANKER  {i:2} {name} – Block nicht gefunden")
                    stumm += 1
                    continue
                p.write_text(t2, encoding="utf-8")
                rc, fails = lauf(w)
            elif t.count(alt) != anzahl:
                print(f"  ANKER  {i:2} {name} – {t.count(alt)}x statt {anzahl}x")
                stumm += 1
                continue
            else:
                p.write_text(t.replace(alt, neu), encoding="utf-8")
                rc, fails = lauf(w)
        finally:
            shutil.rmtree(w, ignore_errors=True)
        if rc == 1 and fails:
            print(f"  BEISST {i:2} {name} ({fails} FAIL)")
        else:
            stumm += 1
            print(f"  STUMM  {i:2} {name} (Exit {rc}, FAIL {fails})")
    print(f"\nErgebnis: {len(PROBEN) - stumm}/{len(PROBEN)} Proben beissen")
    sys.exit(1 if stumm else 0)


if __name__ == "__main__":
    main()
