#!/usr/bin/env python3
"""Gegenprobe zu tests/test_bsi_tls.py: beisst der Waechter?

Jede Probe dreht EINEN Teil des H6-Fixes zurueck (Python-Ersetzung ganzer
Zeilen), laesst den Waechter laufen und erwartet mindestens einen FAIL. Vorher
gruener Basislauf, danach Byte-Gleichheit aller Dateien per md5. Laeuft ohne
Bytecode (PYTHONDONTWRITEBYTECODE=1).

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
WAECHTER = ROOT / "tests" / "test_bsi_tls.py"
RL = "backend/tls_richtlinie.py"
START = "start_jarvis.sh"
DOCKER = "docker/entrypoint.sh"
RUNSH = "run.sh"
MAIN = "backend/main.py"
RUNPY = "run_jarvis.py"
CNF = "backend/openssl_tls.cnf"

SUITES = ("'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:"
          "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:"
          "ECDHE-ECDSA-AES256-SHA384:ECDHE-RSA-AES256-SHA384:"
          "ECDHE-ECDSA-AES128-SHA256:ECDHE-RSA-AES128-SHA256'")

PROBEN = [
    ("Richtlinie wieder 'TLSv1' (der Befund)", RL,
     '    "ECDHE-ECDSA-AES128-SHA256:ECDHE-RSA-AES128-SHA256"\n',
     '    "ECDHE-ECDSA-AES128-SHA256:ECDHE-RSA-AES128-SHA256:TLSv1"\n'),
    ("Richtlinie laesst RSA-Schluesseluebergabe zu", RL,
     '    "ECDHE-ECDSA-AES128-SHA256:ECDHE-RSA-AES128-SHA256"\n',
     '    "ECDHE-ECDSA-AES128-SHA256:ECDHE-RSA-AES128-SHA256:AES256-GCM-SHA384"\n'),
    ("Richtlinie ohne GCM (nur noch CBC-SHA2)", RL,
     '    "ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:"\n'
     '    "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:"\n',
     ''),
    ("start_jarvis.sh ohne --ssl-ciphers", START,
     "    --ssl-ciphers %s \\\n" % SUITES, ''),
    ("start_jarvis.sh mit abweichender Liste", START,
     "    --ssl-ciphers %s \\\n" % SUITES,
     "    --ssl-ciphers 'ECDHE-RSA-AES256-GCM-SHA384' \\\n"),
    ("docker/entrypoint.sh ohne --ssl-ciphers", DOCKER,
     "    --ssl-ciphers %s \\\n" % SUITES, ''),
    ("run.sh ohne --ssl-ciphers", RUNSH,
     " --ssl-ciphers %s --no-server-header" % SUITES, " --no-server-header"),
    ("main.py uvicorn.run ohne ssl_ciphers", MAIN,
     "        ssl_ciphers=TLS12_SUITES,  # BSI H6\n", ''),
    ("run_jarvis.py uvicorn.run ohne ssl_ciphers", RUNPY,
     "        ssl_ciphers=TLS12_SUITES,  # BSI H6\n", ''),
    ("run_jarvis.py: Name da, Import aus anderem Modul", RUNPY,
     "from backend.tls_richtlinie import TLS12_SUITES, konfig_fuer_start\n",
     "from backend.tls_richtlinie import konfig_fuer_start\nTLS12_SUITES = 'TLSv1'\n"),
    # -- TLS 1.3 (H6-Rest, 2026-10-13) --
    ("openssl_tls.cnf laesst CHACHA20 wieder zu", CNF,
     "Ciphersuites = TLS_AES_256_GCM_SHA384:TLS_AES_128_GCM_SHA256\n",
     "Ciphersuites = TLS_AES_256_GCM_SHA384:TLS_AES_128_GCM_SHA256:TLS_CHACHA20_POLY1305_SHA256\n"),
    ("TLS13_SUITES mit Suite ausserhalb der TR", RL,
     'TLS13_SUITES = "TLS_AES_256_GCM_SHA384:TLS_AES_128_GCM_SHA256"\n',
     'TLS13_SUITES = "TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256"\n'),
    ("konfig_uebernehmen laesst OPENSSL_CONF stehen", RL,
     '        os.environ.pop("OPENSSL_CONF", None)\n', ''),
    ("start_jarvis.sh ohne OPENSSL_CONF", START,
     '[ -r ./backend/openssl_tls.cnf ] && [ -r /etc/ssl/openssl.cnf ] && export OPENSSL_CONF="$JARVIS_DIR/backend/openssl_tls.cnf"\n', ''),
    ("docker/entrypoint.sh ohne OPENSSL_CONF", DOCKER,
     '[ -r /app/backend/openssl_tls.cnf ] && [ -r /etc/ssl/openssl.cnf ] && export OPENSSL_CONF="/app/backend/openssl_tls.cnf"\n', ''),
    ("run.sh ohne OPENSSL_CONF", RUNSH,
     '[ -r ./backend/openssl_tls.cnf ] && [ -r /etc/ssl/openssl.cnf ] && export OPENSSL_CONF="$SCRIPT_DIR/backend/openssl_tls.cnf"\n', ''),
    ("run_jarvis.py ohne konfig_fuer_start", RUNPY,
     "    konfig_fuer_start()  # BSI H6-Rest: TLS 1.3-Suiten (erbt der Reload-Worker)\n", ''),
    ("main.py __main__ ohne konfig_fuer_start", MAIN,
     "    konfig_fuer_start()  # BSI H6-Rest: TLS 1.3-Suiten (erbt der Reload-Worker)\n", ''),
    ("main.py ruft konfig_uebernehmen nicht", MAIN,
     "if _tls_richtlinie.konfig_uebernehmen():\n", "if True:\n"),
]

DATEIEN = [RL, START, DOCKER, RUNSH, MAIN, RUNPY, CNF, "tests/test_bsi_tls.py"]


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
