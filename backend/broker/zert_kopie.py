#!/usr/bin/env python3
"""Let's-Encrypt-Zertifikat als root in ``<projekt>/certs`` ablegen – ohne Symlinks zu folgen.

Code-Review 2026-10-18: Op ``certbot_obtain`` und ihr Renewal-Hook schrieben
als root mit ``cp -L``/``chmod``/``chown`` (bzw. ``copy2``/``os.chown``) in
``certs/`` – ein Verzeichnis, das dem DIENSTBENUTZER gehoert. Legt der dort
einen Symlink ``server.key -> /etc/shadow`` an, ueberschrieb root bei jeder
Erneuerung das Ziel und gab es dem Dienstbenutzer. Dieselbe Klasse wie der
K1-/Symlink-Befund vom 2026-10-07.

Jetzt ueber Verzeichnis-Deskriptoren:
  1. ``certs`` wird relativ zu seinem Elternverzeichnis mit ``O_NOFOLLOW``
     geoeffnet (ein Symlink an seiner Stelle scheitert),
  2. jede Datei entsteht NEU (``O_EXCL|O_NOFOLLOW``) unter einem Zufallsnamen,
     bekommt ``fchmod``/``fchown`` am Deskriptor,
  3. ``os.replace`` mit ``dir_fd`` ersetzt den VERZEICHNISEINTRAG – ein
     vorhandener Symlink wird ersetzt, sein Ziel nie beschrieben.

Eigenstaendig (nur Standardbibliothek): der Renewal-Hook ruft die Datei mit
dem System-Python aus der root-eigenen Broker-Kopie auf.

    zert_kopie.py <domain> <certs-verzeichnis> <dienstbenutzer>
"""
from __future__ import annotations

import os
import pwd
import re
import secrets
import sys

LE_LIVE = "/etc/letsencrypt/live"
DATEIEN = (("fullchain.pem", "server.crt", 0o644), ("privkey.pem", "server.key", 0o600))


def _lesen(pfad: str) -> bytes:
    with open(pfad, "rb") as f:
        return f.read()


def _verzeichnis_oeffnen(pfad: str) -> int:
    """``pfad`` oeffnen, letzte Komponente OHNE Symlink-Folgen."""
    eltern, name = os.path.split(os.path.abspath(pfad))
    efd = os.open(eltern, os.O_RDONLY | os.O_DIRECTORY)
    try:
        return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=efd)
    finally:
        os.close(efd)


def kopieren(domain: str, ziel_dir: str, uid: int, gid: int,
             quelle_dir: str | None = None) -> list[str]:
    """Kopiert fullchain/privkey nach ``ziel_dir`` (server.crt/server.key). Wirft bei Fehlern."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.\-]{0,252}", domain or ""):
        raise ValueError("ungueltige Domain")
    quelle_dir = quelle_dir or os.path.join(LE_LIVE, domain)
    inhalte = {ziel: (_lesen(os.path.join(quelle_dir, quelle)), modus)
               for quelle, ziel, modus in DATEIEN}
    dfd = _verzeichnis_oeffnen(ziel_dir)
    geschrieben = []
    try:
        for ziel, (daten, modus) in inhalte.items():
            tmp = f".{ziel}.{secrets.token_hex(6)}.neu"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dfd)
            try:
                os.write(fd, daten)
                os.fsync(fd)
                os.fchown(fd, uid, gid)
                os.fchmod(fd, modus)   # nach fchown: ein chown loescht setuid-Bits
            finally:
                os.close(fd)
            try:
                os.replace(tmp, ziel, src_dir_fd=dfd, dst_dir_fd=dfd)
            except BaseException:
                try:
                    os.unlink(tmp, dir_fd=dfd)
                except OSError:
                    pass
                raise
            geschrieben.append(ziel)
    finally:
        os.close(dfd)
    return geschrieben


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    domain, ziel_dir, benutzer = argv[1:]
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", benutzer):
        print("ungueltiger Dienstbenutzer", file=sys.stderr)
        return 2
    pw = pwd.getpwnam(benutzer)
    if pw.pw_uid == 0:
        print("Dienstbenutzer darf nicht root sein", file=sys.stderr)
        return 2
    try:
        dateien = kopieren(domain, ziel_dir, pw.pw_uid, pw.pw_gid)
    except (OSError, ValueError) as e:
        print(f"Zertifikat nicht abgelegt: {e}", file=sys.stderr)
        return 1
    print("abgelegt: " + ", ".join(dateien))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
