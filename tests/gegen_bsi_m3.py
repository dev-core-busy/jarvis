#!/usr/bin/env python3
"""Gegenprobe zu tests/test_bsi_m3.py: beisst der Waechter?

Jede Probe dreht EINEN Teil des M3-Fixes zurueck (Python-Ersetzung ganzer
Zeilen), laesst den Waechter laufen und erwartet mindestens einen FAIL. Vorher
gruener Basislauf, danach Byte-Gleichheit aller Dateien per md5. Ohne Bytecode.

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
WAECHTER = ROOT / "tests" / "test_bsi_m3.py"
MAIN = "backend/main.py"
AS = "backend/anmelde_schutz.py"
ST = "backend/sitzung_token.py"
CLIENT = "ai-mouse/src/AiMouse/Vision/JarvisClient.cs"

PROBEN = [
    # ── Konto-Sperre ──
    ("Login prueft die Konto-Sperre nicht", MAIN,
     "    _gesperrt = _konto_sperre_antwort(username)\n    if _gesperrt is not None:\n        return _gesperrt\n",
     "    _gesperrt = _konto_sperre_antwort(username)\n"),
    ("Fehlversuch nur noch je IP", MAIN,
     '    if _anmelde_schutz.fehlversuch(ip, _norm_login(username) if username else ""):\n',
     '    if _anmelde_schutz.fehlversuch(ip, ""):\n'),
    # ⚠ Die Einrueckung ist seit 2026-10-20 um eine Stufe tiefer: der Zweig liegt
    # jetzt im ``else`` der Weiche "Geheimnis im Broker?" (ein Authenticator-
    # Eintrag fuer Anmeldung UND Root-Freigaben). Der alte Anker mit acht
    # Leerzeichen traf nichts mehr, und der Harness meldete dafuer
    # "Anker 0x gefunden" – das sah in der Bilanz wie eine stumme Probe aus und
    # hat eine halbe Stunde Fehlersuche am falschen Ende gekostet. Ein kuerzerer
    # Anker geht nicht: ``_record_login_attempt(client_ip, username)`` kommt
    # mehrfach vor (gemessen: 2x mit dieser, 5x mit geringerer Einrueckung).
    ("Falscher 2FA-Code zaehlt nur fuer die IP", MAIN,
     "            if _totp_erg != _totp_schutz.OK:\n"
     "                _record_login_attempt(client_ip, username)\n"
     "                return JSONResponse(\n"
     "                    {\"success\": False, \"requires_totp\": True,\n",
     "            if _totp_erg != _totp_schutz.OK:\n"
     "                _record_login_attempt(client_ip)\n"
     "                return JSONResponse(\n"
     "                    {\"success\": False, \"requires_totp\": True,\n"),
    ("Erfolg setzt den Konto-Zaehler nicht zurueck", MAIN,
     "    token = generate_token(username, mit_2fa=_mit_2fa, ohne_admin=_ohne_admin,\n"
     "                           nur_ai_maus=_ai_maus)\n"
     "    _anmelde_schutz.erfolg(_norm_login(username))\n",
     "    token = generate_token(username, mit_2fa=_mit_2fa, ohne_admin=_ohne_admin,\n"
     "                           nur_ai_maus=_ai_maus)\n"),
    ("Zaehler nur im Speicher (Datei wird nie gelesen)", AS,
     "        if STORE_PATH.exists():\n            d = json.loads(",
     "        if False:\n            d = json.loads("),
    ("Sperre laeuft nie ab", AS,
     "        return max(1, int(bis - jetzt) + 1) if bis > jetzt else 0\n",
     "        return max(1, int(bis - jetzt) + 1) if bis else 0\n"),
    # ── 2FA-Pflicht beim Login ──
    ("Keine Pflicht-Einrichtung fuer Admins", MAIN,
     "    elif _admin_2fa_pflicht() and _is_admin_user(username):\n",
     "    elif False:\n"),
    ("Einrichtung prueft den Code nicht", MAIN,
     "        if _totp_erg != _totp_schutz.OK:\n"
     "            _record_login_attempt(client_ip, username)\n"
     "            return JSONResponse({\"success\": False, \"requires_totp_setup\": True,\n",
     "        if False:\n"
     "            _record_login_attempt(client_ip, username)\n"
     "            return JSONResponse({\"success\": False, \"requires_totp_setup\": True,\n"),
    ("Token nach 2FA ohne Merkmal", MAIN,
     "    token = generate_token(username, mit_2fa=_mit_2fa, ohne_admin=_ohne_admin,\n",
     "    token = generate_token(username, ohne_admin=_ohne_admin,\n"),
    ("Pflicht-Schalter wird ignoriert (immer an)", MAIN,
     '    return not (v is False or str(v).strip().lower() in ("false", "0", "nein", "off"))\n',
     "    return True\n"),
    # ── Admin-Rechte an der Sitzung ──
    ("verify_token setzt keinen Sitzungskontext", MAIN,
     "            _sitzung_kontext.set((_norm_login(username), _sitzung.mit_2fa(sig),\n"
     "                                  _sitzung.ohne_admin(sig)))\n", ""),
    ("_user_is_admin ignoriert die Sitzung", MAIN,
     "    if _sitzung_ohne_admin(u):\n        return False\n", ""),
    ("_is_admin_user wieder mit ALLOWED_USERS-Abkuerzung", MAIN,
     "    return _user_is_admin(username)\n",
     "    return (username in ALLOWED_USERS) or _user_is_admin(username)\n"),
    ("require_local_auth wieder mit ALLOWED_USERS-Abkuerzung", MAIN,
     "    if not _user_is_admin(username):\n"
     "        raise HTTPException(status_code=403, detail=_admin_verweigert_text(username))\n",
     "    if username not in ALLOWED_USERS and not _user_is_admin(username):\n"
     "        raise HTTPException(status_code=403, detail=_admin_verweigert_text(username))\n"),
    ("Kennwortwechsel erbt das Merkmal nicht", MAIN,
     "            mit_2fa = _sitzung.mit_2fa(_sig)\n", "            mit_2fa = False\n"),
    ("Kennwortwechsel macht JEDE Sitzung zu 'mit 2FA'", MAIN,
     "    return generate_token(username, ts=rev + 1, mit_2fa=mit_2fa, ohne_admin=ohne_admin)\n",
     "    return generate_token(username, ts=rev + 1, mit_2fa=True, ohne_admin=ohne_admin)\n"),
    ("totp_disable ohne Pflicht-Pruefung", MAIN,
     "    if _konto_admin and _admin_2fa_pflicht():\n", "    if False:\n"),
    ("Add-in-SSO stellt Token 'mit 2FA' aus", MAIN,
     "    token = generate_token(username)\n"
     "    try:\n"
     "        _user_sessions.record_login(username, client_ip, display=_display_name(username))\n",
     "    token = generate_token(username, mit_2fa=True)\n"
     "    try:\n"
     "        _user_sessions.record_login(username, client_ip, display=_display_name(username))\n"),
    ("Merkmal wird nicht gespeichert", ST,
     '"mit_2fa": _mit_2fa, "ohne_admin": _ohne_admin,',
     '"ohne_admin": _ohne_admin,'),
    # ── Apps ──
    ("Merkmal 'ohne Admin' wird nicht gespeichert", ST,
     '"mit_2fa": _mit_2fa, "ohne_admin": _ohne_admin,',
     '"mit_2fa": _mit_2fa,'),
    ("App-Erkennung kennt die bestehenden Apps nicht", MAIN,
     '    return ua.startswith("okhttp/") or ua.startswith("go-http-client/")\n',
     '    return False\n'),
    ("App-Erkennung trifft 'okhttp' irgendwo im Text", MAIN,
     '    return ua.startswith("okhttp/") or ua.startswith("go-http-client/")\n',
     '    return "okhttp" in ua or ua.startswith("go-http-client/")\n'),
    ("App-Zweig auch fuer Nicht-Admins (2FA-Umweg)", MAIN,
     "    _ohne_admin = _ai_maus or (_ist_app_anmeldung(request, body) and _is_admin_user(username))\n",
     "    _ohne_admin = _ai_maus or _ist_app_anmeldung(request, body)\n"),
    ("App-Token ohne Merkmal", MAIN,
     "    token = generate_token(username, mit_2fa=_mit_2fa, ohne_admin=_ohne_admin,\n",
     "    token = generate_token(username, mit_2fa=_mit_2fa,\n"),
    ("Merkmal 'ohne Admin' wird bei der Pruefung ignoriert", MAIN,
     "    if len(kx) > 2 and kx[2]:\n        return True\n", ""),
    ("Login-Antwort meldet die Konto- statt der Sitzungsrechte", MAIN,
     "    _sitzung_kontext.set((_norm_login(username), _mit_2fa, _ohne_admin))\n", ""),
    ("Kennwortwechsel verliert 'ohne Admin'", MAIN,
     "            ohne_admin = _sitzung.ohne_admin(_sig)\n", ""),
    # ── AI-Maus (2026-10-27): ohne 2FA, nur eigene Schnittstellen ──
    ("AI-Maus wird nicht erkannt", MAIN,
     '    return str((body or {}).get("client") or "").strip().lower() == "ai-mouse"\n',
     "    return False\n"),
    ("AI-Maus-Sitzung nicht 'ohne Admin'", MAIN,
     "    _ohne_admin = _ai_maus or (_ist_app_anmeldung(request, body) and _is_admin_user(username))\n",
     "    _ohne_admin = _ist_app_anmeldung(request, body) and _is_admin_user(username)\n"),
    ("AI-Maus-Token ohne Merkmal 'nur AI-Maus'", MAIN,
     "                           nur_ai_maus=_ai_maus)\n", "                           )\n"),
    ("verify_token prueft den Pfad nicht", MAIN,
     "            if not _sitzung.pfad_erlaubt(sig):\n                return None\n", ""),
    ("Pfad-Middleware nicht registriert", MAIN,
     "app.add_middleware(_AnfragePfadMiddleware)\n", ""),
    ("unbekannter Pfad gilt als erlaubt", ST,
     "    if not isinstance(pfad, str):\n        return False\n",
     "    if not isinstance(pfad, str):\n        return True\n"),
    ("AI-Maus-Admin-Seiten nicht gesperrt", ST,
     "    return pfad.startswith(AI_MAUS_PFADE) and not pfad.startswith(AI_MAUS_GESPERRT)\n",
     "    return pfad.startswith(AI_MAUS_PFADE)\n"),
    ("Merkmal 'nur AI-Maus' wird nicht gespeichert", ST,
     '                                   "nur_ai_maus": _nur_ai_maus,\n', ""),
    ("Merkmal 'nur AI-Maus' wird nicht vermerkt", ST,
     "        if nur_ai_maus:\n            _nur_ai_maus[schluessel(sig)] = int(ts)\n", ""),
    ("AI-Maus schickt keine Kennung", CLIENT,
     '            ["client"] = "ai-mouse",\n', ""),
]

DATEIEN = [MAIN, AS, ST, CLIENT, "tests/test_bsi_m3.py"]


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
