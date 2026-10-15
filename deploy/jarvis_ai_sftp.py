#!/usr/bin/env python3
"""SFTP-Uebertragung fuer jarvis-ai.info (Downloads + Landing-Page), Port 8023.

WARUM DIESER WEG (2026-10-12): SSH auf Port 22 (``scp``) und FTPS auf Port 21
sind von hier aus tot – ``scp`` endet mit "Connection closed", FTPS faengt ein
FTP-ALG im Firmennetz ab. Seit 2026-08-17 gibt es einen eigenen SFTP-Dienst
(ProFTPD ``mod_sftp``) auf Port 8023; er bietet NUR Kennwort-Anmeldung.

Warum paramiko und nicht ``sshpass`` + ``sftp``: ``sftp -b`` erzwingt
BatchMode und schaltet die Kennwort-Anmeldung ab ("Permission denied" bei
korrektem Kennwort), und ``sshpass`` erkennt die Abfrage von mod_sftp nicht
zuverlaessig. Beides ist so passiert.

Der Zugang ist ein chroot ins Abo-Verzeichnis: die Website liegt unter
``www/``. Pfade fuer put/get/putstr sind RELATIV ZUR WEBSITE
(``downloads/jarvis.apk``); Sicherungen landen bewusst AUSSERHALB von ``www/``
– im Docroot waeren sie oeffentlich abrufbar (2026-08-17: HTTP 200).

Hochladen ist atomar (Nebendatei + posix_rename): ein abgebrochener Upload
hinterlaesst nie eine halbe APK, die das Auto-Update dann verteilt.

Zugangsdaten (NIE ins Repo – es ist oeffentlich) in ``.env`` bzw. Umgebung:
    JARVIS_SFTP_PASS   Pflicht
    JARVIS_SFTP_USER   Vorgabe "jarvis"
    JARVIS_SFTP_HOST   Vorgabe ftp.jarvis-ai.info
    JARVIS_SFTP_PORT   Vorgabe 8023

Aufruf:
    jarvis_ai_sftp.py check                          Anmeldung pruefen
    jarvis_ai_sftp.py put     <lokal> <fern>         Datei hochladen (atomar)
    jarvis_ai_sftp.py putstr  <fern>                 stdin als Datei hochladen
    jarvis_ai_sftp.py get     <fern>  <lokal>        Datei herunterladen
    jarvis_ai_sftp.py cat     <fern>                 Datei nach stdout
    jarvis_ai_sftp.py sichern <fern>  <name>         Kopie ausserhalb von www/
                                                     (nur wenn <name> noch fehlt)
Exit 0 = erledigt, 1 = Fehler, 2 = Zugangsdaten fehlen.
"""
import io
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ziele  # noqa: E402

WEBSITE = "www"


def _verbinden():
    try:
        import paramiko  # noqa: PLC0415
    except ImportError:
        sys.exit("FEHLER: paramiko fehlt (pip install paramiko)")
    pw = ziele.finde("JARVIS_SFTP_PASS")
    if not pw:
        print("FEHLER: JARVIS_SFTP_PASS fehlt – in .env eintragen (nie ins Repo).", file=sys.stderr)
        sys.exit(2)
    user = ziele.finde("JARVIS_SFTP_USER") or "jarvis"
    host = ziele.finde("JARVIS_SFTP_HOST") or "ftp.jarvis-ai.info"
    port = int(ziele.finde("JARVIS_SFTP_PORT") or "8023")
    try:
        s = socket.create_connection((host, port), timeout=25)
    except OSError as e:
        sys.exit("FEHLER: %s:%d nicht erreichbar – %s" % (host, port, e))
    tr = paramiko.Transport(s)
    tr.start_client(timeout=25)
    try:
        tr.auth_password(user, pw)
    except paramiko.AuthenticationException:
        sys.exit("FEHLER: Anmeldung als '%s' abgelehnt" % user)
    return tr, paramiko.SFTPClient.from_transport(tr)


def _web(fern: str) -> str:
    """Pfad relativ zur Website; kein Ausbruch per '..' oder absolutem Pfad."""
    teile = [t for t in fern.split("/") if t not in ("", ".")]
    if not teile or ".." in teile:
        sys.exit("FEHLER: ungueltiger Pfad: %r" % fern)
    return "/".join([WEBSITE] + teile)


def _hoch(sf, daten: bytes, ziel: str):
    tmp = ziel + ".upload.tmp"
    sf.putfo(io.BytesIO(daten), tmp)
    if sf.stat(tmp).st_size != len(daten):
        sf.remove(tmp)
        sys.exit("FEHLER: Upload unvollstaendig: %s" % ziel)
    sf.posix_rename(tmp, ziel)


def main() -> None:
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    befehl = a[0]
    if befehl == "check" and len(a) == 1:
        tr, sf = _verbinden()
        print("OK – angemeldet, Website-Ordner: %s" % ("vorhanden" if WEBSITE in sf.listdir(".") else "FEHLT"))
    elif befehl == "put" and len(a) == 3:
        lokal = Path(a[1])
        if not lokal.is_file():
            sys.exit("FEHLER: lokale Datei fehlt: %s" % lokal)
        daten = lokal.read_bytes()
        tr, sf = _verbinden()
        _hoch(sf, daten, _web(a[2]))
        print("hochgeladen: %s -> %s (%d Bytes)" % (lokal, a[2], len(daten)))
    elif befehl == "putstr" and len(a) == 2:
        daten = sys.stdin.buffer.read()
        tr, sf = _verbinden()
        _hoch(sf, daten, _web(a[1]))
        print("hochgeladen: <stdin> -> %s (%d Bytes)" % (a[1], len(daten)))
    elif befehl == "get" and len(a) == 3:
        tr, sf = _verbinden()
        sf.get(_web(a[1]), a[2])
        print("geladen: %s -> %s (%d Bytes)" % (a[1], a[2], Path(a[2]).stat().st_size))
    elif befehl == "cat" and len(a) == 2:
        tr, sf = _verbinden()
        b = io.BytesIO()
        sf.getfo(_web(a[1]), b)
        sys.stdout.buffer.write(b.getvalue())
    elif befehl == "sichern" and len(a) == 3:
        name = a[2]
        if "/" in name or name in ("", ".", "..", WEBSITE):
            sys.exit("FEHLER: Sicherungsname ohne Pfad angeben: %r" % name)
        tr, sf = _verbinden()
        try:
            sf.stat(name)
            print("Sicherung existiert schon: %s" % name)
        except IOError:
            b = io.BytesIO()
            sf.getfo(_web(a[1]), b)
            _hoch(sf, b.getvalue(), name)
            print("gesichert: %s -> %s (ausserhalb der Website, %d Bytes)" % (a[1], name, len(b.getvalue())))
    else:
        sys.exit(__doc__)
    sf.close()
    tr.close()


if __name__ == "__main__":
    main()
