#!/usr/bin/env python3
"""Gegenprobe zu tests/test_sitzung_h3.py und tests/test_broker_socket_eigen.py.

Jede Probe dreht EINEN Teil des Fixes zurueck (Python-Ersetzung ganzer Zeilen),
laesst den zustaendigen Waechter laufen und erwartet mindestens einen FAIL.
Vorher gruene Basislaeufe, danach Byte-Gleichheit aller Dateien per md5. Ohne
Bytecode (``PYTHONDONTWRITEBYTECODE=1``) – sonst laedt ein spaeterer Lauf ggf.
die Sabotage aus einer .pyc.

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
H3 = ROOT / "tests" / "test_sitzung_h3.py"
BR = ROOT / "tests" / "test_broker_socket_eigen.py"
MAIN = "backend/main.py"
ST = "backend/sitzung_token.py"
SB = "backend/sandbox.py"
APP = "frontend/js/app.js"
DAEMON = "backend/broker/daemon.py"

PROBEN = [
    ("verify_token fragt die Buchhaltung nicht", H3, MAIN,
     "            if not _sitzung.pruefe_und_beruehre(sig, int(ts)):\n",
     "            if False:\n"),
    ("Laufzeit wird nicht geprueft", H3, ST,
     "    if alter > max_s or alter < -ZUKUNFT_TOLERANZ:\n",
     "    if alter < -ZUKUNFT_TOLERANZ:\n"),
    ("Zukunfts-Zeitstempel wird angenommen", H3, ST,
     "    if alter > max_s or alter < -ZUKUNFT_TOLERANZ:\n",
     "    if alter > max_s:\n"),
    ("Leerlauf wird nicht geprueft", H3, ST,
     "        if jetzt - zuletzt > idle_s:\n",
     "        if False:\n"),
    ("unbekanntes Token bekommt Vorschuss", H3, ST,
     "        zuletzt = _zuletzt.get(k, float(ts))\n",
     "        zuletzt = _zuletzt.get(k, jetzt)\n"),
    ("Anfrage setzt den Leerlauf nicht zurueck", H3, ST,
     "        _zuletzt[k] = jetzt\n",
     "        pass\n"),
    ("Widerruf je Token wirkungslos", H3, ST,
     "        if k in _widerrufen:\n",
     "        if False:\n"),
    ("Widerruf nicht sofort auf Platte", H3, ST,
     "        _ohne_admin.pop(k, None)\n        _dirty = True\n        _schreiben_unlocked()\n",
     "        _ohne_admin.pop(k, None)\n        _dirty = True\n"),
    ("Einstellung 0 heisst wieder 'aus'", H3, ST,
     "            v = float(_get_setting(\"sitzung_max_stunden\", MAX_STUNDEN_VORGABE))\n"
     "            if v > 0:\n",
     "            v = float(_get_setting(\"sitzung_max_stunden\", MAX_STUNDEN_VORGABE))\n"
     "            if v > 0 or v == 0:\n"),
    ("Ablage ohne privat_machen", H3, ST,
     "            privat_machen(tmp)\n",
     "            pass\n"),
    ("logout widerruft nichts", H3, MAIN,
     "        _sitzung.widerrufe(_sig, int(_ts))\n",
     "        pass\n"),
    ("Kennwortwechsel ohne Epoche", H3, MAIN,
     "    _revoked_logins[_norm_login(username)] = rev\n",
     "    pass\n"),
    ("Ersatz-Token in derselben Sekunde wie die Epoche", H3, MAIN,
     "    return generate_token(username, ts=rev + 1, mit_2fa=mit_2fa, ohne_admin=ohne_admin)\n",
     "    return generate_token(username, ts=rev, mit_2fa=mit_2fa, ohne_admin=ohne_admin)\n"),
    ("Docker-Zweig ohne Ersatz-Token", H3, MAIN,
     "        print(f\"[AUTH] Docker-Kennwort für '{username}' erfolgreich geändert.\", flush=True)\n"
     "        return _sitzung_antwort(request, {\"success\": True, \"token\": _sitzungen_nach_kennwortwechsel(username, request)})\n",
     "        print(f\"[AUTH] Docker-Kennwort für '{username}' erfolgreich geändert.\", flush=True)\n"
     "        return _sitzung_antwort(request, {\"success\": True})\n"),
    ("AD-Login hebt den Widerruf wieder auf", H3, MAIN,
     "                    print(f\"[AUTH] AD-Login erfolgreich: {bind_user}\", flush=True)\n",
     "                    if _revoked_logins.pop(plain_key, None) is not None:\n"
     "                        _save_revocations()\n"
     "                    print(f\"[AUTH] AD-Login erfolgreich: {bind_user}\", flush=True)\n"),
    ("Revalidierung ueberspringt wieder jeden Widerrufenen", H3, MAIN,
     "    return rev is not None and zuletzt_aktiv <= rev\n",
     "    return rev is not None\n"),
    ("alte Epochen werden nicht aufgeraeumt", H3, MAIN,
     "        _revoked_logins.pop(_u, None)\n",
     "        pass\n"),
    ("Ablage fehlt in der Start-Haertung", H3, SB,
     "                 \"data/auth_sitzungen.json\",\n",
     ""),
    ("Einstellungs-Dialog uebernimmt das Token nicht", H3, APP,
     "                    _uebernimmErsatzToken(data.token);\n                    hideChangePwModal();\n",
     "                    hideChangePwModal();\n"),
    ("Sicherheits-Reiter uebernimmt das Token nicht", H3, APP,
     "                        _uebernimmErsatzToken(data.token);\n                        if (oldEl) oldEl.value = '';\n",
     "                        if (oldEl) oldEl.value = '';\n"),
    ("Helfer setzt die Variable token nicht", H3, APP,
     "        token = neu;\n",
     "        void neu;\n"),
    ("Broker loescht beim Beenden blind", BR, DAEMON,
     "    elif jetzt == eigener:\n",
     "    elif True:\n"),
    ("Broker meldet bei jedem Neustart einen fremden Broker", BR, DAEMON,
     "    if jetzt is None:\n        pass\n    elif jetzt == eigener:\n",
     "    if jetzt == eigener:\n"),
]

DATEIEN = sorted({p[2] for p in PROBEN})


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def lauf(waechter: Path) -> tuple[int, int]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, str(waechter)], capture_output=True, text=True,
                       timeout=300, cwd=str(ROOT), env=env)
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", r.stdout)
    if r.returncode == 2 or not m:
        return -1, r.returncode
    return int(m.group(2)), r.returncode


def main() -> int:
    if {p[2] for p in PROBEN} - set(DATEIEN):
        print("ABBRUCH: Probe fasst eine nicht gesicherte Datei an")
        return 2
    sicherung = {d: (ROOT / d).read_bytes() for d in DATEIEN}
    vorher = {d: md5(d) for d in DATEIEN}

    for w in (H3, BR):
        fails, rc = lauf(w)
        if fails != 0:
            print("ABBRUCH: Basislauf %s nicht gruen (FAIL=%s, rc=%s)" % (w.name, fails, rc))
            return 2
    print("Basislaeufe gruen.\n")

    beissen = 0
    try:
        for name, waechter, datei, alt, neu in PROBEN:
            pfad = ROOT / datei
            text = pfad.read_text(encoding="utf-8")
            if text.count(alt) != 1:
                print("  ???  %s – Anker %dx gefunden" % (name, text.count(alt)))
                continue
            pfad.write_text(text.replace(alt, neu), encoding="utf-8")
            try:
                fails, rc = lauf(waechter)
            finally:
                pfad.write_bytes(sicherung[datei])
            if fails > 0:
                beissen += 1
                print("  BISS %-58s %d FAIL" % (name, fails))
            elif fails < 0:
                print("  ABBR %-58s Waechter konnte nicht laufen (rc=%s)" % (name, rc))
            else:
                print("  ZAHN %-58s 0 FAIL – beisst NICHT" % name)
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
