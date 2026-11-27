#!/usr/bin/env python3
"""Gegenprobe zu tests/test_bsi_m3.py: beisst der Waechter?

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
WAECHTER = ROOT / "tests" / "test_bsi_m3.py"
MAIN = "backend/main.py"
AS = "backend/anmelde_schutz.py"
ST = "backend/sitzung_token.py"
CLIENT = "ai-mouse/src/AiMouse/Vision/JarvisClient.cs"

PROBEN = [
    # ── Konto-Sperre ──
    # Seit 2026-11-05 (A1) prueft und belegt der Login in EINEM Schritt
    # (_anmelde_reservierung); der alte Anker traf nichts mehr ("Anker 0x").
    ("Login prueft die Konto-Sperre nicht", MAIN,
     "    _gesperrt = _anmelde_reservierung(request, client_ip, username)\n"
     "    if _gesperrt is not None:\n        return _gesperrt\n",
     "    _gesperrt = _anmelde_reservierung(request, client_ip, username)\n"),
    ("Fehlversuch nur noch je IP", MAIN,
     '    if _anmelde_schutz.fehlversuch(ip, _norm_login(username) if username else ""):\n',
     '    if _anmelde_schutz.fehlversuch(ip, ""):\n'),
    # Seit 2026-11-20 prueft der Login den Code ueber _totp_code_pruefen und
    # bucht den Fehlversuch selbst – der Anker ist diese Buchung.
    ("Falscher 2FA-Code zaehlt nur fuer die IP", MAIN,
     "            if _zaehlt:\n                _record_login_attempt(client_ip, username)\n",
     "            if _zaehlt:\n                _record_login_attempt(client_ip)\n"),
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
    # ── Anmeldung (Zahnrad, 2026-11-20) ──
    ("Admins werden bei der Anmeldung wieder nach dem Code gefragt", MAIN,
     "    elif _konto_ist_admin(username):\n", "    elif False:\n"),
    ("Token nach 2FA (Nicht-Admin) ohne Merkmal", MAIN,
     "    token = generate_token(username, mit_2fa=_mit_2fa, ohne_admin=_ohne_admin,\n",
     "    token = generate_token(username, ohne_admin=_ohne_admin,\n"),
    # ── Admin-Rechte an der Sitzung ──
    ("verify_token setzt keinen Sitzungskontext", MAIN,
     "            _sitzung_kontext.set((_norm_login(username), _sitzung.admin_erhoeht(sig),\n"
     "                                  _sitzung.ohne_admin(sig)))\n", ""),
    ("verify_token nimmt 'mit 2FA' als Admin-Rechte", MAIN,
     "            _sitzung_kontext.set((_norm_login(username), _sitzung.admin_erhoeht(sig),\n",
     "            _sitzung_kontext.set((_norm_login(username), _sitzung.mit_2fa(sig),\n"),
    ("ohne Erhoehung gilt die Sitzung trotzdem als Admin", MAIN,
     "    return not kx[1]\n", "    return False\n"),
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
    ("Kennwortwechsel erbt 'mit 2FA' nicht", MAIN,
     "            mit_2fa = _sitzung.mit_2fa(_sig)\n", "            mit_2fa = False\n"),
    ("Kennwortwechsel erbt die Erhoehung nicht", MAIN,
     "            erhoeht = _sitzung.admin_erhoeht(_sig)\n", "            erhoeht = False\n"),
    ("Kennwortwechsel macht JEDE Sitzung zu 'mit 2FA'", MAIN,
     "    return generate_token(username, ts=rev + 1, mit_2fa=mit_2fa, ohne_admin=ohne_admin,\n",
     "    return generate_token(username, ts=rev + 1, mit_2fa=True, ohne_admin=ohne_admin,\n"),
    ("Kennwortwechsel macht JEDE Sitzung zur erhoehten", MAIN,
     "                          admin_erhoeht=erhoeht)\n", "                          admin_erhoeht=True)\n"),
    ("totp_disable ohne Admin-Pruefung", MAIN,
     "    if _konto_ist_admin(username):\n        return JSONResponse({\"success\": False, \"error\": \"Für Administratoren ist die \"\n",
     "    if False:\n        return JSONResponse({\"success\": False, \"error\": \"Für Administratoren ist die \"\n"),
    ("Add-in-SSO-Token nicht 'ohne Admin'", MAIN,
     "    token = generate_token(username, ohne_admin=True)\n",
     "    token = generate_token(username)\n"),
    ("Merkmal 'mit 2FA' wird nicht gespeichert", ST,
     '"mit_2fa": _mit_2fa, "ohne_admin": _ohne_admin,',
     '"ohne_admin": _ohne_admin,'),
    ("Merkmal 'Admin erhoeht' wird nicht gespeichert", ST,
     '                                   "admin_erhoeht": _admin_erhoeht,\n', ""),
    ("Abmelden nimmt die Erhoehung nicht mit", ST,
     "        _nur_ai_maus.pop(k, None)\n        _admin_erhoeht.pop(k, None)\n        _dirty = True",
     "        _nur_ai_maus.pop(k, None)\n        _dirty = True"),
    ("App-Sitzung laesst sich direkt erhoehen", ST,
     "            if k in _ohne_admin or k in _nur_ai_maus:\n                return False\n", ""),
    # ── Erhoehung am Zahnrad ──
    ("Zahnrad prueft den Code nicht", MAIN,
     "        fehler = await _totp_code_pruefen(username, st[\"totp_secret\"], code)\n",
     "        fehler = None\n"),
    ("Zahnrad prueft das Admin-Konto nicht", MAIN,
     "    if not _konto_ist_admin(username):\n        _erhoehung_protokoll(",
     "    if False:\n        _erhoehung_protokoll("),
    ("Zahnrad: Fehlversuch zaehlt nicht fuers Konto", MAIN,
     "            if zaehlt:\n                _record_login_attempt(ip, username)\n",
     "            if zaehlt:\n                pass\n"),
    ("Zahnrad ohne Sperr-Schranke vor dem Code", MAIN,
     "        schranke = _kennwort_schranke(request, username)\n        if schranke is not None:\n"
     "            return schranke\n        fehler = await _totp_code_pruefen(",
     "        fehler = await _totp_code_pruefen("),
    ("Zahnrad-Einrichtung ohne Kennwort-Pflicht", MAIN,
     "        if not password:\n            return JSONResponse({\"ok\": False, \"requires_totp_setup\": True,\n",
     "        if False:\n            return JSONResponse({\"ok\": False, \"requires_totp_setup\": True,\n"),
    ("Zahnrad-Einrichtung prueft das Kennwort nicht", MAIN,
     "        if not await asyncio.to_thread(authenticate_linux_user, username, password):\n"
     "            _kennwort_fehlversuch(request, username, \"admin_erhoehung\")\n",
     "        if False:\n"
     "            _kennwort_fehlversuch(request, username, \"admin_erhoehung\")\n"),
    ("Zahnrad-Einrichtung prueft den Code nicht", MAIN,
     "        erg = _totp_schutz.pruefen(_norm_login(username), vorgemerkt, code)\n"
     "        if erg != _totp_schutz.OK:\n",
     "        erg = _totp_schutz.pruefen(_norm_login(username), vorgemerkt, code)\n"
     "        if False:\n"),
    # Der Vorfall vom 2026-11-20 (DEV) als Sabotage: die IdP-MFA ersetzt den
    # Code wieder.
    ("Zahnrad: IdP-MFA ersetzt den Code wieder", MAIN,
     "    if st.get(\"totp_enabled\") and st.get(\"totp_secret\"):\n        if not code:\n"
     "            return JSONResponse({\"ok\": False, \"requires_totp\": True,\n",
     "    if _sitzung.mit_2fa(request.headers.get(\"Authorization\", \"\").rsplit(\":\", 1)[-1]):\n"
     "        weg = \"code\"\n"
     "    elif st.get(\"totp_enabled\") and st.get(\"totp_secret\"):\n        if not code:\n"
     "            return JSONResponse({\"ok\": False, \"requires_totp\": True,\n"),
    ("Beenden nimmt die Rechte nicht zurueck", MAIN,
     "    _sitzung.setze_admin_erhoeht(kennung, ts, False)\n", ""),
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
    ("Login-Antwort meldet die Konto- statt der Sitzungsrechte", MAIN,
     "    _sitzung_kontext.set((_norm_login(username), False, _ohne_admin))\n", ""),
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
    # ── AI-Maus (Betreiberentscheid 2026-11-27): 2FA wie im Browser, mit IdP nur Firmenkonto ──
    ("AI-Maus wieder ohne 2FA-Abfrage", MAIN,
     "    if _ohne_admin and not _ai_maus:\n",
     "    if _ai_maus:\n        pass\n    elif _ohne_admin:\n"),
    ("AI-Maus-Kennwort trotz IdP angenommen", MAIN,
     "    return _ist_ai_maus_anmeldung(body) and _oidc_konfig() is not None\n",
     "    return False\n"),
    ("IdP-Sperre gilt fuer jede Anmeldung", MAIN,
     "    return _ist_ai_maus_anmeldung(body) and _oidc_konfig() is not None\n",
     "    return _oidc_konfig() is not None\n"),
    ("AI-Maus schickt keine Kennung", CLIENT,
     '            ["client"] = "ai-mouse",\n', ""),
]

# BEWUSST OHNE PROBE (doppelte Schranken, Register: "zwei Schranken fuer dieselbe
# Frage machen jede Gegenprobe stumm"): admin_erhoehen weist eine App-Sitzung
# selbst ab (kx[2]) UND setze_admin_erhoeht verweigert sie; ebenso prueft
# sitzung_token.admin_erhoeht() beim LESEN noch einmal "ohne Admin"/"nur AI-Maus".
# Beides ist Tiefenverteidigung fuer jeden Weg ausser dem Endpunkt; gemessen wird
# die tragende Schranke (setze_admin_erhoeht direkt, Probe oben).
# Aus demselben Grund ohne Probe: das "ohne Admin" in main._sitzung_ohne_admin
# (kx[2]) – eine App-Sitzung traegt nie "erhoeht" (sitzung_token), die Zeile
# allein zu entfernen aendert also nichts Messbares (gemessen 2026-11-20:
# 0 FAIL). Der Grund steht auch an der Zeile.

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
