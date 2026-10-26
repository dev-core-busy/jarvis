#!/usr/bin/env python3
"""Gegenprobe zu tests/test_bsi_n.py: beisst der Waechter?

Jede Probe dreht EINEN Teil der N1–N6-Behebung zurueck (Python-Ersetzung
ganzer Zeilen), laesst den Waechter laufen und erwartet mindestens einen FAIL.
Vorher gruener Basislauf, danach Byte-Gleichheit aller Dateien per md5. Ohne
Bytecode.

Bewusst NICHT als Probe: "Pruefen und Merken ohne Lock". Der Waechter misst
das mit 12 gleichzeitigen Faeden, aber ohne kuenstliche Verzoegerung zwischen
Lesen und Schreiben trifft ein Thread-Wechsel unter dem GIL das Fenster nur
zufaellig – eine Probe, die mal beisst und mal nicht, waere keine Messung.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_bsi_n.py"
MAIN = "backend/main.py"
TS = "backend/totp_schutz.py"
HU = "backend/http_umleitung.py"
APP = "frontend/js/app.js"
START = "start_jarvis.sh"
DI = "deploy_instructions.sh"
SEC = "backend/security.py"

PROBEN = [
    # ── N1 ──
    ("health ohne Admin-Pruefung (Details fuer alle)", MAIN,
     "    try:\n        await require_local_auth(request)\n    except HTTPException:\n"
     "        return JSONResponse({\"status\": \"ok\"})\n    errors = config.validate()\n",
     "    errors = config.validate()\n"),
    ("Neustart-Knopf schickt kein Token an /api/health", APP,
     "                        cache: 'no-store',\n"
     "                        headers: { 'Authorization': `Bearer ${token}` }\n",
     "                        cache: 'no-store'\n"),
    # ── N2 ──
    ("Umleitung uebernimmt den Host-Kopf", HU,
     "    if gewuenscht and gewuenscht in namen:\n"
     "        host = gewuenscht\n"
     "    else:\n"
     "        brauchbar = [n for n in namen if taugt_als_rueckfall(n)]\n"
     "        if not brauchbar:\n"
     "            return None\n"
     "        host = brauchbar[0]\n",
     "    host = gewuenscht or namen[0]\n"),
    ("Rueckfall ohne Brauchbarkeitsfilter (Sprung auf den Rechnernamen)", HU,
     "        brauchbar = [n for n in namen if taugt_als_rueckfall(n)]\n",
     "        brauchbar = list(namen)\n"),
    # ── N2: deckt das Zertifikat die eigene Adresse? ──
    ("Adress-Ermittlung ruft wieder nach draussen", SEC,
     '    ips = set()\n    server_ip = os.getenv("SERVER_IP", "")\n',
     '    ips = set()\n'
     '    ips.add(subprocess.run(["curl", "-s", "http://ifconfig.me"],\n'
     '                           capture_output=True, text=True).stdout.strip())\n'
     '    server_ip = os.getenv("SERVER_IP", "")\n'),
    ("Adress-Ermittlung nimmt das Gateway wieder mit", SEC,
     '        result = subprocess.run(["ip", "-4", "addr", "show", "scope", "global"],\n',
     '        result = subprocess.run(["ip", "route"],\n'),
    ("ohne lesbare Namen wird doch etwas behauptet (fail-open)", SEC,
     '    if not namen:\n        return ""                     '
     '# nicht ermittelbar -> nichts behaupten\n', ""),
    ("eigene Adresse im SAN zaehlt nicht mehr (Laerm auf frischem Zertifikat)", SEC,
     '    if any(a in namen for a in eigene):\n'
     '        return ""                     # (a) meine Adresse steht drin\n', ""),
    ("aufloesbarer DNS-Name zaehlt nicht mehr (Laerm auf ECHT)", SEC,
     '    if any(taugt_als_rueckfall(n) for n in namen if not _ist_ip(n)):\n'
     '        return ""                     # (b) ein aufloesbarer DNS-Name steht drin\n', ""),
    ("fremde IP gilt wieder als aufloesbarer Name (veraltetes Zert wird still)", SEC,
     "    if any(taugt_als_rueckfall(n) for n in namen if not _ist_ip(n)):\n",
     "    if any(taugt_als_rueckfall(n) for n in namen):\n"),
    ("Startpfad meldet die Abweichung nicht mehr", SEC,
     "        grund = zertifikat_adress_warnung()\n",
     '        grund = ""\n'),
    (".local gilt wieder als brauchbarer Rueckfall", HU,
     "        return not (name == \"local\" or name.endswith(\".local\"))\n",
     "        return True\n"),
    ("einteiliger Rechnername gilt wieder als brauchbar", HU,
     "        if \".\" not in name:                       # einteilig\n"
     "            return False\n", ""),
    ("Platzhalter-Namen gelten als Ziel", HU,
     "    dns = [d for d in dns if d and \"*\" not in d]\n", ""),
    ("ohne Zertifikat Rueckfall auf den Host-Kopf", HU,
     "    if not namen:\n        return None\n",
     "    if not namen:\n        return \"https://%s%s\" % (_host_ohne_port(host_kopf), pfad)\n"),
    ("'//' am Pfadanfang bleibt stehen", HU,
     "    pfad = \"/\" + (pfad or \"\").lstrip(\"/\")\n",
     "    pfad = pfad or \"/\"\n"),
    # ── N3 ──
    ("Zeitschritt-Merker wird ignoriert", TS,
     "        if schluessel and schritt <= _schritte.get(schluessel, -1):\n",
     "        if False:\n"),
    ("nur exakt derselbe Schritt gesperrt (Vorschritt geht durch)", TS,
     "        if schluessel and schritt <= _schritte.get(schluessel, -1):\n",
     "        if schluessel and schritt == _schritte.get(schluessel, -1):\n"),
    ("Merker nur je Konto (Secret-Wechsel gilt als Wiederholung)", TS,
     "    schluessel = (\"%s|%s\" % (konto, hashlib.sha256(secret.encode()).hexdigest()[:12])\n",
     "    schluessel = (\"%s|%s\" % (konto, \"\")\n"),
    ("Merker nur im Speicher", TS,
     "        if STORE_PATH.exists():\n", "        if False:\n"),
    ("Login prueft wieder selbst per pyotp", MAIN,
     "            _totp_erg = _totp_schutz.pruefen(_norm_login(username), user_state[\"totp_secret\"],\n"
     "                                             totp_code)\n",
     "            import pyotp\n"
     "            _totp_erg = (_totp_schutz.OK if pyotp.TOTP(user_state[\"totp_secret\"])"
     ".verify(totp_code, valid_window=1) else _totp_schutz.FALSCH)\n"),
    ("Bestaetigung prueft wieder selbst per pyotp", MAIN,
     "                ok = _totp_schutz.pruefen(_norm_login(user), geheim, code) == _totp_schutz.OK\n",
     "                import pyotp\n"
     "                ok = bool(pyotp.TOTP(geheim).verify(code, valid_window=1))\n"),
    # ── N4 ──
    ("Kennwortwechsel ohne Schranke", MAIN,
     "    # Altes Kennwort prüfen – mit derselben Grenze wie beim Login (BSI N4)\n"
     "    schranke = _kennwort_schranke(request, username)\n"
     "    if schranke is not None:\n        return schranke\n",
     "    # Altes Kennwort prüfen\n"),
    ("2FA-Abschaltung zaehlt keinen Fehlversuch", MAIN,
     "        _kennwort_fehlversuch(request, username, \"totp_disable\")\n", ""),
    ("2FA-Neueinrichtung ohne Schranke", MAIN,
     "        schranke = _kennwort_schranke(request, username)\n"
     "        if schranke is not None:\n            return schranke\n", ""),
    ("Schranke ignoriert die IP-Grenze", MAIN,
     "    if not _check_rate_limit(ip):\n"
     "        return JSONResponse(\n"
     "            {\"success\": False, \"error\": \"Zu viele Fehlversuche von dieser Adresse. \"\n",
     "    if False:\n"
     "        return JSONResponse(\n"
     "            {\"success\": False, \"error\": \"Zu viele Fehlversuche von dieser Adresse. \"\n"),
    ("Fehlversuch ohne Konto (nur IP)", MAIN,
     "    _record_login_attempt(ip, username)\n    _sicherheits_log.ereignis(\"kennwort_pruefung\"",
     "    _record_login_attempt(ip)\n    _sicherheits_log.ereignis(\"kennwort_pruefung\""),
    # ── N5 ──
    ("Startskript ohne --no-server-header", START,
     "    --no-server-header \\\n", ""),
    ("Umleitungs-Server mit Banner", MAIN,
     "    redirect_cfg = uvicorn.Config(redirect_app, host=\"0.0.0.0\", port=80, log_level=\"warning\",\n"
     "                                  server_header=False)\n",
     "    redirect_cfg = uvicorn.Config(redirect_app, host=\"0.0.0.0\", port=80, log_level=\"warning\")\n"),
    # ── N6 ──
    ("fester Schluesselpfad im Deploy-Skript", DI,
     "SSH_KEY_PATH=\"${JARVIS_SSH_KEY:-$HOME/.ssh/id_rsa}\"\n",
     "SSH_KEY_PATH=\"/c/users/bender/.ssh/id_rsa\"\n"),
]

DATEIEN = [MAIN, TS, HU, APP, START, DI, SEC, "tests/test_bsi_n.py"]


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def lauf() -> tuple[int, int]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, str(WAECHTER)], capture_output=True, text=True,
                       timeout=300, cwd=str(ROOT), env=env)
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", r.stdout)
    if r.returncode == 2 or not m:
        return -1, r.returncode
    return int(m.group(2)), r.returncode


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
                print("  BISS %-60s %d FAIL" % (name, fails))
            elif fails < 0:
                print("  ABBR %-60s Waechter konnte nicht laufen (rc=%s)" % (name, rc))
            else:
                print("  ZAHN %-60s 0 FAIL – beisst NICHT" % name)
    finally:
        for d, inhalt in sicherung.items():
            (ROOT / d).write_bytes(inhalt)

    nachher = {d: md5(d) for d in DATEIEN}
    if nachher != vorher:
        print("\nABBRUCH: Dateien nach der Probe nicht byte-gleich: %s"
              % [d for d in DATEIEN if nachher[d] != vorher[d]])
        return 2
    print("\n%d/%d Proben beissen (Dateien byte-gleich wiederhergestellt)" % (beissen, len(PROBEN)))
    return 0 if beissen == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
