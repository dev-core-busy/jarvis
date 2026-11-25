#!/usr/bin/env python3
"""Gegenprobe zu tests/test_ueberwachung.py, tests/test_ueberwachung_ui.js und
dem SSH-Posten am Zahnrad (tests/test_gear_badge.py, tests/test_gear_badge_ui.js).

Jede Probe sabotiert eine KOPIE von backend/ueberwachung.py,
deploy/security/system_haertung.sh, backend/main.py oder frontend/js/sysload.js
in einem Wegwerf-Verzeichnis und laesst beide Waechter gegen diese Kopien
laufen (JARVIS_UEBERW_PRUEFLING, JARVIS_HAERTUNG_PRUEFLING,
JARVIS_MAIN_PRUEFLING, JARVIS_SYSLOAD_PRUEFLING). Die Repo-Dateien werden nie
angefasst.

Erwartet je Probe: mindestens ein Waechter Exit 1 mit FAIL und keiner Exit 2.
Vorab muss der Basislauf gegen die unveraenderten Kopien gruen sein.

Exit 0 = alle Proben beissen, 1 = mindestens eine stumm, 2 = konnte nicht laufen.
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

REPO = Path(__file__).resolve().parent.parent
QUELLEN = {
    "ue": REPO / "backend" / "ueberwachung.py",
    "sh": REPO / "deploy" / "security" / "system_haertung.sh",
    "main": REPO / "backend" / "main.py",
    "js": REPO / "frontend" / "js" / "sysload.js",
    "sbtn": REPO / "frontend" / "js" / "settings_btn.js",
}
PY = REPO / "tests" / "test_ueberwachung.py"
JS = REPO / "tests" / "test_ueberwachung_ui.js"
GEAR_PY = REPO / "tests" / "test_gear_badge.py"
GEAR_JS = REPO / "tests" / "test_gear_badge_ui.js"

# (Name, Datei, alt, neu, erwartete Trefferzahl von 'alt')
PROBEN = [
    # ── Auswertung ──
    ("SSH: 'Failed publickey' zaehlt als Fehlversuch", "ue",
     'r"^(?:Failed (?:password|keyboard-interactive\\S*) for"',
     'r"^(?:Failed (?:password|publickey|keyboard-interactive\\S*) for"', 1),
    ("SSH: Accepted wird uebersehen", "ue", "        if _SSH_OK.match(msg):", "        if False:", 1),
    ("SSH: je Zeile statt je Verbindung", "ue",
     'schluessel = "%s:%s" % (m.group("ip"), m.group("port"))',
     'schluessel = "%s:%s:%d" % (m.group("ip"), m.group("port"), i)', 1),
    ("SSH: Folgelauf zaehlt dieselbe Verbindung erneut", "ue",
     'if v["schluessel"] not in gezaehlt]', "]", 1),
    ("Ausgang Dienstbenutzer nur Warnung", "ue", '("out_dienst", "alarm",', '("out_dienst", "warnung",', 1),
    # AIDE-Abgleich (24.11.2026)
    ("AIDE: offener Abgleich stumm", "ue", '        if a.get("zustand") == "offen":', '        if False:', 1),
    ("AIDE: gescheiterter Abgleich stumm", "ue", '        elif a.get("zustand") == "fehler":', '        elif False:', 1),
    ("AIDE: veralteter Abgleich stumm", "ue", "        if jetzt - juengst > AIDE_VERALTET_S:", "        if False:", 1),
    ("AIDE: nie gelaufen gilt als frisch", "ue", "        juengst = zeit or eing[\"aide_eingerichtet\"]",
     "        juengst = zeit or jetzt", 1),
    ("Sandbox und Fremde vertauscht", "ue",
     '"out_sandbox" if z["uid"] in sandbox else "out_fremd"', '"out_fremd" if z["uid"] in sandbox else "out_sandbox"', 1),
    ("Dienst: startend gilt als ausgefallen", "ue",
     '("active", "activating", "deactivating", "reloading", "refreshing")', '("active", "deactivating")', 1),
    ("Dienst: Neustart (deactivating) gilt als ausgefallen", "ue",
     '("active", "activating", "deactivating", "reloading", "refreshing")', '("active", "activating", "reloading", "refreshing")', 1),
    ("Dienst: auch abgeschaltete Units melden", "ue",
     'if z.get("enabled") in ("enabled", "enabled-runtime") \\', "if True \\", 1),
    ("Platz: Alarmvergleich verdreht", "ue",
     'anteil < _zahl(konf, "PLATZ_ALARM")', 'anteil > _zahl(konf, "PLATZ_ALARM")', 1),
    ("Platz: gleiches Dateisystem doppelt", "ue",
     'if p.get("geraet") in gesehen or not p.get("gesamt"):', 'if not p.get("gesamt"):', 1),
    ("Zertifikat: abgelaufen ist kein Alarm", "ue",
     'stufe = "alarm" if tage <= _zahl(konf, "ZERT_ALARM_TAGE")', 'stufe = "alarm" if 0 <= tage <= _zahl(konf, "ZERT_ALARM_TAGE")', 1),
    ("Ereignisse verfallen nie", "ue",
     'if jetzt - e.get("zeit", 0) <= HALTE_S]', "]", 1),
    ("Journal: Meldung in jedem Lauf", "ue", 'if not gleich or erinnern or not b["gemeldet"]:', "if True:", 1),
    ("Journal: kein BEHOBEN", "ue",
     'if bid not in neu_ids and a.get("stufe") in ("warnung", "alarm"):', "if False:", 1),
    ("Journal: auch Hinweise", "ue", 'if b["stufe"] in ("warnung", "alarm"):', "if True:", 1),
    ("Lesen: veralteter Zustand gilt als gut", "ue", "    if alter > VERALTET_S:", "    if False:", 1),
    ("Lesen: Interna an die Oberflaeche", "ue",
     'befunde = [{k: b.get(k) for k in ("id", "art", "stufe", "text", "werte", "seit")}\n               for b in z.get("befunde") or []]',
     'befunde = list(z.get("befunde") or [])', 1),
    ("Veraltet erst nach einem Tag", "ue", "VERALTET_S = 3 * TAKT_S", "VERALTET_S = 24 * 3600", 1),
    ("Schreiben: fuer alle lesbar", "ue", "    modus = 0o600\n", "    modus = 0o644\n", 1),
    ("Konfiguration: fremde Datei wird gelesen", "ue",
     "if st.st_uid != 0 or st.st_mode & 0o022 or", "if st.st_mode & 0o022 or", 1),
    ("Fremdpaket im Root-Modul", "ue", "def _uid(name: str)", "def _x():\n    import yaml  # noqa\n\n\ndef _uid(name: str)", 1),
    # ── Units ──
    ("Programm aus /opt/jarvis (K1)", "sh",
     'UEBERW_PROG="/usr/local/lib/jarvis-broker/backend/ueberwachung.py"', 'UEBERW_PROG="/opt/jarvis/backend/ueberwachung.py"', 1),
    ("Unit mit Netz", "sh", "PrivateNetwork=yes\n", "", 1),
    ("Timer alle 15 Minuten", "sh", "OnUnitActiveSec=5min", "OnUnitActiveSec=15min", 1),
    ("--anwenden startet den Timer nicht", "sh",
     "systemctl enable --now jarvis-ueberwachung.timer", "systemctl enable jarvis-ueberwachung.timer", 1),
    ("AIDE meldet den Zustand taeglich", "sh", "/var/lib/jarvis-ueberwachung/zustand\\.json$ f VarFile\n", "", 1),
    ("--pruefen ohne Altersgrenze", "sh", '"  VERALTET    Ueberwachung:', '"  ALT    Ueberwachung:', 1),
    # ── Endpunkt ──
    ("Endpunkt ohne Admin-Schranke", "main",
     "async def system_ueberwachung(user: str = Depends(require_local_auth)):",
     "async def system_ueberwachung(user: str = Depends(require_auth)):", 1),
    ("Endpunkt liest im Event-Loop", "main", "erg = await asyncio.to_thread(_ueberw.lesen)", "erg = _ueberw.lesen()", 1),
    # ── CPU-Anzeige: KEINE Spur der Ueberwachung (2026-11-25) ── die Proben
    # bauen das Entfernte wieder ein; sysload.js hat sonst keinen Anker dafuer.
    ("CPU-Anzeige: Markierung zurueck", "js",
     "            el.title = T('load.btn', 'Systemauslastung anzeigen');\n",
     "            el.title = T('load.btn', 'Systemauslastung anzeigen');\n            el.classList.add('jv-ue-warnung');\n", 1),
    ("CPU-Anzeige: Tooltip nennt die Ueberwachung", "js",
     "            el.title = T('load.btn', 'Systemauslastung anzeigen');\n",
     "            el.title = T('load.btn', 'Systemauslastung anzeigen') + ' – Serverüberwachung: Warnung';\n", 1),
    ("CPU-Anzeige: fragt die Ueberwachung ab", "js",
     "                if (!anzeigeAusstatten()) ausstattenSpaeter();\n",
     "                if (!anzeigeAusstatten()) ausstattenSpaeter();\n                if (_admin) fetch('/api/system/ueberwachung');\n", 1),
    # ── Zahnrad: alle Warnungen/Alarme (2026-11-25) ──
    ("Zahnrad: Warnungen der Ueberwachung fehlen", "main",
     '            elif b.get("stufe") in ("warnung", "alarm"):', '            elif False:', 1),
    ("Zahnrad: auch Hinweise", "main",
     '            elif b.get("stufe") in ("warnung", "alarm"):', '            elif b.get("stufe") in ("warnung", "alarm", "info"):', 1),
    ("Zahnrad: Warnungen nicht gezaehlt", "main",
     '"gesamt": pending + gesperrt + (1 if ssh else 0) + len(ue_befunde),',
     '"gesamt": pending + gesperrt + (1 if ssh else 0),', 1),
    ("Zahnrad: Alarme nicht vorn", "main",
     '    ue_befunde.sort(key=lambda b: 0 if b.get("stufe") == "alarm" else 1)\n', "", 1),
    ("Zahnrad: Ueberwachungs-Alarm verschluckt", "main",
     '    ue_alarm = any(b.get("stufe") == "alarm" for b in ue_befunde)', "    ue_alarm = False", 1),
    ("Zahnrad: Werte ungeprueft durchgereicht", "main",
     '"werte": werte if isinstance(werte, dict) else {},', '"werte": werte,', 1),
    ("Zahnrad: Ueberwachungszeile fehlt", "sbtn", "            if (it.art === 'ue') return ueZeile(it);\n", "", 1),
    ("Zahnrad: stille Zeile verspricht einen Sprung", "sbtn",
     """'<div class="jv-gear-tip-row jv-gear-tip-still" data-ue="'""",
     """'<div class="jv-gear-tip-row jv-gear-tip-still" data-fokus="broker" data-ue="'""", 1),
    ("Zahnrad: AIDE ohne Ziel", "sbtn", "        aide_offen: ['profiles', 'pakete'],\n", "", 1),
    ("Zahnrad: Reiter fest auf Sicherheit", "sbtn",
     "sessionStorage.setItem('jarvis_settings_tab', reiter || 'security');",
     "sessionStorage.setItem('jarvis_settings_tab', 'security');", 1),
    ("Zahnrad: Platzhalter bleiben stehen", "sbtn",
     "return vorlage.replace(/\\{(\\w+)\\}/g,", "return vorlage.replace(/\\{(\\d+)\\}/g,", 1),
    ("Zahnrad: Befundtext unmaskiert", "sbtn", "(esc(ueText(it)) || '–')", "(ueText(it) || '–')", 1),
    ("Zahnrad: Ueberwachungs-Alarm faerbt nicht rot", "sbtn",
     "(_badge.gesperrt || _badge.ssh_alarm || _badge.ue_alarm)", "(_badge.gesperrt || _badge.ssh_alarm)", 1),
    ("Zahnrad: Hinweis zu stillen Zeilen fehlt", "sbtn", "        if (ueStill) {\n", "        if (false) {\n", 1),
    ("Zahnrad: SSH je Fehlversuch gezaehlt", "main",
     '"gesamt": pending + gesperrt + (1 if ssh else 0) + len(ue_befunde),',
     '"gesamt": pending + gesperrt + ssh + len(ue_befunde),', 1),
    ("Zahnrad: kein SSH-Eintrag", "main", '        if ssh:\n            posten.append({\n                "art": "ssh",',
     '        if False:\n            posten.append({\n                "art": "ssh",', 1),
    ("Zahnrad: SSH-Alarm verschluckt", "main",
     'ssh_alarm = bool(ssh) and ssh_befund.get("stufe") == "alarm"', "ssh_alarm = False", 1),
    ("Zahnrad: SSH-Zeile als normaler Eintrag (mit Sprung)", "sbtn",
     "            if (it.art === 'ssh') return sshZeile(it);\n", "", 1),
    ("Zahnrad: SSH-Zeile springt in die Einstellungen", "sbtn",
     """'<button type="button" class="jv-gear-tip-row" data-ssh="1" aria-expanded="'""",
     """'<button type="button" class="jv-gear-tip-row" data-ssh="1" data-fokus="broker" aria-expanded="'""", 1),
    # ── Aufklappen der SSH-Zeile (gemeldet 2026-11-22: Klick ohne Wirkung) ──
    ("Zahnrad: Klick auf SSH ohne Wirkung", "sbtn", "                    _sshOffen = !_sshOffen;\n", "", 1),
    ("Zahnrad: Neuzeichnen klappt SSH zu", "sbtn",
     "        if (n && tipOffen()) tipZeichnen();", "        if (n && tipOffen()) { _sshOffen = false; tipZeichnen(); }", 1),
    ("Zahnrad: Hinweis verspricht immer einen Abschnitt", "sbtn",
     "        if (mitSprung || !posten.length) {", "        if (true) {", 1),
    ("Zahnrad: Hinweis zum SSH-Eintrag fehlt", "sbtn",
     "        if (ssh) {\n            teile.push(T('security.gear_tip_hint_ssh'",
     "        if (false) {\n            teile.push(T('security.gear_tip_hint_ssh'", 1),
    ("Zahnrad: Verlauf unmaskiert", "sbtn",
     "'<div class=\"jv-gear-tip-dz\">' + esc((v.zeit ? zeitpunkt(v.zeit) + ' · ' : '') + text)",
     "'<div class=\"jv-gear-tip-dz\">' + ((v.zeit ? zeitpunkt(v.zeit) + ' · ' : '') + text)", 1),
    ("Badge: Verlauf nicht durchgereicht", "main",
     'for v in (ssh_werte.get("verlauf") or [])[:10] if isinstance(v, dict)],', "for v in []],", 1),
    ("Badge: Verlauf ohne Typpruefung", "main",
     '"ips": [str(x) for x in (v.get("ips") or [])][:10],', '"ips": list(v.get("ips") or [])[:10],', 1),
    ("Befund: Verlauf aeltester zuerst", "ue", "for e in reversed(es)][:VERLAUF_MAX],", "for e in es][:VERLAUF_MAX],", 1),
    ("Befund: Verlauf ungedeckelt", "ue", "for e in reversed(es)][:VERLAUF_MAX],", "for e in reversed(es)],", 1),
    ("Zahnrad: Klick-Handler an jeder Zeile", "sbtn",
     "el.querySelectorAll('.jv-gear-tip-row[data-fokus]')", "el.querySelectorAll('.jv-gear-tip-row')", 1),
    ("Zahnrad: SSH-Alarm faerbt nicht rot", "sbtn",
     "(_badge.gesperrt || _badge.ssh_alarm || _badge.ue_alarm)", "(_badge.gesperrt || _badge.ue_alarm)", 1),
    ("Zahnrad: Benutzername unmaskiert", "sbtn", "var unten = [esc(sub),", "var unten = [sub,", 1),
]
NACHTRAG: dict = {}


def waechter(pfade):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
               JARVIS_UEBERW_PRUEFLING=str(pfade["ue"]), JARVIS_HAERTUNG_PRUEFLING=str(pfade["sh"]),
               JARVIS_MAIN_PRUEFLING=str(pfade["main"]), JARVIS_SYSLOAD_PRUEFLING=str(pfade["js"]),
               JARVIS_SBTN_PRUEFLING=str(pfade["sbtn"]))
    erg = []
    for argv in ([sys.executable, str(PY)], ["node", str(JS)],
                 [sys.executable, str(GEAR_PY)], ["node", str(GEAR_JS)]):
        p = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=240)
        # test_gear_badge*.py/js melden "FAIL", die B13-Waechter "✗"
        erg.append((p.returncode, p.stdout.count("✗") + len(re.findall(r"^\s*FAIL ", p.stdout, re.M))))
    return erg


def main():
    for f in list(QUELLEN.values()) + [PY, JS, GEAR_PY, GEAR_JS]:
        if not f.is_file():
            print("ABBRUCH: %s fehlt" % f)
            return 2
    if {p[1] for p in PROBEN} - set(QUELLEN):
        print("ABBRUCH: Probe auf eine Datei ohne Kopie")
        return 2
    original = {k: v.read_text(encoding="utf-8") for k, v in QUELLEN.items()}
    tmp = Path(tempfile.mkdtemp(prefix="gegen_ueberw_"))
    try:
        pfade = {k: tmp / v.name for k, v in QUELLEN.items()}

        def schreiben(wer, text):
            for k in QUELLEN:
                pfade[k].write_text(text if k == wer else original[k], encoding="utf-8")

        schreiben(None, "")
        basis = waechter(pfade)
        if any(rc != 0 for rc, _ in basis):
            print("ABBRUCH: Basislauf nicht gruen %s – keine Probe deutbar" % basis)
            return 2
        print("Basislauf gruen")
        stumm = 0
        for name, wer, alt, neu, n in PROBEN:
            text = original[wer]
            if text.count(alt) != n:
                print("  PROBE KAPUTT  %-50s Anker %d statt %d Treffer" % (name, text.count(alt), n))
                stumm += 1
                continue
            text = text.replace(alt, neu)
            if name in NACHTRAG:
                a2, n2 = NACHTRAG[name]
                if text.count(a2) != 1:
                    print("  PROBE KAPUTT  %-50s Nachtrag-Anker fehlt" % name)
                    stumm += 1
                    continue
                text = text.replace(a2, n2)
            schreiben(wer, text)
            erg = waechter(pfade)
            biss = any(rc == 1 and f > 0 for rc, f in erg) and not any(rc == 2 for rc, _ in erg)
            if biss:
                print("  beisst        %-50s %s" % (name, erg))
            else:
                print("  STUMM         %-50s %s" % (name, erg))
                stumm += 1
        print("ERGEBNIS: %d von %d Proben beissen" % (len(PROBEN) - stumm, len(PROBEN)))
        return 0 if stumm == 0 else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
