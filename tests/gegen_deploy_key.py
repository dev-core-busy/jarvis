#!/usr/bin/env python3
"""Gegenprobe zu tests/test_deploy_key.py: beisst der Waechter?

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
W = ROOT / "tests" / "test_deploy_key.py"
INST = "deploy/security/broker_installieren.sh"
EINR = "deploy/security/deploy_key_einrichten.sh"
UM = "backend/update_manager.py"

PROBEN = [
    ("Schluessel-Rechte nicht geprueft", W, INST,
     '        root_privat "$SCHLUESSEL" 077 \\\n',
     '        true \\\n'),
    # KEINE Probe fuer das "[ ! -L ]" in root_privat: stat ohne -L sieht bei
    # einem Link den Link selbst (Modus 0777) – die Rechtepruefung lehnt ihn
    # schon deshalb ab. Gemessen 2026-09-30: ohne die Zeile 0 FAIL, weil die
    # Zusage auch ohne sie gilt. Die Zeile bleibt als Guertel.
    ("Host-Anker nicht geprueft", W, INST,
     '        root_privat "$KNOWN" 022 \\\n',
     '        true \\\n'),
    ("Host-Schluessel beim ersten Kontakt vertraut", W, INST,
     '        SSH="$SSH -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$KNOWN -o GlobalKnownHostsFile=/dev/null"\n',
     '        SSH="$SSH -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$KNOWN -o GlobalKnownHostsFile=/dev/null"\n'),
    ("ssh_config redet mit", W, INST,
     '        SSH="ssh -F /dev/null -i $SCHLUESSEL -o IdentitiesOnly=yes -o BatchMode=yes"\n',
     '        SSH="ssh -i $SCHLUESSEL -o IdentitiesOnly=yes -o BatchMode=yes"\n'),
    ("Bestands-Cache behaelt alte Adresse", W, INST,
     '        git -C "$CACHE" remote set-url origin "$REPO" \\\n',
     '        true \\\n'),
    ("Schluesselnamen mit Ziffern wieder ungelesen", W, INST,
     "        done < <(grep -E '^[A-Z0-9_]+=' \"$KONF\")\n",
     "        done < <(grep -E '^[A-Z_]+=' \"$KONF\")\n"),
    ("REPO-Pruefung offen", W, INST,
     '                REPO)       [[ "$v" =~ ^(https://[A-Za-z0-9./_-]+|git@github\\.com:[A-Za-z0-9._-]+/[A-Za-z0-9._-]+\\.git)$ ]] && REPO="$v" ;;\n',
     '                REPO)       REPO="$v" ;;\n'),
    ("Einrichtung: andere ssh-Optionen als der Installer", W, EINR,
     '    s="$s -o HostKeyAlias=github.com -o HostKeyAlgorithms=ssh-ed25519 -o ConnectTimeout=20"\n',
     '    s="$s -o HostKeyAlias=github.com -o ConnectTimeout=20"\n'),
    ("Einrichtung: falscher Host-Schluessel", W, EINR,
     'GITHUB_HOSTKEY="github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"\n',
     'GITHUB_HOSTKEY="github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJm"\n'),
    # core.sshCommand im Baum des Dienstbenutzers (2026-10-11). Jede Probe
    # stellt einen Teil des Zustands wieder her, der bis dahin auf DEV galt:
    # der Abruf des Dienstbenutzers gelang nur ueber ~/.ssh/config als
    # Rueckfall, waehrend core.sshCommand auf den fuer ihn unlesbaren
    # root-Schluessel zeigte.
    ("Einrichtung: core.sshCommand zeigt wieder auf den root-Schluessel", W, EINR,
     '    "ssh -i $K -o IdentitiesOnly=yes',
     '    "ssh -i /root/.ssh/jarvis_broker_deploy -o IdentitiesOnly=yes'),
    ("Einrichtung: core.sshCommand gar nicht gesetzt", W, EINR,
     'git -C "$DIR" config core.sshCommand \\\n', 'true \\\n'),
    ("Einrichtung: core.sshCommand ohne festgenagelten Hostkey", W, EINR,
     ' -o StrictHostKeyChecking=yes"\n', '"\n'),
    ("update_manager: Zugangsfehler ohne Hinweis", W, UM,
     '        if _gitfehler_zugang(fehler, *roh):\n',
     '        if False:\n'),
    ("update_manager: publickey nicht erkannt", W, UM,
     '        "could not read username", "permission denied (publickey)",\n',
     '        "could not read username",\n'),
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
