#!/usr/bin/env python3
"""Gegenprobe zu tests/test_mail_meldung.py.

Jede Probe sabotiert eine KOPIE von backend/ (in einem Wegwerf-Verzeichnis,
zusammen mit einer Kopie des Waechters) und laesst den Waechter dort laufen –
der Waechter rechnet REPO aus seinem eigenen Ort. Die Repo-Dateien werden nie
angefasst.

Erwartet je Probe: Exit 1 mit mindestens einem FAIL, nie Exit 2.
Vorab muss der Basislauf gegen die unveraenderte Kopie gruen sein.

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
WAECHTER = REPO / "tests" / "test_mail_meldung.py"
MM = "backend/mail_meldung.py"

# (Name, Datei relativ zum Repo, alt, neu, erwartete Trefferzahl von 'alt')
PROBEN = [
    ("Empfaengerpruefung offen", MM, 'if not _ADRESSE.match(t):', 'if False:', 1),
    ("Relay ohne Zeichenpruefung", MM, 'if not m or not _HOST.match(m.group(1)):', 'if not m:', 1),
    ("unbekannte Quelle erlaubt", MM, '        if w not in QUELLEN:\n            return [], "Unbekannte',
     '        if False:\n            return [], "Unbekannte', 1),
    ("Code wieder verlangt (Speichern)", "backend/broker/meta.py",
     '            fehler = f1 or f2 or f3 or f4 or f5 or f6\n',
     '            fehler = f1 or f2 or f3 or f4 or f5 or f6 or (_nachweis(args, by, op, audit_key, peer) or {}).get("error")\n', 1),
    ("Code wieder verlangt (Einrichten)", "backend/broker/meta.py",
     '        if aktion == "einrichten":\n            erg = mail_meldung.einrichten()',
     '        if aktion == "einrichten":\n            if _nachweis(args, by, op, audit_key, peer):\n                return {"ok": False}\n            erg = mail_meldung.einrichten()', 1),
    ("Absender wird nicht gespeichert", "backend/broker/meta.py",
     '"MAIL_ABSENDER": absender,', '', 1),
    ("Absender ungeprueft", MM, '    if t and not _ABSENDER.match(t):\n        return "", "Keine gültige Absender',
     '    if False:\n        return "", "Keine gültige Absender', 1),
    ("Absender wieder mit Punktpflicht", MM, '    if t and not _ABSENDER.match(t):', '    if t and not _ADRESSE.match(t):', 1),
    ("Name/Betreff mit Steuerzeichen", MM, '    if re.search(r"[\\x00-\\x1f\\x7f]", t):', '    if False:', 1),
    ("Umschlag-Absender fest", MM, '    r = _lauf([SENDMAIL, "-oi", "-f", _absender_adresse(k, fqdn), "--"]',
     '    r = _lauf([SENDMAIL, "-oi", "-f", "jarvis@" + fqdn, "--"]', 1),
    ("Betreff-Anfang fest", MM, '    praefix = (k.get("betreff") or VORGABE_BETREFF).replace("{server}", kurz)',
     '    praefix = VORGABE_BETREFF.replace("{server}", kurz)', 1),
    ("{server} nicht ersetzt", MM, '    name = (k.get("absender_name") or VORGABE_NAME).replace("{server}", kurz)',
     '    name = (k.get("absender_name") or VORGABE_NAME)', 1),
    ("Audit ohne Werte", "backend/broker/meta.py",
     '                     info=str(erg.get("gespeichert", ""))[:300], peer=peer)', '                     peer=peer)', 1),
    ("Postfix lauscht nach aussen", MM, '"inet_interfaces = loopback-only",', '"inet_interfaces = all",', 1),
    ("jeder darf abgeben", MM, '"authorized_submit_users = root",', '"authorized_submit_users = static:anyone",', 1),
    ("SMTP-Eingang bleibt an", MM, 'r2 = _lauf(["postconf", "-M#", "smtp/inet"], timeout=20)',
     'r2 = Erg_ok = type("E", (), {"returncode": 0, "stderr": ""})()', 1),
    ("Relay wird ignoriert", MM, '"relayhost = %s" % relay,', '"relayhost = ",', 1),
    ("root immer an die Empfaenger", MM,
     'if ("system" in k["quellen"] and k["empfaenger"]) else "/dev/null"',
     'if k["empfaenger"] else "/dev/null"', 1),
    ("fremde root-Zeile bleibt wirksam", MM, '            z = _AUSKOMMENTIERT + z\n', "            pass\n", 1),
    ("Quelle aus wird trotzdem gesendet", MM,
     '    if quelle != "test" and quelle not in k["quellen"]:', '    if False:', 1),
    ("keine Drosselung", MM, '    if d["anzahl"] >= GRENZE_JE_STUNDE.get(quelle, 10):', '    if False:', 1),
    ("Zurueckgehaltenes verschwiegen", MM, "    if unterdrueckt:\n        kopf +=", "    if False:\n        kopf +=", 1),
    ("Sicherheitsmail mit Inhalt", MM, '              ("Quelladresse", "ip"), ("Anzahl", "anzahl")]',
     '              ("Quelladresse", "ip"), ("Anzahl", "anzahl"), ("Text", "snippet")]', 1),
    ("Feldwerte mehrzeilig", MM, '    return re.sub(r"[\\r\\n\\t]+", " ", str(s or "")).strip()[:n]',
     '    return str(s or "")[:n]', 1),
    ("AIDE erklaert jede gemerkte Datei", MM,
     '        return _sha(_p(pfad).read_bytes()) == soll', "        return True", 1),
    ("Ueberwachung meldet nicht", "backend/ueberwachung.py", "    mail_melden(meldungen)\n", "", 1),
    ("AIDE-Abgleich meldet nicht", "backend/aide_abgleich.py", "    mail_melden(z)\n", "", 1),
    ("Dienst reicht beliebige Felder weiter", "backend/sicherheit_mail.py",
     "    for f in FELDER:\n        w = felder.get(f)", "    for f in felder:\n        w = felder.get(f)", 1),
    ("Sperre nicht gemeldet", "backend/security_guard.py",
     '        _mail("konto_gesperrt_angriff", benutzer=user, kanal=channel,', '        print("konto_gesperrt_angriff", user, channel,', 1),
    ("Update startet Broker nicht fuer Mailmodul", "backend/update_manager.py",
     '"backend/mail_meldung.py", ', "", 1),
    ("6j aus /opt/jarvis statt Broker-Kopie", "start_jarvis_root.sh",
     'MAIL_PROG="$CODE_DIR/backend/mail_meldung.py"', 'MAIL_PROG="/opt/jarvis/backend/mail_meldung.py"', 1),
    ("6j installiert nie", "start_jarvis_root.sh",
     "MAIL_AKTION=--anwenden; else MAIL_AKTION=--einrichten", "MAIL_AKTION=--anwenden; else MAIL_AKTION=--anwenden", 1),
    ("Auto-Sperre mit Befehlstext", "backend/security_guard.py",
     '_mail("konto_gesperrt_verstoss", benutzer=user, kanal=channel, muster=kind, ip=ip)',
     '_mail("konto_gesperrt_verstoss", benutzer=user, kanal=channel, muster=kind, ip=ip, detail=detail)', 1),
]


def lauf(wurzel: Path) -> tuple[int, int, str]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([sys.executable, str(wurzel / "tests" / "test_mail_meldung.py")],
                       env=env, capture_output=True, text=True, timeout=180, cwd=str(wurzel))
    return p.returncode, len(re.findall(r"^\s*FAIL ", p.stdout, re.M)), p.stdout + p.stderr


def main() -> int:
    if not WAECHTER.is_file():
        print("ABBRUCH: Waechter fehlt")
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="gegen_mail_"))
    try:
        (tmp / "tests").mkdir()
        shutil.copy2(WAECHTER, tmp / "tests" / WAECHTER.name)
        shutil.copytree(REPO / "backend", tmp / "backend",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copy2(REPO / "start_jarvis_root.sh", tmp / "start_jarvis_root.sh")
        original = {}
        for _, datei, alt, _, soll in PROBEN:
            text = original.setdefault(datei, (REPO / datei).read_text(encoding="utf-8"))
            n = text.count(alt)
            if n != soll:
                print("ABBRUCH: Anker in %s %dx gefunden (erwartet %d): %r" % (datei, n, soll, alt[:70]))
                return 2
        rc, fails, aus = lauf(tmp)
        if rc != 0 or fails:
            print("ABBRUCH: Basislauf nicht gruen (Exit %d, %d FAIL)\n%s" % (rc, fails, aus[-1500:]))
            return 2
        print("Basislauf gruen")
        stumm = 0
        for name, datei, alt, neu, _ in PROBEN:
            ziel = tmp / datei
            ziel.write_text(original[datei].replace(alt, neu), encoding="utf-8")
            try:
                rc, fails, aus = lauf(tmp)
            finally:
                ziel.write_text(original[datei], encoding="utf-8")
            if rc == 1 and fails:
                print("  BEISST  %-42s %d FAIL" % (name, fails))
            else:
                stumm += 1
                print("  STUMM   %-42s Exit %d, %d FAIL" % (name, rc, fails))
                print("          " + "\n          ".join(aus.strip().splitlines()[-4:]))
        print("\nERGEBNIS: %d/%d Proben beissen" % (len(PROBEN) - stumm, len(PROBEN)))
        return 1 if stumm else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
