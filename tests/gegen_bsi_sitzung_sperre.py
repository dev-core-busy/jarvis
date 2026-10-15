#!/usr/bin/env python3
"""Gegenprobe zu tests/test_bsi_sitzung_sperre.py: beisst der Waechter?

Jede Probe dreht EINEN Teil der Sperrpruefung an selbst pruefenden Endpunkten
zurueck (Python-Ersetzung ganzer Zeilen), laesst den Waechter laufen und
erwartet mindestens einen FAIL. Vorher gruener Basislauf, danach Byte-Gleichheit
per md5, ohne Bytecode, mit Laufmarke.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKE = ROOT / "tests" / ".gegen_bsi_sitzung_sperre.laufmarke"

MA = "backend/main.py"

PROBEN = [
    ("Helfer: Kontosperre fehlt", MA,
     "    return bool(_user_must_change(user) or security_guard.is_blocked(user)\n",
     "    return bool(_user_must_change(user)\n"),
    ("Helfer: offener Kennwortwechsel fehlt", MA,
     "    return bool(_user_must_change(user) or security_guard.is_blocked(user)\n",
     "    return bool(security_guard.is_blocked(user)\n"),
    ("Helfer: Anmeldeberechtigung fehlt", MA,
     "    return bool(_user_must_change(user) or security_guard.is_blocked(user)\n                or not _login_still_allowed(user))\n",
     "    return bool(_user_must_change(user) or security_guard.is_blocked(user))\n"),
    ("Helfer: gesperrte Sitzung durchgelassen", MA,
     "        if _sitzung_gesperrt(user):\n            return None, 403\n        return user, 200\n",
     "        return user, 200\n"),
    ("avatar_ask wieder nur verify_token", MA,
     "    global _avatar_agent\n    user, status = _sitzung_oder_schluessel(request)\n    if user is None:\n        return JSONResponse({\"detail\": \"Nicht autorisiert\"}, status_code=status)\n",
     "    global _avatar_agent\n    user = verify_token(request.headers.get(\"Authorization\", \"\").replace(\"Bearer \", \"\"))\n    status = 401\n    if not (user or _verify_agent_api_key(request)):\n        return JSONResponse({\"detail\": \"Nicht autorisiert\"}, status_code=status)\n"),
    ("tts wieder nur verify_token", MA,
     "    # Auth: Bearer-Token, X-API-Key als Login-Token oder Agent-API-Key\n    user, status = _sitzung_oder_schluessel(request)\n    if user is None:\n        return JSONResponse({\"detail\": \"Nicht autorisiert\"}, status_code=status)\n\n    body = await request.json()\n",
     "    # Auth: Bearer-Token, X-API-Key als Login-Token oder Agent-API-Key\n    user = verify_token(request.headers.get(\"Authorization\", \"\").replace(\"Bearer \", \"\"))\n    if not (user or _verify_agent_api_key(request)):\n        return JSONResponse({\"detail\": \"Nicht autorisiert\"}, status_code=401)\n\n    body = await request.json()\n"),
    ("support_query ohne Sperrpruefung", MA,
     "    # ── Auth: Benutzer-Token oder externer API-Key ──────────────────\n    _bearer = request.headers.get(\"Authorization\", \"\").replace(\"Bearer \", \"\")\n    user = verify_token(_bearer)\n    if user and _sitzung_gesperrt(user):\n",
     "    # ── Auth: Benutzer-Token oder externer API-Key ──────────────────\n    _bearer = request.headers.get(\"Authorization\", \"\").replace(\"Bearer \", \"\")\n    user = verify_token(_bearer)\n    if False:\n"),
    ("support_summarize ohne Sperrpruefung", MA,
     "    Auth: Benutzer-Token (Bearer) ODER externer API-Key (analog /api/support/query).\n    \"\"\"\n    _bearer = request.headers.get(\"Authorization\", \"\").replace(\"Bearer \", \"\")\n    user = verify_token(_bearer)\n    if user and _sitzung_gesperrt(user):\n",
     "    Auth: Benutzer-Token (Bearer) ODER externer API-Key (analog /api/support/query).\n    \"\"\"\n    _bearer = request.headers.get(\"Authorization\", \"\").replace(\"Bearer \", \"\")\n    user = verify_token(_bearer)\n    if False:\n"),
    ("Kamera-Stream ohne Sperrpruefung", MA,
     "    if _stream_user and not key_ok and _sitzung_gesperrt(_stream_user):\n",
     "    if False:\n"),
    ("Regel: neue Stelle mit altem Muster", MA,
     "def _sitzung_gesperrt(user: str) -> bool:\n",
     "def _neu_altes_muster(request):\n    return verify_token(request.headers.get(\"Authorization\", \"\"))\n\n\ndef _sitzung_gesperrt(user: str) -> bool:\n"),
]

DATEIEN = [MA, "tests/test_bsi_sitzung_sperre.py"]

WAECHTER = [
    (["python3", "tests/test_bsi_sitzung_sperre.py"], r"Ergebnis: (\d+) OK, (\d+) FAIL"),
]


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def lauf():
    """Alle Waechter; Summe der FAILs. -1 = einer konnte nicht laufen."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    summe = 0
    for cmd, muster in WAECHTER:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                               cwd=str(ROOT), env=env)
        except subprocess.TimeoutExpired:
            return -1, "timeout " + cmd[-1]
        m = re.search(muster, r.stdout)
        if r.returncode == 2 or not m:
            return -1, f"{cmd[-1]} rc={r.returncode} {r.stdout.strip()[-160:]}"
        summe += int(m.group(2))
    return summe, 0


def zuruecknehmen():
    """Rueckstand eines abgeschossenen Laufs zuruecknehmen (Laufmarke)."""
    if not MARKE.exists():
        return
    try:
        alt = json.loads(MARKE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        print("ABBRUCH: Laufmarke unlesbar – Arbeitsbaum von Hand pruefen")
        sys.exit(2)
    for d, hexinhalt in alt.items():
        (ROOT / d).write_bytes(bytes.fromhex(hexinhalt))
    MARKE.unlink()
    print("Rueckstand eines abgebrochenen Laufs zurueckgenommen.")


def main() -> int:
    zuruecknehmen()
    if {p[1] for p in PROBEN} - set(DATEIEN):
        print("ABBRUCH: Probe fasst eine nicht gesicherte Datei an")
        return 2
    sicherung = {d: (ROOT / d).read_bytes() for d in DATEIEN}
    vorher = {d: md5(d) for d in DATEIEN}

    fails, rc = lauf()
    if fails != 0:
        print("ABBRUCH: Basislauf nicht gruen (FAIL=%s, %s)" % (fails, rc))
        return 2
    print("Basislauf gruen.\n")

    MARKE.write_text(json.dumps({d: b.hex() for d, b in sicherung.items()}), encoding="utf-8")
    beissen = 0
    try:
        for name, datei, alt, neu in PROBEN:
            pfad = ROOT / datei
            text = pfad.read_text(encoding="utf-8")
            if text.count(alt) != 1:
                print("  ???  %s – Anker %dx gefunden" % (name, text.count(alt)))
                continue
            pfad.write_text(text.replace(alt, neu, 1), encoding="utf-8")
            try:
                fails, rc = lauf()
            finally:
                pfad.write_bytes(sicherung[datei])
            if fails > 0:
                beissen += 1
                print("  BISS %-62s %d FAIL" % (name, fails))
            elif fails < 0:
                print("  ABBR %-62s Waechter konnte nicht laufen (%s)" % (name, rc))
            else:
                print("  ZAHN %-62s 0 FAIL – beisst NICHT" % name)
    finally:
        for d, inhalt in sicherung.items():
            (ROOT / d).write_bytes(inhalt)
        if MARKE.exists():
            MARKE.unlink()

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
