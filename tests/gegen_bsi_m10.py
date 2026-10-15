#!/usr/bin/env python3
"""Gegenprobe zu tests/test_bsi_m10.py: beisst der Waechter?

Jede Probe dreht EINEN Teil von M10 zurueck (Python-Ersetzung ganzer Zeilen),
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
MARKE = ROOT / "tests" / ".gegen_bsi_m10.laufmarke"

ZR = "backend/zugang_regel.py"
MA = "backend/main.py"

PROBEN = [
    ("Middleware laesst Routen ohne Regel durch", ZR,
     '        if route is None or self._einstufung(route) != "ohne_regel":\n',
     '        if True:\n'),
    ("Pruefung angenommen ohne Aufruf (fail-open)", ZR,
     '                await self._pruefen(Request(scope, receive))\n                return await self.app(scope, receive, send)\n',
     '                return await self.app(scope, receive, send)\n'),
    ("Sperre ergibt 401 statt Status der Pruefung", ZR,
     '                status = int(getattr(e, "status_code", 401) or 401)\n', '                status = 401\n'),
    ("WebSocket ohne Regel wird durchgelassen", ZR,
     '            await send({"type": "websocket.close", "code": 1008})\n            return\n',
     '            return await self.app(scope, receive, send)\n'),
    ("Mount wird nicht erkannt (gilt als GET)", ZR,
     '    if cls == "Mount":\n        return [("MOUNT", getattr(route, "path", pfad))]\n', ''),
    ("Dependency-Erkennung blind", ZR,
     '    if dep is not None and any(c in anmelde_funktionen for c in _aufrufe(dep)):\n',
     '    if False:\n'),
    ("Ausnahme fuer eine Route mit Dependency (Leiche)", ZR,
     '    ("POST", "/api/login"): ("anmeldung", "Anmeldung"),\n',
     '    ("POST", "/api/login"): ("anmeldung", "Anmeldung"),\n    ("GET", "/api/me"): ("oeffentlich", "nur zur Probe eingefuegt"),\n'),
    ("Ausnahme ohne Route", ZR,
     '    ("POST", "/api/login"): ("anmeldung", "Anmeldung"),\n',
     '    ("POST", "/api/login"): ("anmeldung", "Anmeldung"),\n    ("GET", "/api/gibtsnicht"): ("oeffentlich", "nur zur Probe eingefuegt"),\n'),
    ("Route faellt aus der Ausnahmeliste", ZR,
     '    ("GET", "/api/health"): ("oeffentlich", "Zustandsabfrage, liefert nur ok"),\n', ''),
    ("Middleware in main.py nicht eingehaengt", MA,
     'app.add_middleware(_zugang_regel.ZugangsMiddleware,\n                   anmelde_funktionen=_anmelde_funktionen, pruefen=_zugang_pruefen)\n',
     ''),
    ("Pruefung ist nicht require_auth", MA,
     'async def _zugang_pruefen(request):\n    await require_auth(request)\n',
     'async def _zugang_pruefen(request):\n    return None\n'),
    ("Rundsendung an nicht angemeldete Verbindungen", MA,
     '    for session_id, ws in list(active_sessions.items()):\n        if not _ws_rundsendung_erlaubt(ws):\n            continue\n',
     '    for session_id, ws in list(active_sessions.items()):\n'),
    ("CPU-Last an jeden", MA,
     '            if _ws_rundsendung_erlaubt(ws):\n                cpu = psutil.cpu_percent(interval=0)\n',
     '            if True:\n                cpu = psutil.cpu_percent(interval=0)\n'),
    ("angemeldet schon vor den Pruefungen", MA,
     '        # Erst HIER (alle Pruefungen bestanden) bekommt die Verbindung Rundsendungen.\n        _ws_angemeldet.add(id(ws))\n',
     ''),
    ("Vision: Vorgabeschluessel zurueck", MA,
     '                       .get("config", {}).get("stream_key") or "")\n',
     '                       .get("config", {}).get("stream_key") or "jarvis-stream-vorgabe")\n'),
    ("Vision: kurze Schluessel gelten", MA,
     '    key_ok = (len(expected_key) >= 16 and bool(stream_key)\n',
     '    key_ok = (bool(stream_key)\n'),
    ("neue Route ohne Dependency und ohne Ausnahme", MA,
     '@app.get("/api/security/zugangsregeln")\n',
     '@app.get("/api/probe/vergessen")\nasync def _probe_vergessen():\n    return {}\n\n\n@app.get("/api/security/zugangsregeln")\n'),
]

DATEIEN = [ZR, MA, "tests/test_bsi_m10.py"]

WAECHTER = [
    (["python3", "tests/test_bsi_m10.py"], r"Ergebnis: (\d+) OK, (\d+) FAIL"),
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
