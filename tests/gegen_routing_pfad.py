#!/usr/bin/env python3
"""Gegenprobe: beisst tests/test_routing_pfad.py ueberhaupt?

Die Probe legt dem Waechter SABOTIERTE KOPIEN von backend/main.py vor (als
Argument, in einem Wegwerf-Verzeichnis) – die echte Datei wird nie angefasst,
ein abgebrochener Lauf hinterlaesst also keinen Rueckstand.

Je Probe der erwartete Exit: 1 = Verstoss erkannt, 0 = zu Recht kein Befund
(Gegenkontrolle: eine Protokollzeile mit request.url.path im f-String ist
erlaubt), 2 = Waechter meldet "konnte nicht laufen" (Middleware umbenannt).

Lauf:  venv/bin/python tests/gegen_routing_pfad.py
Exit 0 = alle Proben wie erwartet, 1 = mindestens eine nicht, 2 = konnte nicht laufen
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HIER = Path(__file__).resolve().parent
WAECHTER = HIER / "test_routing_pfad.py"
MAIN = HIER.parent / "backend" / "main.py"

# (Name, alt, neu, erwarteter Exit) – alt muss GENAU einmal vorkommen
PROBEN = [
    ("Loopback-Sperre liest wieder request.url.path",
     "    path = _routing_pfad(request)\n    if not _client_is_local(request)",
     "    path = request.url.path\n    if not _client_is_local(request)", 1),
    ("Sicherheitsprotokoll filtert wieder nach request.url.path",
     'or not _routing_pfad(request).startswith("/api/"):',
     'or not request.url.path.startswith("/api/"):', 1),
    ("CSP waehlt wieder nach request.url.path",
     "_csp.kopfzeilen(_routing_pfad(request),", "_csp.kopfzeilen(request.url.path,", 1),
    ("Sicherheits-Kopfzeilen waehlen wieder nach request.url.path",
     '            _routing_pfad(request), request.url.scheme == "https").items():',
     '            request.url.path, request.url.scheme == "https").items():', 1),
    ("Helfer liest raw_path statt path",
     '    return request.scope["path"]\n', '    return request.scope["raw_path"].decode()\n', 1),
    ("Helfer umgangen ueber str(request.url)",
     "    path = _routing_pfad(request)\n    if not _client_is_local(request)",
     "    path = '/' + str(request.url).split('/', 3)[-1]\n    if not _client_is_local(request)", 1),
    ("Gegenkontrolle: Protokollzeile mit url.path im f-String bleibt erlaubt",
     "    path = _routing_pfad(request)\n    if not _client_is_local(request)",
     "    path = _routing_pfad(request)\n    print(f\"[API] {request.url.path}\")\n"
     "    if not _client_is_local(request)", 0),
    ("Middleware umbenannt -> Waechter muss abbrechen statt still zu bestehen",
     "async def _api_local_only_mw(", "async def _api_nur_lokal_mw(", 2),
]


def lauf(pfad: Path) -> int:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, str(WAECHTER), str(pfad)], capture_output=True,
                          text=True, timeout=120, env=env).returncode


def main() -> int:
    if not MAIN.is_file() or not WAECHTER.is_file():
        print("ABBRUCH: main.py oder Waechter fehlt")
        return 2
    text = MAIN.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        basis = Path(tmp) / "main.py"
        basis.write_text(text, encoding="utf-8")
        rc = lauf(basis)
        if rc != 0:
            print(f"ABBRUCH: Basislauf nicht gruen (rc={rc})")
            return 2
        print("Basislauf gruen.\n")
        treffer = 0
        for name, alt, neu, erwartet in PROBEN:
            if text.count(alt) != 1:
                print(f"  ???  {name} – Anker {text.count(alt)}x gefunden")
                continue
            kopie = Path(tmp) / "probe.py"
            kopie.write_text(text.replace(alt, neu), encoding="utf-8")
            rc = lauf(kopie)
            gut = rc == erwartet
            treffer += gut
            print(f"  {'OK  ' if gut else 'ZAHN'} {name:<72} Exit {rc} (erwartet {erwartet})")
    print(f"\n{treffer}/{len(PROBEN)} Proben wie erwartet")
    return 0 if treffer == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
