#!/usr/bin/env python3
"""Gegenprobe zu tests/test_host_pruefung.py: beisst der Waechter?

Jede Probe dreht EINEN Teil der Host-Pruefung (Haertung B12) zurueck
(Python-Ersetzung ganzer Zeilen), laesst den Waechter laufen und erwartet
mindestens einen FAIL. Vorher gruener Basislauf, danach Byte-Gleichheit aller
Dateien per md5. Laeuft ohne Bytecode (PYTHONDONTWRITEBYTECODE=1).

Bewusst OHNE Probe: die Zeichenpruefung in ``host_normal`` (``/``, ``@`` ...).
Sie haelt kaputte Eintraege aus den Einstellungen aus der Liste, ein fremder
Host-Kopf faellt ohne sie genauso durch (er steht nicht in der Liste) – eine
Sabotage dort haette keine messbare Wirkung, also auch keinen Biss.

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
WAECHTER = ROOT / "tests" / "test_host_pruefung.py"
HP = "backend/host_pruefung.py"
MAIN = "backend/main.py"

PROBEN = [
    ("auto weist auch bei selbst signiertem Zertifikat ab", HP,
     '        m = "erzwingen" if selbst is False else "melden"\n', '        m = "erzwingen"\n'),
    ("auto weist bei unlesbarem Zertifikat ab", HP,
     '        m = "erzwingen" if selbst is False else "melden"\n',
     '        m = "erzwingen" if selbst is not True else "melden"\n'),
    ("unbekannter Modus gilt als erzwingen", HP,
     "    return w if w in MODI else VORGABE\n", '    return w if w in MODI else "erzwingen"\n'),
    ("Port wird nicht abgetrennt", HP,
     '    if h.count(":") == 1:\n', "    if False:\n"),
    ("eckige Klammern (IPv6) nicht verstanden", HP,
     '    if h.startswith("["):\n', "    if False:\n"),
    ("DNS-Namen des Zertifikats fehlen", HP,
     "        for n in san.get_values_for_type(x509.DNSName):\n            namen.add(host_normal(n))\n",
     ""),
    ("Hosts aus den Einstellungen fehlen", HP,
     'URL_SCHLUESSEL = ("cors_origins", "addin_base_url", "oidc_redirect_uri")\n',
     "URL_SCHLUESSEL = ()\n"),
    ("erlaubte_hostnamen wirkungslos", HP,
     "    for n in _liste(_einst(LISTEN_SCHLUESSEL, \"\")):\n        namen.add(host_normal(n))\n", ""),
    ("Loopback fehlt", HP,
     '    namen = set(LOOPBACK) | zert_namen | _eigene_namen()\n',
     "    namen = zert_namen | _eigene_namen()\n"),
    ("Zwischenspeicher ohne Frist", HP,
     "        if _stand and t - _stand[0] < TTL_S:\n", "        if _stand:\n"),
    ("Zwischenspeicher wirkungslos", HP,
     "        if _stand and t - _stand[0] < TTL_S:\n", "        if False:\n"),
    ("fremder Name wird nie abgewiesen", HP,
     '        if m != "erzwingen":\n', "        if True:\n"),
    ("fehlender Host-Kopf kommt durch", HP,
     "        if h and h in namen:\n", "        if not h or h in namen:\n"),
    ("WebSocket nicht abgewiesen", HP,
     '            await send({"type": "websocket.close", "code": WS_CODE})\n            return\n',
     "            return await self.app(scope, receive, send)\n"),
    ("Meldung ohne Drossel", HP,
     "        if zuletzt is not None and t - zuletzt < MELDE_ABSTAND_S:\n            return\n", ""),
    ("Modus aus meldet trotzdem", HP,
     '        if m == "aus":\n            return await self.app(scope, receive, send)\n', ""),
    ("Middleware nicht registriert", MAIN,
     "app.add_middleware(_host_pruefung.HostPruefung)\n", ""),
    ("Middleware nicht die aeusserste", MAIN,
     "app.add_middleware(_host_pruefung.HostPruefung)\n",
     "app.add_middleware(_host_pruefung.HostPruefung)\napp.add_middleware(_kompression.KompressionsWeiche)\n"),
    ("Einstellungen nicht hereingereicht", MAIN,
     "_host_pruefung.einstellungen_quelle(config.get_setting, _SERVER_ZERTIFIKAT)\n", ""),
]

DATEIEN = [HP, MAIN, "tests/test_host_pruefung.py"]


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
                print("  BISS %-52s %d FAIL" % (name, fails))
            elif fails < 0:
                print("  ABBR %-52s Waechter konnte nicht laufen (rc=%s)" % (name, rc))
            else:
                print("  ZAHN %-52s 0 FAIL – beisst NICHT" % name)
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
