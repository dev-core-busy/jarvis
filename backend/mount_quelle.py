"""Quellangabe einer Netzwerk-Freigabe pruefen und normalisieren.

WARUM ES DIESES MODUL GIBT (Vorgabe des Betreibers, 2026-09-04): "wenn im
'SMB/CIFS' Fall ein falsch formatierter Pfad versucht wird einzugeben, muss das
abgefangen werden". Bis dahin nahm ``POST /api/knowledge/mounts`` JEDE nicht
leere Zeichenkette an; der Fehler fiel erst beim Klick auf "Verbinden" auf –
und dort nach bis zu 10 Sekunden Netz-Timeout, mit einer Meldung des Systems
statt einer Auskunft ueber die Eingabe.

ZWEI DINGE, DIE ZUSAMMENGEHOEREN
--------------------------------
1. **Abweisen, was nicht mountbar ist** – und zwar beim ANLEGEN, nicht beim
   Verbinden. Eine gespeicherte Freigabe, die nie funktionieren kann, ist ein
   Fehler, der auf seinen Entdecker wartet.
2. **Normalisieren, was gemeint ist.** Ein Administrator kennt aus Windows
   ``\\\\server\\freigabe`` und aus dem Dateimanager ``smb://server/freigabe``.
   Beides IST die Freigabe, die er meint – das abzulehnen waere Schikane.
   Gespeichert wird die Form, die ``mount -t cifs`` versteht.

DIE REGEL LIEGT HIER UND NUR HIER. main.py prueft damit die Eingabe, der
Root-Broker dieselbe Angabe noch einmal vor dem ``mount`` (Tiefenverteidigung).
Zwei Fassungen liefen beim naechsten Feinschliff auseinander – dieselbe Lehre
wie bei den vier ``_client()``-Stellen des Jira-Zugangs.
"""

import re

# Hostname, FQDN, IPv4 – oder IPv6 in eckigen Klammern (die Form, die
# mount.cifs akzeptiert). Bewusst KEINE Aufloesung: ob der Name existiert,
# entscheidet das Netz beim Verbinden, nicht ein Eingabefeld.
_HOST = r"(?:\[[0-9A-Fa-f:]+\]|[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)"
_HOST_RE = re.compile(rf"^{_HOST}$")

# Steuerzeichen und Zeilenumbrueche haben in einem Mount-Argument nichts zu
# suchen – sie kaemen sonst in einer /etc/davfs2/secrets-Zeile oder in einer
# Journal-Zeile wieder heraus.
_VERBOTEN_RE = re.compile(r"[\x00-\x1f\x7f]")

BEISPIEL = {
    "smb": "//server/freigabe",
    "nfs": "server:/export",
    "webdav": "https://server/pfad",
}


def pruefe(mount_type: str, quelle: str) -> tuple[str, str]:
    """(normalisierte Quelle, Fehlertext). Fehlertext leer = in Ordnung.

    Der Fehlertext nennt IMMER ein Beispiel. "Ungueltige Quelle" ist richtig
    und trotzdem nutzlos – dieselbe Klasse wie "mount error(13)".
    """
    typ = (mount_type or "smb").strip().lower()
    roh = (quelle or "").strip()
    if not roh:
        return "", f"Es fehlt die Quelle. Beispiel: {BEISPIEL.get(typ, BEISPIEL['smb'])}"
    if _VERBOTEN_RE.search(roh):
        return "", "Die Quelle enthaelt Steuerzeichen oder Zeilenumbrueche."
    if len(roh) > 255:
        return "", "Die Quelle ist zu lang (hoechstens 255 Zeichen)."

    if typ == "smb":
        return _smb(roh)
    if typ == "nfs":
        return _nfs(roh)
    if typ == "webdav":
        return _webdav(roh)
    return "", (f"Unbekannter Freigabetyp '{mount_type}' – moeglich sind "
                f"SMB/CIFS, NFS und WebDAV.")


def _smb(roh: str) -> tuple[str, str]:
    """//server/freigabe – und alles, was erkennbar dasselbe meint."""
    s = roh
    # Windows-Schreibweise und die URL-Form des Dateimanagers: BEIDE sind
    # gemeint, nur anders getippt. mount -t cifs versteht nur die Slash-Form.
    if s.lower().startswith(("smb://", "cifs://")):
        s = "//" + s.split("://", 1)[1]
    s = s.replace("\\", "/")
    s = re.sub(r"^/{2,}", "//", s)          # ///srv → //srv
    if not s.startswith("//"):
        # Der haeufigste Tippfehler: "server/freigabe" ohne die zwei Slashes.
        if re.match(rf"^{_HOST}/[^/]", s):
            return "", (f"Vor dem Servernamen fehlen zwei Schraegstriche. "
                        f"Gemeint ist vermutlich '//{s}'.")
        if re.match(r"^[A-Za-z]:", s) or s.startswith("/"):
            return "", ("Das ist ein lokaler Pfad, keine Netzwerk-Freigabe. "
                        "Eine SMB-Freigabe wird als //server/freigabe angegeben.")
        return "", ("Eine SMB-Freigabe wird als //server/freigabe angegeben "
                    "(die Windows-Schreibweise \\\\server\\freigabe wird "
                    "ebenfalls angenommen).")

    rest = s[2:]
    if "/" not in rest.rstrip("/"):
        # //server allein: mount meldet dazu "Malformed UNC in devname".
        host = rest.strip("/")
        return "", (f"Es fehlt der Name der Freigabe – '//{host}' ist nur der "
                    f"Server. Richtig waere zum Beispiel '//{host}/freigabe'.")
    host, _, share = rest.partition("/")
    if not _HOST_RE.match(host):
        return "", (f"'{host}' ist kein gueltiger Servername. Erlaubt sind "
                    f"Name, FQDN oder IP-Adresse – Beispiel: //{BEISPIEL['smb'][2:]}")
    share = share.strip("/")
    if not share:
        return "", (f"Es fehlt der Name der Freigabe – richtig waere zum "
                    f"Beispiel '//{host}/freigabe'.")
    # Fuehrende/abschliessende Schraegstriche vereinheitlichen; Leerzeichen IM
    # Freigabenamen sind erlaubt (die gibt es in Windows-Netzen staendig).
    return f"//{host}/{share}", ""


def _nfs(roh: str) -> tuple[str, str]:
    """server:/export – der Doppelpunkt ist der Unterschied zu einem Pfad."""
    s = roh.replace("\\", "/")
    if s.lower().startswith("nfs://"):
        # nfs://server/export → server:/export
        rest = s.split("://", 1)[1]
        host, _, pfad = rest.partition("/")
        s = f"{host}:/{pfad}" if host else s
    if ":" not in s:
        if s.startswith("/"):
            return "", ("Das ist ein lokaler Pfad. Eine NFS-Freigabe wird als "
                        "server:/export angegeben.")
        return "", ("Es fehlt der Doppelpunkt: eine NFS-Freigabe wird als "
                    "server:/export angegeben.")
    host, _, pfad = s.partition(":")
    if not _HOST_RE.match(host):
        return "", (f"'{host}' ist kein gueltiger Servername – Beispiel: "
                    f"{BEISPIEL['nfs']}")
    if not pfad.startswith("/"):
        return "", (f"Nach dem Doppelpunkt gehoert ein absoluter Pfad – "
                    f"gemeint ist vermutlich '{host}:/{pfad}'.")
    return f"{host}:{pfad.rstrip('/') or '/'}", ""


def _webdav(roh: str) -> tuple[str, str]:
    """http(s)://server/pfad – davfs2 nimmt nichts anderes."""
    s = roh
    if s.lower().startswith(("dav://", "davs://")):
        schema, _, rest = s.partition("://")
        s = ("https://" if schema.lower() == "davs" else "http://") + rest
    if not s.lower().startswith(("http://", "https://")):
        return "", ("Eine WebDAV-Freigabe wird als https://server/pfad "
                    "angegeben.")
    rest = s.split("://", 1)[1]
    host = rest.split("/", 1)[0].split("@")[-1].split(":")[0]
    if not host or not _HOST_RE.match(host):
        return "", (f"Die Adresse enthaelt keinen gueltigen Servernamen – "
                    f"Beispiel: {BEISPIEL['webdav']}")
    return s.rstrip("/") or s, ""
