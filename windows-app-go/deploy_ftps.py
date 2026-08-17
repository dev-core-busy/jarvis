#!/usr/bin/env python3
"""FTPS-Uebertragung fuer den Landing-Page-Deploy (jarvis-ai.info).

Warum FTPS und nicht SSH: der SSH-Zugang des Abo-Benutzers laeuft in eine defekte
chroot-Umgebung (Shell UND sftp-server scheitern mit Exit 255), siehe Memory
`landing-page-deploy-defekt`. FTPS dagegen ist am Server korrekt aktiviert.

WICHTIG – Netzweg: Manche Firmennetze betreiben einen FTP-ALG, der das Kommando
`AUTH TLS` abfaengt und mit `502 ... contact your network administrator` beantwortet.
Dann kommt TLS gar nicht erst zustande. Das ist KEIN Zertifikats- und KEIN Server-
problem: aus einem Netz ohne ALG (Homeoffice, Mobilfunk/Tethering, VPN) laeuft
derselbe Aufruf fehlerfrei. Diese Datei erkennt den Fall und sagt es im Klartext.

Zugangsdaten (NIE ins Repo – es ist oeffentlich):
  1. Umgebungsvariablen JARVIS_FTPS_USER / JARVIS_FTPS_PASS, oder
  2. Datei `windows-app-go/.ftps_credentials` (gitignored), Format:
         JARVIS_FTPS_USER=jarvis
         JARVIS_FTPS_PASS=...

Aufruf:
    deploy_ftps.py put    <lokal>   <fern>     Datei hochladen
    deploy_ftps.py get    <fern>    <lokal>    Datei herunterladen
    deploy_ftps.py putstr <fern>               stdin als Datei hochladen
    deploy_ftps.py check                       nur Verbindung/Anmeldung pruefen
"""
import ftplib
import os
import ssl
import sys
from pathlib import Path

HOST = os.environ.get("JARVIS_FTPS_HOST", "jarvis-ai.info")
PORT = int(os.environ.get("JARVIS_FTPS_PORT", "21"))
DOCROOT = os.environ.get("JARVIS_DOCROOT", "/var/www/vhosts/jarvis-ai.info/www")

_ALG_HINWEIS = """
╔══════════════════════════════════════════════════════════════════════════════╗
║ FTPS wird in DIESEM Netz blockiert (FTP-ALG faengt 'AUTH TLS' ab).           ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ Das ist WEDER ein Server- NOCH ein Zertifikatsproblem:                       ║
║ die Verbindung wird abgebrochen, BEVOR ueberhaupt ein Zertifikat             ║
║ ausgetauscht wird. Ein importiertes Zertifikat hilft deshalb NICHT.          ║
║                                                                              ║
║ Abhilfe – eine davon genuegt:                                                ║
║   * Netz ohne ALG nutzen: Handy-Tethering/Hotspot oder VPN                   ║
║   * Plesk-Dateimanager im Browser: https://jarvis-ai.info:8443               ║
║   * Hoster bitten, FTPS zusaetzlich auf Port 990 (implizit) anzubieten –     ║
║     ALGs haengen an Port 21, ein anderer Port umgeht sie dauerhaft.          ║
╚══════════════════════════════════════════════════════════════════════════════╝"""


def _zugangsdaten() -> tuple[str, str]:
    """Benutzer/Kennwort aus Umgebung oder .ftps_credentials lesen."""
    user = os.environ.get("JARVIS_FTPS_USER", "")
    pw = os.environ.get("JARVIS_FTPS_PASS", "")
    if not (user and pw):
        cred = Path(__file__).parent / ".ftps_credentials"
        if cred.exists():
            for zeile in cred.read_text(encoding="utf-8").splitlines():
                zeile = zeile.strip()
                if not zeile or zeile.startswith("#") or "=" not in zeile:
                    continue
                k, _, v = zeile.partition("=")
                v = v.strip().strip('"').strip("'")
                if k.strip() == "JARVIS_FTPS_USER" and not user:
                    user = v
                elif k.strip() == "JARVIS_FTPS_PASS" and not pw:
                    pw = v
    if not (user and pw):
        sys.exit(
            "FEHLER: Keine FTPS-Zugangsdaten.\n"
            "  Entweder JARVIS_FTPS_USER/JARVIS_FTPS_PASS setzen, oder\n"
            f"  {Path(__file__).parent / '.ftps_credentials'} anlegen (gitignored):\n"
            "      JARVIS_FTPS_USER=jarvis\n"
            "      JARVIS_FTPS_PASS=<kennwort>"
        )
    return user, pw


class _FtpsSessionReuse(ftplib.FTP_TLS):
    """ProFTPD verlangt haeufig, dass die Datenverbindung die TLS-Sitzung der
    Steuerverbindung WIEDERVERWENDET (`TLSOptions NoSessionReuseRequired` ist
    nicht gesetzt). Ohne das scheitert jeder Transfer mit '425 Unable to build
    data connection', obwohl die Anmeldung geklappt hat. Python's ftplib macht
    das von sich aus nicht – daher dieser Ueberbau."""

    def ntransfercmd(self, cmd, rest=None):
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            try:
                conn = self.sock.context.wrap_socket(
                    conn, server_hostname=self.host, session=self.sock.session
                )
            except Exception:
                # Server verlangt keine Wiederverwendung -> normal verpacken
                conn = self.sock.context.wrap_socket(conn, server_hostname=self.host)
        return conn, size


def verbinden() -> ftplib.FTP_TLS:
    """Baut eine angemeldete FTPS-Verbindung auf (explizites TLS, Port 21)."""
    user, pw = _zugangsdaten()
    # Selbstsigniertes Zertifikat -> keine Pruefung. Vertretbar, weil nur der
    # Upload der oeffentlichen Landing-Page darueber laeuft. Genau diese Abfrage
    # bestaetigt man im GUI-Client von Hand.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    f = _FtpsSessionReuse(context=ctx)
    try:
        f.connect(HOST, PORT, timeout=30)
    except OSError as e:
        sys.exit(f"FEHLER: {HOST}:{PORT} nicht erreichbar – {type(e).__name__}: {e}")

    try:
        f.auth()                      # AUTH TLS – hier schlaegt ein ALG zu
    except ftplib.error_perm as e:
        if "502" in str(e):
            print(_ALG_HINWEIS, file=sys.stderr)
            sys.exit(2)
        sys.exit(f"FEHLER bei AUTH TLS: {e}")

    try:
        f.login(user, pw)
    except ftplib.error_perm as e:
        sys.exit(f"FEHLER: Anmeldung als '{user}' abgelehnt – {e}")

    f.prot_p()                        # Datenkanal ebenfalls verschluesseln
    f.set_pasv(True)
    return f


def _cd(f: ftplib.FTP_TLS, fernpfad: str) -> str:
    """Wechselt in das Zielverzeichnis und gibt den Dateinamen zurueck.
    Relative Pfade sind relativ zum DOCROOT."""
    pfad = fernpfad if fernpfad.startswith("/") else f"{DOCROOT}/{fernpfad}"
    ordner, _, name = pfad.rpartition("/")
    if ordner:
        try:
            f.cwd(ordner)
        except ftplib.error_perm as e:
            sys.exit(f"FEHLER: Zielordner '{ordner}' nicht erreichbar – {e}")
    return name


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    aktion = sys.argv[1]

    if aktion == "check":
        f = verbinden()
        print(f"OK – angemeldet, Arbeitsverzeichnis: {f.pwd()}")
        f.quit()
        return

    if aktion == "put" and len(sys.argv) == 4:
        lokal, fern = sys.argv[2], sys.argv[3]
        if not Path(lokal).is_file():
            sys.exit(f"FEHLER: lokale Datei fehlt: {lokal}")
        f = verbinden()
        name = _cd(f, fern)
        with open(lokal, "rb") as fh:
            f.storbinary(f"STOR {name}", fh)
        print(f"hochgeladen: {lokal} -> {fern} ({Path(lokal).stat().st_size} Bytes)")
        f.quit()
        return

    if aktion == "putstr" and len(sys.argv) == 3:
        import io
        daten = sys.stdin.buffer.read()
        f = verbinden()
        name = _cd(f, sys.argv[2])
        f.storbinary(f"STOR {name}", io.BytesIO(daten))
        print(f"hochgeladen: <stdin> -> {sys.argv[2]} ({len(daten)} Bytes)")
        f.quit()
        return

    if aktion == "get" and len(sys.argv) == 4:
        fern, lokal = sys.argv[2], sys.argv[3]
        f = verbinden()
        name = _cd(f, fern)
        with open(lokal, "wb") as fh:
            f.retrbinary(f"RETR {name}", fh.write)
        print(f"geladen: {fern} -> {lokal} ({Path(lokal).stat().st_size} Bytes)")
        f.quit()
        return

    sys.exit(__doc__)


if __name__ == "__main__":
    main()
