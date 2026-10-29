#!/usr/bin/env python3
"""Gegenprobe: beissen tests/test_cron_system_ui.js und tests/test_apt_verlauf.py?

Legt den Waechtern sabotierte KOPIEN von frontend/js/cron.js bzw.
backend/apt_upgrades.py vor (Argument, Wegwerf-Verzeichnis) – die echten
Dateien werden nie angefasst.
Exit 0 = alle Proben wie erwartet, 1 = mindestens eine nicht, 2 = konnte nicht laufen
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HIER = Path(__file__).resolve().parent
WURZEL = HIER.parent
UI = (["node", str(HIER / "test_cron_system_ui.js")], WURZEL / "frontend" / "js" / "cron.js")
PY = ([sys.executable, str(HIER / "test_apt_verlauf.py")], WURZEL / "backend" / "apt_upgrades.py")

PROBEN = [
    (UI, "Abruffehler wird zu \"ausgeschaltet\"",
     "        if (d.fehler) return { aktiv: false, text: window.t('cron.sys_fehler').replace('{e}', d.fehler), warn: true };\n",
     "        if (d.fehler) return { aktiv: false, text: window.t('cron.sys_aus'), warn: true };\n", 1),
    (UI, "fehlende Felder werden zu \"ausgeschaltet\"",
     "            return { aktiv: false, text: window.t('cron.sys_unbekannt'), warn: true };\n",
     "            return { aktiv: false, text: window.t('cron.sys_aus'), warn: true };\n", 1),
    (UI, "Grenze \"nach dem Timer-Lauf\" weg",
     "e.start >= letzter", "true", 1),
    (UI, "unlesbarer Verlauf heisst \"nie eingespielt\"",
     "        if (!Array.isArray(liste)) return window.t('cron.sys_verlauf_unlesbar');\n",
     "        if (!Array.isArray(liste)) return window.t('cron.sys_nie_eingespielt');\n", 1),
    (UI, "Neuzeichnen der Liste ruft den Status mit ab",
     "        const el = document.getElementById('cron-list');\n        try {\n            const r = await fetch('/api/cron',",
     "        const el = document.getElementById('cron-list');\n        this._loadSystem();\n        try {\n            const r = await fetch('/api/cron',", 1),
    (UI, "Paketname im Protokoll nicht mehr escaped",
     "<span class=\"cron-log-kurz\">${this._esc(this._sysNamen(e))}</span>",
     "<span class=\"cron-log-kurz\">${this._sysNamen(e)}</span>", 1),
    (UI, "Systemeintrag bekommt einen Bearbeiten-Knopf",
     "                    <div class=\"cron-item-actions\">\n                        <button class=\"kb-btn-icon cron-sys-log-btn\"",
     "                    <div class=\"cron-item-actions\">\n                        <button class=\"kb-btn-icon cron-edit-btn\"></button>\n                        <button class=\"kb-btn-icon cron-sys-log-btn\"", 1),
    (UI, "{marke} wird nicht ersetzt",
     "        return v.split('{marke}').join(marke);\n    }\n\n    _sysZeit(s) {",
     "        return v;\n    }\n\n    _sysZeit(s) {", 1),
    (UI, "Einstellungen-Knopf auch ohne Reiter",
     "${hatReiter ? `<button", "${true ? `<button", 1),
    (UI, "Laufzeile auch, wenn der Lauf etwas eingespielt hat",
     "                && !liste.some(e => typeof e.start === 'number' && e.start >= zp.letzter)) {\n",
     "                ) {\n", 1),
    (UI, "Laufzeile fehlt ganz",
     "        box.innerHTML = lauf + d.eingespielt.map(e => {",
     "        box.innerHTML = d.eingespielt.map(e => {", 1),
    (UI, "gescheiterter Lauf gilt als erfolgreich",
     "            const ok = zp.ergebnis === 'success';\n", "            const ok = true;\n", 1),
    (UI, "Renderer umbenannt -> konnte nicht laufen",
     "    _renderSystem() {\n", "    _renderSystemX() {\n", 2),
    (PY, "Commandline-Filter weg (Handlaeufe zaehlen mit)",
     "        if \"unattended-upgrade\" not in felder.get(\"Commandline\", \"\"):\n",
     "        if not felder:\n", 1),
    (PY, "unlesbar wird zur leeren Liste",
     "    if not gelesen:\n        return None\n", "    if not gelesen:\n        return []\n", 1),
    (PY, "0 Mikrosekunden wird 1970 statt unbekannt",
     "if isinstance(us, (int, float)) and us > 0:", "if isinstance(us, (int, float)):", 1),
    (PY, "rotierte .gz-Datei wird als Text gelesen",
     "            if pfad.endswith(\".gz\"):\n", "            if pfad.endswith(\".gz\") and False:\n", 1),
    (PY, "Funktion umbenannt -> konnte nicht laufen",
     "def zeitplan() -> dict:\n", "def zeitplan_alt() -> dict:\n", 2),
]


def lauf(befehl, pfad: Path) -> int:
    try:
        return subprocess.run(befehl + [str(pfad)], capture_output=True, text=True, cwd=WURZEL,
                              env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), timeout=180).returncode
    except subprocess.TimeoutExpired:
        return 124


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        for befehl, quelle in (UI, PY):
            kopie = Path(tmp) / quelle.name
            kopie.write_text(quelle.read_text(encoding="utf-8"), encoding="utf-8")
            if lauf(befehl, kopie) != 0:
                print(f"ABBRUCH: Basislauf nicht gruen ({quelle.name})")
                return 2
        print("Basislaeufe gruen.\n")
        treffer = 0
        for (befehl, quelle), name, alt, neu, erwartet in PROBEN:
            text = quelle.read_text(encoding="utf-8")
            if text.count(alt) != 1:
                print("  ???  %s – Anker %dx gefunden" % (name, text.count(alt)))
                continue
            kopie = Path(tmp) / quelle.name
            kopie.write_text(text.replace(alt, neu), encoding="utf-8")
            rc = lauf(befehl, kopie)
            treffer += rc == erwartet
            print("  %s %-55s Exit %d (erwartet %d)"
                  % ("OK  " if rc == erwartet else "ZAHN", name, rc, erwartet))
    print("\n%d/%d Proben wie erwartet" % (treffer, len(PROBEN)))
    return 0 if treffer == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
