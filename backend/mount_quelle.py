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


# ─── Rueckrichtung: Serverpfad -> Netzwerkpfad ───────────────────────────────
# WARUM (Vorgabe des Betreibers, 2026-09-08): eine /chat-Antwort nannte als
# Quelle "Ordner share_0/0039_Maris/Anleitungen SAP.one". Das ist der
# EINHAENGEPUNKT auf dem Server – eine Nummer, die niemand kennt und die der
# Benutzer nirgends oeffnen kann. Er soll die Quelle anklicken bzw. in den
# Explorer kopieren koennen, also
# "\\191.100.147.90\OneNote_text_Jasmin\0039_Maris\Anleitungen SAP.one".
#
# Die Zuordnung MUSS hier liegen und nicht beim Aufrufer: die Regel "welche
# Schreibweise meint dieselbe Freigabe" steht in `pruefe()` – eine zweite,
# nachgebaute Fassung liefe beim naechsten Feinschliff auseinander (der
# Altbestand auf DEV traegt seine Quelle bis heute in Windows-Schreibweise,
# `\\191.100.147.90\Dokumentationen`; nur `pruefe()` versteht beides).


def netzpfad(mounts, pfad: str) -> str:
    """Serverpfad einer Wissensdatei -> Netzwerkpfad. "" = kein Netzwerkpfad.

    ``mounts`` ist die Freigabenliste aus der Knowledge-Skill-Konfiguration
    (je Eintrag ``mountpoint``, ``type``, ``source``).

    FAIL-OPEN, und die Richtung ist Absicht: unbekannter Pfad, kaputter
    Eintrag, unbrauchbare Quelle -> "" , und der Aufrufer laesst den
    technischen Pfad stehen. Ein geratener Netzwerkpfad waere schlimmer als der
    Einhaengepunkt – er sieht anklickbar aus und fuehrt ins Nichts.

    Verglichen wird EINTRAGSWEISE, nicht als Teilstring: "/mnt/jarvis-kb/share_1"
    steckt in "/mnt/jarvis-kb/share_10". Bei mehreren passenden Einhaengepunkten
    (einer unter dem anderen) gewinnt der laengste – der ist der spezifischere.
    """
    p = str(pfad or "").strip()
    if not p or not isinstance(mounts, (list, tuple)):
        return ""
    # Der Index fuehrt Mount-Pfade absolut; die Wissensgruppen-Manifeste kennen
    # daneben die Form ohne fuehrenden Schraegstrich ("mnt/jarvis-kb/…").
    kandidaten = [p] if p.startswith("/") else [p, "/" + p]

    treffer = None
    for m in mounts:
        if not isinstance(m, dict):
            continue
        mp = str(m.get("mountpoint") or "").strip().rstrip("/")
        if not mp:
            continue
        for k in kandidaten:
            if k == mp:
                rest = ""
            elif k.startswith(mp + "/"):
                rest = k[len(mp) + 1:]
            else:
                continue
            if treffer is None or len(mp) > len(treffer[0]):
                treffer = (mp, rest, m)
            break
    if treffer is None:
        return ""

    _, rest, m = treffer
    typ = str(m.get("type") or "smb").strip().lower()
    quelle, fehler = pruefe(typ, str(m.get("source") or ""))
    if fehler or not quelle:
        return ""
    return _anhaengen(typ, quelle, rest)


def _anhaengen(typ: str, quelle: str, rest: str) -> str:
    """Unterpfad an die normalisierte Quelle haengen – in DEREN Schreibweise."""
    teile = [t for t in rest.split("/") if t]
    if typ == "smb":
        # //host/freigabe -> \\host\freigabe: das ist die Form, die Windows
        # oeffnet, und die einzige, die in einer Chat-Antwort ueberlebt
        # (`agent._clean_doc_refs` entfernt Pfade mit Schraegstrichen, wenn sie
        # auf eine Ergebnis-Endung enden – ein "//srv/x/Handbuch.pdf" waere aus
        # der Anzeige verschwunden).
        unc = "\\\\" + quelle[2:].replace("/", "\\")
        return "\\".join([unc] + teile) if teile else unc
    # NFS (host:/export) und WebDAV (https://host/pfad) tragen ihre Pfade mit
    # Schraegstrichen – die Quelle ist dort selbst schon so geschrieben.
    return "/".join([quelle.rstrip("/")] + teile) if teile else quelle


def serverpfad(mounts, netz: str) -> str:
    """Netzwerkpfad -> Serverpfad. "" = keiner Freigabe zuzuordnen.

    Die Umkehrung von ``netzpfad()``. Sie gibt es, weil der Benutzer die Quelle
    ANKLICKEN soll: die Chat-Antwort nennt den Netzwerkpfad, der Browser kann
    ihn aber nicht oeffnen (gemessen: ein ``file://``-Link auf einer
    https-Seite wird von Chrome verworfen – ohne Navigation und ohne eine
    einzige Konsolenzeile, der Klick tut sichtbar GAR NICHTS). Der Weg, der
    wirklich traegt, ist die Datei aus der Wissensdatenbank auszuliefern – und
    dafuer braucht der Endpunkt den Serverpfad zurueck.

    ⚠ HIER GILT FAIL-CLOSED, anders als in ``netzpfad()``: diese Funktion
    entscheidet, WELCHE DATEI ausgeliefert wird. Was sich keiner konfigurierten
    Freigabe zuordnen laesst, ergibt "" – und der Aufrufer antwortet 404. Sie
    ist ausserdem NICHT die Sicherheitsschranke: der Endpunkt prueft danach
    unveraendert, dass die aufgeloeste Datei in einem Wissensordner liegt.

    Verglichen wird der FREIGABE-Teil ohne Ruecksicht auf Gross/Kleinschreibung
    (Windows-Freigaben sind case-insensitiv, und der Benutzer bzw. das Modell
    tippt sie mal so, mal so); der Unterpfad behaelt seine Schreibweise
    UNVERAENDERT – das Dateisystem darunter ist case-sensitiv.
    """
    roh = str(netz or "").strip().strip('"').strip("'")
    if not roh or not isinstance(mounts, (list, tuple)):
        return ""
    if _VERBOTEN_RE.search(roh):
        return ""
    # UNC (\\host\share\…) auf die Slash-Form bringen – in der liegen die
    # normalisierten Quellen. NFS und WebDAV tragen sie schon.
    s = roh.replace("\\", "/") if roh.startswith("\\\\") else roh
    s = re.sub(r"^/{2,}", "//", s)

    treffer = None
    for m in mounts:
        if not isinstance(m, dict):
            continue
        mp = str(m.get("mountpoint") or "").strip().rstrip("/")
        if not mp:
            continue
        quelle, fehler = pruefe(str(m.get("type") or "smb"),
                                str(m.get("source") or ""))
        if fehler or not quelle:
            continue
        q = quelle.rstrip("/")
        if s.lower() == q.lower():
            rest = ""
        elif s.lower().startswith(q.lower() + "/"):
            rest = s[len(q) + 1:]
        else:
            continue
        if treffer is None or len(q) > len(treffer[0]):
            treffer = (q, rest, mp)
    if treffer is None:
        return ""

    _, rest, mp = treffer
    teile = [t for t in rest.split("/") if t]
    # Kein ".." und kein leeres Segment – der Endpunkt loest danach zwar noch
    # auf und prueft die Zugehoerigkeit, aber eine Traversal-Angabe gehoert
    # nicht erst dort abgefangen.
    if any(t == ".." or t == "." for t in teile):
        return ""
    return "/".join([mp] + teile) if teile else mp
