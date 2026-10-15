#!/usr/bin/env python3
"""Gegenprobe zu tests/test_signatur_h1.py: beisst der Waechter?

Jede Probe dreht EINEN Teil zurueck (Python-Ersetzung ganzer Zeilen), laesst den
Waechter laufen und erwartet mindestens einen FAIL. Vorher gruener Basislauf,
danach Byte-Gleichheit aller Dateien per md5, ohne Bytecode.

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
W = ROOT / "tests" / "test_signatur_h1.py"
INST = "deploy/security/broker_installieren.sh"
EINR = "deploy/security/signatur_einrichten.sh"
UM = "backend/update_manager.py"

PROBEN = [
    ("Installer prueft die Signatur nicht", W, INST,
     '        if ! git -C "$CACHE" -c gpg.ssh.allowedSignersFile="$SIGNERS" -c gpg.ssh.program=/usr/bin/ssh-keygen \\\n'
     '                verify-commit HEAD >/dev/null 2>&1; then\n',
     '        if false; then\n'),
    ("Installer vertraut fremd beschreibbarem Anker", W, INST,
     '        root_privat "$SIGNERS" 022 \\\n',
     '        true \\\n'),
    ("App-Update zieht ohne Pruefung", W, UM,
     '    rc, out, err = _git(*sig_opt, "pull", "--ff-only", "origin", branch, timeout=60)\n',
     '    rc, out, err = _git("pull", "--ff-only", "origin", branch, timeout=60)\n'),
    ("App-Update ohne merge.verifySignatures", W, UM,
     '            "-c", "merge.verifySignatures=true"]\n',
     '            ]\n'),
    ("Signaturstatus immer ok", W, UM,
     '    return "ok" if rc == 0 else "fehlt"\n',
     '    return "ok"\n'),
    # KEINE Probe fuer die Pflicht-Zeile "--fingerabdruck fehlt": ohne jeden
    # Fingerabdruck scheitert jede Schluesselzeile ohnehin am Vergleich darunter
    # (gemessen 2026-09-30: ohne die Zeile 0 FAIL, die Zusage gilt trotzdem).
    # Sie bleibt als Guertel – und fuer die verstaendlichere Meldung.
    ("Einrichtung ohne Fingerabdruck-Vergleich", W, EINR,
     '    [ "$OK" = 1 ] || fehler "Schluessel ${FP:-?} in $SIGNERS ist nicht bestaetigt (--fingerabdruck) – nichts verankert."\n',
     '    true\n'),
    ("Einrichtung ohne Zeilenpruefung", W, EINR,
     '    [[ "$z" =~ ^[A-Za-z0-9._@-]+\\ namespaces=\\"git\\"\\ ssh-ed25519\\ [A-Za-z0-9+/]+=*$ ]] \\\n',
     '    [[ -n "$z" ]] \\\n'),
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

    fails, rc = lauf(W)
    if fails != 0:
        print("ABBRUCH: Basislauf nicht gruen (FAIL=%s, rc=%s)" % (fails, rc))
        return 2
    print("Basislauf gruen.\n")

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
