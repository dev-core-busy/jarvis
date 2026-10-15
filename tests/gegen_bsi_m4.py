#!/usr/bin/env python3
"""Gegenprobe zu tests/test_bsi_m4.py: beisst der Waechter?

Jede Probe dreht EINEN Teil von M4 zurueck (Python-Ersetzung ganzer Zeilen),
laesst den Waechter laufen und erwartet mindestens einen FAIL. Vorher gruener
Basislauf, danach Byte-Gleichheit aller Dateien per md5, ohne Bytecode, mit
Laufmarke (abgeschossener Lauf wird beim naechsten Start zurueckgenommen).

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
MARKE = ROOT / "tests" / ".gegen_bsi_m4.laufmarke"

UG = "backend/url_geheimnis.py"
VT = "backend/vnc_ticket.py"
MA = "backend/main.py"
VJ = "frontend/js/vnc.js"
DK = "backend/download_key.py"
AR = "android/app/src/main/java/info/jarvisai/app/data/repository/IssuesRepository.kt"

PROBEN = [
    # ── Schwaerzen ──
    ("Filter wird nicht installiert (Funktion leer)", UG,
     '    for name in UVICORN_LOGGER:\n        lg = logging.getLogger(name)\n',
     '    for name in ():\n        lg = logging.getLogger(name)\n'),
    ("nur das Access-Log, nicht die WebSocket-Zeilen", UG,
     'UVICORN_LOGGER = ("uvicorn.access", "uvicorn.error")\n',
     'UVICORN_LOGGER = ("uvicorn.access",)\n'),
    ("Filter schwaerzt die Argumente nicht", UG,
     '                record.args = tuple(schwaerzen(a) for a in record.args)\n',
     '                pass\n'),
    ("verschachtelte Adresse (noVNC path=) nicht erkannt", UG,
     '    r"(?P<vor>(?:^|[?&;]|%3[Ff]|%26))(?P<name>" + _NAMEN + r")(?P<gleich>=|%3[Dd])"\n',
     '    r"(?P<vor>(?:^|[?&;]))(?P<name>" + _NAMEN + r")(?P<gleich>=)"\n'),
    ("ticket fehlt in der Namensliste", UG,
     '    "key", "api_key", "apikey", "ticket",\n', '    "key", "api_key", "apikey",\n'),
    ("Kennwort in user:pw@ bleibt stehen", UG,
     '    return _USERINFO.sub(lambda m: m.group("vor") + ERSATZ, t)\n', '    return t\n'),
    ("Wert bis zum Zeilenende (frisst Folgeparameter)", UG,
     '    r"(?P<wert>(?:(?!%26)[^&#\\s\\"\'])+)",\n', '    r"(?P<wert>\\S+)",\n'),
    ("main.py installiert den Filter nicht", MA,
     '_url_geheimnis.installieren()\n', 'pass\n'),
    ("Kamera-Startzeile ungeschwaerzt", MA,
     '                        print(f"📷 Vision auto-start: {_url_geheimnis.schwaerzen(source)}")\n',
     '                        print(f"📷 Vision auto-start: {source}")\n'),
    # ── Ticket ──
    ("Ticket mehrfach einloesbar", VT,
     '        eintrag = _tickets.pop(ticket, None)\n', '        eintrag = _tickets.get(ticket)\n'),
    ("Ticket verfaellt nicht", VT,
     '    if eintrag is None or eintrag[2] <= jetzt:\n', '    if eintrag is None:\n'),
    ("Ticket ohne Kontext", VT,
     '    return eintrag[0], eintrag[1]\n', '    return eintrag[0], None\n'),
    # ── WebSocket ──
    ("Sitzungstoken in der Adresse wieder angenommen", MA,
     '    _eingeloest = _vnc_ticket.einloesen(websocket.query_params.get("ticket", ""))\n',
     '    _eingeloest = _vnc_ticket.einloesen(websocket.query_params.get("ticket", ""))\n'
     '    if not _eingeloest and verify_token(websocket.query_params.get("token", "")):\n'
     '        _eingeloest = (verify_token(websocket.query_params.get("token", "")), None)\n'),
    ("WebSocket setzt den Sitzungskontext nicht (fail-open, M3)", MA,
     '    _sitzung_kontext.set(_vnc_kontext)\n    if not _login_still_allowed(_vnc_user):\n',
     '    if not _login_still_allowed(_vnc_user):\n'),
    ("WebSocket ohne Pruefung der Anmeldeberechtigung", MA,
     '    _sitzung_kontext.set(_vnc_kontext)\n    if not _login_still_allowed(_vnc_user):\n',
     '    _sitzung_kontext.set(_vnc_kontext)\n    if False:\n'),
    # ── Ticket-Endpunkt ──
    ("Endpunkt uebernimmt den Kontext der Dependency (nicht neu bestimmt)", MA,
     '    if verify_token(token) != user:\n        raise HTTPException(status_code=401, detail="Nicht authentifiziert")\n'
     '    ticket = _vnc_ticket.ausstellen(',
     '    if False:\n        raise HTTPException(status_code=401, detail="Nicht authentifiziert")\n'
     '    ticket = _vnc_ticket.ausstellen('),
    ("Endpunkt ohne Sperrpruefung", MA,
     '    if security_guard.is_blocked(user):\n        raise HTTPException(status_code=403, detail="ACCOUNT_BLOCKED")\n'
     '    token = request.headers.get("Authorization", "").replace("Bearer ", "")\n    if verify_token(token) != user:\n',
     '    token = request.headers.get("Authorization", "").replace("Bearer ", "")\n    if verify_token(token) != user:\n'),
    ("Ticket-Antwort cachebar", MA,
     '                        headers={"Cache-Control": "no-store"})\n\n\n@app.get("/api/config")',
     '                        headers={})\n\n\n@app.get("/api/config")'),
    ("Ticket-Endpunkt fuer jeden Angemeldeten", MA,
     'async def vnc_ticket_holen(request: Request, user: str = Depends(require_local_auth)):\n',
     'async def vnc_ticket_holen(request: Request, user: str = Depends(require_auth)):\n'),
    # ── /docs ──
    ("/docs reicht das Sitzungstoken weiter", MA,
     '    return get_swagger_ui_html(openapi_url=_openapi_url(user), title="Jarvis API – Swagger")\n',
     '    tok = request.headers.get("Authorization", "").replace("Bearer ", "") or request.query_params.get("token", "")\n'
     '    return get_swagger_ui_html(openapi_url=f"/openapi.json?token={tok}", title="Jarvis API – Swagger")\n'),
    ("/redoc reicht das Sitzungstoken weiter", MA,
     '    return get_redoc_html(openapi_url=_openapi_url(user), title="Jarvis API – ReDoc")\n',
     '    tok = request.headers.get("Authorization", "").replace("Bearer ", "") or request.query_params.get("token", "")\n'
     '    return get_redoc_html(openapi_url=f"/openapi.json?token={tok}", title="Jarvis API – ReDoc")\n'),
    ("Schema-Adresse mit Sitzungs- statt Abruf-Schluessel", MA,
     '    key, _exp = _dlkey.erzeugen(user)\n    return "/openapi.json?token=" + key\n',
     '    key = user\n    return "/openapi.json?token=" + key\n'),
    # ── Oberflaeche ──
    ("vnc.js: Sitzungstoken in der noVNC-Adresse", VJ,
     '            const wsPath = encodeURIComponent(`ws/vnc?ticket=${encodeURIComponent(d.ticket)}`);\n',
     '            const wsPath = encodeURIComponent(`ws/vnc?token=${encodeURIComponent(_tok)}`);\n'),
    ("vnc.js: Ticket per GET ohne Kopfsatz", VJ,
     "        fetch('/api/vnc/ticket', {\n            method: 'POST',\n            headers: { 'Authorization': 'Bearer ' + _tok }\n        })",
     "        fetch('/api/vnc/ticket', {})"),
    # ── strikter Abruf ──
    ("strict wieder Vorgabe AUS", DK,
     '    v = config.get_setting("download_key_strict", True)\n',
     '    v = config.get_setting("download_key_strict", False)\n'),
    # ── Android ──
    ("Android: Sitzungstoken wieder in der Adresse", AR,
     '        val wert = abrufSchluessel() ?: tok.takeUnless { istSitzung }\n',
     '        val wert = tok\n'),
    ("Android: Rueckfall aufs Sitzungstoken", AR,
     '        val wert = abrufSchluessel() ?: tok.takeUnless { istSitzung }\n',
     '        val wert = abrufSchluessel() ?: tok\n'),
    ("Android: Schluessel ohne Kopfsatz geholt", AR,
     '            httpClient.newCall(authBuilder("/api/download-key").get().build()).execute().use { resp ->\n',
     '            httpClient.newCall(Request.Builder().url("${baseUrl()}/api/download-key").get().build()).execute().use { resp ->\n'),
]

DATEIEN = [UG, VT, MA, VJ, DK, AR, "tests/test_bsi_m4.py"]

WAECHTER = [
    (["python3", "tests/test_bsi_m4.py"], r"Ergebnis: (\d+) OK, (\d+) FAIL"),
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
