#!/usr/bin/env python3
"""Gegenprobe zu tests/test_bsi_hoch.py: beisst der Waechter?

Jede Probe dreht EINEN Fix zurueck (Python-Ersetzung ganzer Zeilen), laesst den
Waechter laufen und erwartet mindestens einen FAIL. Vorher gruener Basislauf,
danach Byte-Gleichheit aller Dateien per md5.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_bsi_hoch.py"
MAIN = "backend/main.py"
KV = "backend/kundenverwaltung_client.py"
SET = "frontend/settings.html"

PROBEN = [
    ("H2: setup schreibt wieder totp_secret + totp_enabled=False", MAIN,
     '    _set_user_auth_state(username, {"totp_pending_secret": secret})\n',
     '    _set_user_auth_state(username, {"totp_secret": secret, "totp_enabled": False})\n'),
    ("H2: Kennwort-Schranke bei aktiver 2FA entfernt", MAIN,
     '    user_state = _get_user_auth_state(username)\n'
     '    if user_state.get("totp_enabled") and user_state.get("totp_secret"):\n'
     '        try:\n',
     '    user_state = _get_user_auth_state(username)\n'
     '    if False:\n'
     '        try:\n'),
    ("H2: verify nimmt wieder totp_secret statt des vorgemerkten", MAIN,
     '    secret = user_state.get("totp_pending_secret")\n',
     '    secret = user_state.get("totp_secret")\n'),
    # Code-Review 2026-10-07: App-Sitzung tauscht den Faktor nicht aus
    ("Review: setup ohne App-Sperre", MAIN,
     '        return sperre\n'
     '    user_state = _get_user_auth_state(username)\n'
     '    if user_state.get("totp_enabled") and user_state.get("totp_secret"):\n',
     '        pass\n'
     '    user_state = _get_user_auth_state(username)\n'
     '    if user_state.get("totp_enabled") and user_state.get("totp_secret"):\n'),
    ("Review: verify ohne App-Sperre", MAIN,
     '        return sperre\n'
     '    body = await request.json()\n'
     '    code = body.get("code", "").strip()\n',
     '        pass\n'
     '    body = await request.json()\n'
     '    code = body.get("code", "").strip()\n'),
    ("Review: disable ohne App-Sperre", MAIN,
     '        return sperre\n'
     '    body = await request.json()\n'
     '    password = body.get("password", "")\n',
     '        pass\n'
     '    body = await request.json()\n'
     '    password = body.get("password", "")\n'),
    ("Review: App-Erkennung immer falsch", MAIN,
     '    return bool(kx is not None and kx[0] == _norm_login(user) and len(kx) > 2 and kx[2])\n',
     '    return False\n'),
    ("Review: App-Erkennung ignoriert das Konto", MAIN,
     '    return bool(kx is not None and kx[0] == _norm_login(user) and len(kx) > 2 and kx[2])\n',
     '    return bool(kx is not None and len(kx) > 2 and kx[2])\n'),
    ("Review: verify befoerdert die Sitzung wieder", MAIN,
     '    return JSONResponse({"success": True, "message": "2FA aktiviert"})\n',
     '    try:\n'
     '        _u, _ts, _sig = request.headers.get("Authorization", "").replace("Bearer ", "").split(":", 2)\n'
     '        _sitzung.setze_mit_2fa(_sig, int(_ts))\n'
     '    except Exception:\n'
     '        pass\n'
     '    return JSONResponse({"success": True, "message": "2FA aktiviert"})\n'),
    ("H12: Rueckfall auf anonymous", MAIN,
     '    else:\n'
     '        return JSONResponse({"success": False, "error": "Nicht authentifiziert"}, status_code=401)\n',
     '    else:\n'
     '        user = "anonymous"\n'),
    ("H12: Sperren fuer Sitzungstoken entfernt", MAIN,
     '        if _user_must_change(user) or security_guard.is_blocked(user) \\\n',
     '        if False and _user_must_change(user) or False \\\n'),
    ("H14: Rueckfall ohne Anker wieder CERT_NONE", KV,
     '        return ctx\n'
     '    return ssl.create_default_context()\n',
     '        return ctx\n'
     '    _c = ssl.create_default_context()\n'
     '    _c.check_hostname = False\n'
     '    _c.verify_mode = ssl.CERT_NONE\n'
     '    return _c\n'),
    ("H14: Anker wird ignoriert", KV,
     '    if ziel and sap_cert.passt(eintrag, *ziel):\n',
     '    if False:\n'),
    ("H14: Anker gilt fuer jeden Host/Port", KV,
     '    if ziel and sap_cert.passt(eintrag, *ziel):\n',
     '    if isinstance(eintrag, dict) and eintrag.get("pem"):\n'),
    ("H14: Namensabgleich immer aus", KV,
     '        if eintrag.get("name_abweichung"):\n',
     '        if True:\n'),
    ("H14: Container im Reiter fehlt", SET,
     '                        <div class="sapcert" id="kv-cert" style="margin-top:10px;"></div>\n',
     ''),
]

DATEIEN = sorted({p[1] for p in PROBEN})


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def lauf() -> tuple[int, int]:
    r = subprocess.run([sys.executable, str(WAECHTER)], capture_output=True, text=True,
                       timeout=300, cwd=str(ROOT))
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
