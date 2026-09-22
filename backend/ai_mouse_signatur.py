"""Code-Signatur fuer die AI-Maus-Anwendung (Authenticode, seit 2026-09-21).

⚠ WAS DAS LEISTET – UND WAS AUSDRUECKLICH NICHT.

Eine Signatur gibt der Anwendung einen **verifizierten Herausgebernamen**: der
Benutzer sieht in den Dateieigenschaften und in jedem Rechte-Dialog, von wem
sie stammt, und eine nachtraegliche Manipulation an der 66-MB-Datei faellt auf.
Erst damit sind ueberhaupt AppLocker-/WDAC-Regeln nach Herausgeber moeglich.

**Sie schaltet SmartScreen NICHT ab.** Das ist die wichtigste Zeile dieses
Moduls, weil die Erwartung anders herum verbreitet ist: Microsoft hat die
Sofort-Reputation fuer EV-Zertifikate 2024 entfernt, seither bauen OV, EV und
Microsofts eigener Signierdienst ihre Reputation gleichermassen ueber das
DOWNLOAD-VOLUMEN auf ("several weeks and hundreds of clean installs from a wide
audience"). Ein Werkzeug fuer ein paar Dutzend Arbeitsplaetze erreicht das nie.
Mit einem Zertifikat der FIRMEN-CA erst recht nicht – SmartScreen wertet allein
oeffentlich vertrauenswuerdige CAs.

Wer die Warnung bei der Erstinstallation wirklich loswerden will, nimmt den
anderen Weg, den Microsoft fuer genau diese Lage nennt: von einer
Intranet-Freigabe verteilen statt ueber den Browser laden
(``ai_mouse.freigabe_pfad()``). Beides zusammen ist der vollstaendige Ausbau,
und die beiden Haelften loesen VERSCHIEDENE Dinge.

──────────────────────────────────────────────────────────────────────────────
WO DIE GEHEIMNISSE LIEGEN

``data/.aimouse_sign.pfx``   das Zertifikat samt privatem Schluessel  (0600)
``data/.aimousesignkey``     der Fernet-Schluessel fuer das Kennwort  (0600)
``data/ai_mouse_signatur.json``  Metadaten + verschluesseltes Kennwort (0640)

⚠ DAS KENNWORT LIEGT AUSDRUECKLICH **NICHT** IN DER SKILL-KONFIGURATION, und
das ist kein Stilfrage: ``GET /api/skills`` haengt an ``require_auth`` und gibt
ueber ``list_skills()`` auch ``skill_info["config"]`` heraus – jeder angemeldete
Benutzer koennte es dort lesen. Eine eigene Ablage mit eigener Schluesseldatei
ist der Weg, den SAP, VEMAS und Jira im Haus schon gehen.

⚠ EIGENE SCHLUESSELDATEI, nicht die eines anderen Moduls: ein gemeinsamer
Schluessel verbaende zwei Bereiche, und ein Restore eines einzelnen machte den
anderen unlesbar.

Alle drei Dateien gehoeren in ``_APP_DENY_REL``, ``PRIVATE_FILES`` und
``SHELL_SECRET_PATHS`` – ohne das liest ein ``cat`` in der Sandbox den privaten
Schluessel, mit dem sich anschliessend beliebiger Code im Namen des Hauses
signieren laesst. Das ist das schwerste Geheimnis, das dieses Projekt ablegt.

──────────────────────────────────────────────────────────────────────────────
FAIL-OPEN, ABER LAUT (Entscheidung des Betreibers, 2026-09-21)

Scheitert das Signieren (Kennwort falsch, Zertifikat abgelaufen, osslsigncode
fehlt, Zeitstempel-Dienst nicht erreichbar), wird die Anwendung **unsigniert
ausgeliefert** und der Grund steht im Journal UND in der Oberflaeche. Eine
unsignierte Anwendung ist besser als gar keine – ein abgelaufenes Zertifikat
darf nicht die ganze Verteilung lahmlegen, auch nicht die stille
Aktualisierung. Was es NICHT sein darf, ist still: genau diese Fehlerklasse hat
hier schon mehrfach Tage gekostet.
"""

from __future__ import annotations

import json
import os
import re
import struct
import subprocess
import tempfile
import threading
import time
from pathlib import Path

# ── Orte ────────────────────────────────────────────────────────────────────
_DATA = Path(__file__).resolve().parent.parent / "data"

PFX_DATEI = _DATA / ".aimouse_sign.pfx"
SCHLUESSEL_DATEI = _DATA / ".aimousesignkey"
KONFIG_DATEI = _DATA / "ai_mouse_signatur.json"

SCHLUESSEL_MODUS = 0o600
PFX_MODUS = 0o600
KONFIG_MODUS = 0o640

# Ein PFX mit einem Zertifikat ist wenige Kilobyte gross. Der Deckel faengt
# eine versehentlich hochgeladene ISO ab, bevor sie im Speicher liegt.
MAX_PFX_BYTES = 256 * 1024

# ⚠ VORGABE IST EIN RFC-3161-ZEITSTEMPEL, UND ER IST KEIN BEIWERK: ohne ihn
# wird die Signatur ungueltig, sobald das Zertifikat ablaeuft – auch fuer
# Dateien, die laengst verteilt sind. Mit Zeitstempel bleibt sie gueltig, weil
# nachweisbar ist, dass zur Signierzeit alles gueltig war.
#
# Er braucht allerdings einen ausgehenden Netzweg. Gibt es den nicht, traegt
# der Administrator das Feld leer ein – dann wird ohne signiert, und der
# Zustand sagt es.
TSA_STANDARD = "http://timestamp.digicert.com"

# Die Signatur selbst; SHA-1 ist seit Jahren nicht mehr vertrauenswuerdig.
HASH_ALGO = "sha256"

# Ein Signierlauf haengt am Zeitstempel-Dienst. Ohne Deckel wartet der Bau
# unbegrenzt auf einen Server, der nicht antwortet.
ZEITDECKEL_S = 120

_sperre = threading.RLock()


class SignaturFehler(Exception):
    """Etwas an der Einrichtung stimmt nicht – mit Klartext fuer die Anzeige."""


# ── Eigentuemer ─────────────────────────────────────────────────────────────
def _eigentuemer_erhalten(pfad: Path) -> None:
    """Die Datei dem Dienstbenutzer lassen, auch wenn root sie geschrieben hat.

    ⚠ DAS IST KEINE KOSMETIK, ES IST DIE VORAUSSETZUNG DAFUER, DASS DAS FEATURE
    UEBERHAUPT FUNKTIONIERT – und es ist am 2026-09-22 auf DEV gemessen worden,
    nicht hergeleitet:

    ``deploy/ai_mouse_build.sh`` ruft ``signieren()``, und dieses Skript laeuft
    im Regelfall ALS ROOT (Bootstrap Schritt 6g, Broker-Op, Handaufruf). Nach
    einem Signat schreibt ``signieren()`` ``letzter_fehler``/``letzte_signatur``
    zurueck. Ohne diesen Helfer gehoert die Ablage danach root – und der Dienst
    (``User=jarvis``) kann sie **nicht mehr lesen**. Die Folge ist still und
    teuer: ``zertifikat_da()`` meldet False, die Oberflaeche sagt „kein
    Zertifikat", und der naechste Bau als Dienstbenutzer signiert nicht mehr.
    Im Journal stand woertlich::

        [AI-Maus/Signatur] …/ai_mouse_signatur.json ist nicht lesbar
        ([Errno 13] Permission denied) – Eigentuemer 0:0, Rechte 640

    Dieselbe Falle und dieselbe Loesung wie ``config._write_preserve_owner``
    (dort fuer den Root-Broker und ``settings.json``).

    Der Rueckfall auf das VERZEICHNIS ist der Unterschied zum Vorbild: jenes
    nimmt den Eigentuemer der vorhandenen Datei und laesst eine NEU angelegte
    bei root. Hier kann die erste Datei sehr wohl aus einem root-Lauf stammen.
    """
    try:
        if os.geteuid() != 0:
            return
    except AttributeError:      # Windows – dort gibt es die Frage nicht
        return
    try:
        st = pfad.stat() if pfad.exists() else None
        uid = st.st_uid if st else None
        gid = st.st_gid if st else None
        if uid in (None, 0):
            # Neu angelegt (oder schon root): den Eigentuemer des
            # Datenverzeichnisses uebernehmen – dem gehoert der Dienst.
            dst = _DATA.stat()
            uid, gid = dst.st_uid, dst.st_gid
        if uid and uid != 0:
            os.chown(pfad, uid, gid)
    except Exception:  # noqa: BLE001
        # Fail-safe: ein misslungenes chown darf den Bau nicht aufhalten. Der
        # Lesefehler danach wird von `_laden()` laut gemeldet.
        pass


# ── Verschluesselung ────────────────────────────────────────────────────────
def _fernet():
    """Der Fernet ueber ``SCHLUESSEL_DATEI`` – legt sie bei Bedarf an."""
    from cryptography.fernet import Fernet  # noqa: PLC0415

    if not SCHLUESSEL_DATEI.exists():
        _DATA.mkdir(parents=True, exist_ok=True)
        schluessel = Fernet.generate_key()
        # ⚠ ERST MIT 0600 ANLEGEN, DANN SCHREIBEN. Zwischen open() und einem
        # nachtraeglichen chmod laege der Schluessel sonst kurz mit der
        # Vorgabe-Maske da – dieselbe Reihenfolge wie in `vemas_accounts`.
        fd = os.open(str(SCHLUESSEL_DATEI),
                     os.O_WRONLY | os.O_CREAT | os.O_TRUNC, SCHLUESSEL_MODUS)
        with os.fdopen(fd, "wb") as f:
            f.write(schluessel)
        os.chmod(SCHLUESSEL_DATEI, SCHLUESSEL_MODUS)
        _eigentuemer_erhalten(SCHLUESSEL_DATEI)
    return Fernet(SCHLUESSEL_DATEI.read_bytes().strip())


def _verschluesseln(klartext: str) -> str:
    return _fernet().encrypt((klartext or "").encode("utf-8")).decode("ascii")


def _entschluesseln(gespeichert: str) -> str:
    """Klartext – oder ``""``, wenn der Wert unlesbar ist.

    Unlesbar heisst in der Regel: die Schluesseldatei wurde ersetzt (Restore
    eines einzelnen Bereichs). Dann ist das Kennwort weg und muss neu gesetzt
    werden; ein Wurf waere hier die schlechtere Auskunft, weil der Zustand
    trotzdem angezeigt werden soll.
    """
    if not gespeichert:
        return ""
    try:
        return _fernet().decrypt(gespeichert.encode("ascii")).decode("utf-8")
    except Exception:  # noqa: BLE001
        return ""


# ── Ablage ──────────────────────────────────────────────────────────────────
def _laden() -> dict:
    """Die Metadaten – bei jedem Problem ein leeres dict.

    ⚠ FAIL-OPEN, ABER NICHT STILL: eine unlesbare Ablage darf den Bau nicht
    aufhalten, aber der Grund gehoert ins Journal. Genau dieser Fall (Datei als
    root geschrieben, fuer den Dienst nicht lesbar) hat am 2026-09-21 in der
    Confluence-Einbindung eine leere Liste vorgetaeuscht.
    """
    try:
        if not KONFIG_DATEI.is_file():
            return {}
        d = json.loads(KONFIG_DATEI.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception as e:  # noqa: BLE001
        try:
            st = KONFIG_DATEI.stat()
            print("[AI-Maus/Signatur] %s ist nicht lesbar (%s) – Eigentuemer "
                  "%d:%d, Rechte %o" % (KONFIG_DATEI, e, st.st_uid, st.st_gid,
                                        st.st_mode & 0o777), flush=True)
        except OSError:
            print("[AI-Maus/Signatur] %s ist nicht lesbar: %s"
                  % (KONFIG_DATEI, e), flush=True)
        return {}


def _speichern(d: dict) -> None:
    """Atomar und mit 0640 – die Datei traegt das verschluesselte Kennwort."""
    _DATA.mkdir(parents=True, exist_ok=True)
    tmp = KONFIG_DATEI.with_suffix(".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, KONFIG_MODUS)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.chmod(tmp, KONFIG_MODUS)
    os.replace(tmp, KONFIG_DATEI)
    os.chmod(KONFIG_DATEI, KONFIG_MODUS)
    _eigentuemer_erhalten(KONFIG_DATEI)


# ── Zertifikat ──────────────────────────────────────────────────────────────
def _pkcs12_lesen(daten: bytes, kennwort: str) -> dict:
    """Betreff, Aussteller und Laufzeit – wirft bei falschem Kennwort.

    ⚠ HIER WIRD GEPRUEFT, BEVOR ETWAS GESPEICHERT WIRD. Ein falsches Kennwort
    faellt damit beim Hochladen auf und nicht erst beim naechsten Bau – und ein
    bereits hinterlegtes, funktionierendes Zertifikat wird nicht durch eine
    Fehleingabe ersetzt (Register: „eine Fehleingabe darf keine laufende
    Konfiguration zerstoeren").
    """
    from cryptography.hazmat.primitives.serialization import pkcs12  # noqa: PLC0415

    try:
        pw = kennwort.encode("utf-8") if kennwort else None
        schluessel, zert, _kette = pkcs12.load_key_and_certificates(daten, pw)
    except Exception as e:  # noqa: BLE001
        raise SignaturFehler(
            "Die Datei liess sich nicht oeffnen. Entweder ist das Kennwort "
            "falsch, oder es ist keine PKCS#12-Datei (.pfx/.p12). "
            "Meldung: %s" % e) from None

    if zert is None:
        raise SignaturFehler("In der Datei ist kein Zertifikat enthalten.")
    if schluessel is None:
        raise SignaturFehler(
            "In der Datei ist kein privater Schluessel enthalten – mit einem "
            "reinen Zertifikat laesst sich nicht signieren. Beim Export aus "
            "der Zertifikatsverwaltung „Privaten Schluessel exportieren\" "
            "waehlen.")

    def _name(x) -> str:
        try:
            # Der gebraeuchliche Name ist das, was ein Mensch wiedererkennt.
            from cryptography.x509.oid import NameOID  # noqa: PLC0415
            teile = x.get_attributes_for_oid(NameOID.COMMON_NAME)
            if teile:
                return str(teile[0].value)
            return x.rfc4514_string()
        except Exception:  # noqa: BLE001
            return ""

    # `not_valid_after_utc` gibt es erst ab cryptography 42; der Rueckfall
    # haelt aeltere Installationen am Leben.
    def _ende(z):
        for attr in ("not_valid_after_utc", "not_valid_after"):
            wert = getattr(z, attr, None)
            if wert is not None:
                return wert
        return None

    ende = _ende(zert)
    return {
        "betreff": _name(zert.subject),
        "aussteller": _name(zert.issuer),
        "gueltig_bis": ende.strftime("%Y-%m-%d") if ende else "",
        "ablauf_ts": ende.timestamp() if ende else 0.0,
    }


def zertifikat_setzen(daten: bytes, kennwort: str, tsa: str = "") -> dict:
    """Zertifikat ablegen. Wirft ``SignaturFehler``, ohne etwas zu aendern.

    Rueckgabe ist der neue Zustand (ohne Geheimnisse).
    """
    if not daten:
        raise SignaturFehler("Es wurde keine Datei uebergeben.")
    if len(daten) > MAX_PFX_BYTES:
        raise SignaturFehler(
            "Die Datei ist mit %d KB zu gross fuer ein Zertifikat "
            "(Grenze %d KB). Ist es wirklich eine .pfx/.p12?"
            % (len(daten) // 1024, MAX_PFX_BYTES // 1024))

    # ⚠ ERST PRUEFEN, DANN SCHREIBEN – siehe `_pkcs12_lesen`.
    meta = _pkcs12_lesen(daten, kennwort)

    with _sperre:
        _DATA.mkdir(parents=True, exist_ok=True)
        # Wieder: erst mit 0600 anlegen, dann schreiben.
        tmp = PFX_DATEI.with_suffix(".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, PFX_MODUS)
        with os.fdopen(fd, "wb") as f:
            f.write(daten)
        os.chmod(tmp, PFX_MODUS)
        os.replace(tmp, PFX_DATEI)
        os.chmod(PFX_DATEI, PFX_MODUS)
        _eigentuemer_erhalten(PFX_DATEI)

        d = _laden()
        d.update(meta)
        d["pw_enc"] = _verschluesseln(kennwort)
        d["tsa"] = _tsa_normieren(tsa if tsa is not None else d.get("tsa", ""))
        d["gesetzt_am"] = time.time()
        # Ein frisch hinterlegtes Zertifikat hat noch nichts signiert – ein
        # stehengebliebener Fehler von vorher waere eine Falschaussage.
        d["letzter_fehler"] = ""
        _speichern(d)
    return zustand()


def zertifikat_entfernen() -> dict:
    """Zertifikat und Kennwort loeschen. Die Anwendung bleibt, wie sie ist.

    ⚠ DIE BEREITS GEBAUTE EXE WIRD NICHT ENTSIGNIERT. Das waere ein Eingriff
    in eine ausgelieferte Datei ohne Gegenwert; beim naechsten Bau entsteht
    ohnehin eine unsignierte. Der Zustand sagt das.
    """
    with _sperre:
        try:
            PFX_DATEI.unlink()
        except FileNotFoundError:
            pass
        d = _laden()
        for k in ("pw_enc", "betreff", "aussteller", "gueltig_bis",
                  "ablauf_ts", "gesetzt_am", "letzter_fehler"):
            d.pop(k, None)
        _speichern(d)
    return zustand()


def tsa_setzen(tsa: str) -> dict:
    """Nur den Zeitstempel-Dienst aendern – ohne das Zertifikat anzufassen."""
    with _sperre:
        d = _laden()
        d["tsa"] = _tsa_normieren(tsa)
        _speichern(d)
    return zustand()


_TSA_RE = re.compile(r"^https?://[^\s<>\"']+$", re.IGNORECASE)


def _tsa_normieren(roh: str) -> str:
    """Getrimmt und geprueft – ``""`` heisst ausdruecklich „ohne Zeitstempel".

    Eine unbrauchbare Adresse wird ABGEWIESEN und nicht stillschweigend
    verworfen: sonst traegt der Administrator etwas ein, sieht es verschwinden
    und haelt das Feld fuer kaputt.
    """
    wert = (roh or "").strip()
    if not wert:
        return ""
    if not _TSA_RE.match(wert) or len(wert) > 300:
        raise SignaturFehler(
            "Der Zeitstempel-Dienst muss eine http(s)-Adresse sein, z.B. %s – "
            "oder leer bleiben (dann wird ohne Zeitstempel signiert)."
            % TSA_STANDARD)
    return wert


def zertifikat_da() -> bool:
    """Liegt ein Zertifikat bereit? Fehlertolerant, im Zweifel ``False``."""
    try:
        return PFX_DATEI.is_file() and PFX_DATEI.stat().st_size > 0
    except OSError:
        return False


# ── Ist die Anwendung signiert? ─────────────────────────────────────────────
#
# ⚠ GEMESSEN AM PE-HEADER, NICHT AN DER AUSGABE EINES FREMDWERKZEUGS. Die
# Zusage lautet „die Datei, die hier ausgeliefert wird, traegt eine Signatur" –
# und das steht in der Datei selbst (Data Directory 4, "Certificate Table").
# `osslsigncode verify` waere die naheliegende Wahl und die schlechtere: es
# meldet bei einem Zertifikat der FIRMEN-CA einen Fehlschlag, weil es deren
# Wurzel nicht kennt – auf diesem Server ist das der Normalfall, und wir
# wuerden eine korrekt signierte Datei als unsigniert melden.
_DD_SICHERHEIT = 4          # Index der Certificate Table im Data Directory
_PE32 = 0x10B
_PE32_PLUS = 0x20B


def ist_signiert(pfad) -> bool:
    """Traegt die PE-Datei eine Authenticode-Signatur? Im Zweifel ``False``.

    Jeder Fehler ergibt ``False`` – „unbekannt" wird hier bewusst wie
    „unsigniert" behandelt: die Anzeige darf keine Signatur behaupten, die sie
    nicht nachgewiesen hat.
    """
    try:
        with open(pfad, "rb") as f:
            kopf = f.read(1024)
            if kopf[:2] != b"MZ" or len(kopf) < 0x40:
                return False
            lf = struct.unpack_from("<I", kopf, 0x3C)[0]
            if lf < 0 or lf + 24 > len(kopf) or kopf[lf:lf + 4] != b"PE\0\0":
                return False
            opt_gr, = struct.unpack_from("<H", kopf, lf + 20)
            opt = lf + 24
            if opt_gr < 2 or opt + opt_gr > len(kopf):
                return False
            magic, = struct.unpack_from("<H", kopf, opt)
            # Die Data Directories beginnen im Optional Header bei 96 (PE32)
            # bzw. 112 (PE32+); davor liegen die zusaetzlichen 64-Bit-Felder.
            if magic == _PE32_PLUS:
                dd = opt + 112
            elif magic == _PE32:
                dd = opt + 96
            else:
                return False
            eintrag = dd + _DD_SICHERHEIT * 8
            if eintrag + 8 > opt + opt_gr or eintrag + 8 > len(kopf):
                return False
            versatz, groesse = struct.unpack_from("<II", kopf, eintrag)
            # Beide muessen gesetzt sein: ein Eintrag mit Groesse 0 ist der
            # Normalzustand einer unsignierten Datei.
            return bool(versatz and groesse)
    except (OSError, struct.error, ValueError):
        return False


# ── Werkzeug ────────────────────────────────────────────────────────────────
WERKZEUG = "osslsigncode"


def werkzeug_da() -> bool:
    """Ist ``osslsigncode`` installiert?"""
    import shutil  # noqa: PLC0415

    return bool(shutil.which(WERKZEUG))


def werkzeug_hinweis() -> str:
    """Was fehlt und wie es dazukommt – oder ``""``, wenn alles da ist."""
    if werkzeug_da():
        return ""
    return ("Zum Signieren fehlt das Programm „%s\". Es wird beim Einschalten "
            "des Skills mitinstalliert; laeuft der Skill bereits, genuegt der "
            "⤓-Knopf in der Skill-Liste (Einstellungen → Skills). Von Hand: "
            "apt-get install -y %s" % (WERKZEUG, WERKZEUG))


# ── Signieren ───────────────────────────────────────────────────────────────
def signieren(exe: Path) -> tuple[bool, str]:
    """Die Datei an Ort und Stelle signieren. ``(erfolg, grund)``.

    ``(True, "")``          signiert.
    ``(False, "")``         es ist kein Zertifikat hinterlegt – kein Fehler.
    ``(False, "<grund>")``  hinterlegt, aber es ging nicht. Der Aufrufer
                            liefert die Datei trotzdem aus und meldet den
                            Grund (Entscheidung des Betreibers, siehe Modulkopf).

    ⚠ DAS KENNWORT GEHT UEBER EINE DATEI, NIE ALS ARGUMENT. Argumente stehen in
    der Prozessliste und damit fuer jeden Benutzer des Servers sichtbar –
    dieselbe Regel, die im Projekt fuer ``sudo -S`` gilt. ``osslsigncode``
    bietet dafuer ``-readpass``.
    """
    exe = Path(exe)
    if not zertifikat_da():
        return (False, "")

    # ⚠ DAS ZERTIFIKAT WIRD VOR DEM WERKZEUG GEPRUEFT, und das ist eine
    # Entscheidung: ein abgelaufenes Zertifikat ist ein Zustand, den nur der
    # Administrator aendern kann, und er besteht unabhaengig davon, ob
    # `osslsigncode` gerade installiert ist. Andersherum muesste er erst das
    # Programm nachinstallieren, um ueberhaupt zu ERFAHREN, dass sein
    # Zertifikat seit Wochen abgelaufen ist – eine Meldung, die den
    # dringenderen Befund verdeckt.
    d = _laden()
    kennwort = _entschluesseln(d.get("pw_enc", ""))
    ablauf = float(d.get("ablauf_ts") or 0.0)
    if ablauf and ablauf < time.time():
        return (False, "Das hinterlegte Zertifikat ist am %s abgelaufen."
                % (d.get("gueltig_bis") or "?"))

    if not werkzeug_da():
        return (False, werkzeug_hinweis())
    if not exe.is_file():
        return (False, "Die zu signierende Datei fehlt: %s" % exe)

    tsa = str(d.get("tsa") or "")
    # ⚠ ZWEI ANLAEUFE, UND DAS IST EINE ABWAEGUNG: ein Zeitstempel-Dienst ist
    # ein FREMDER Server und faellt aus. Ohne Zeitstempel zu signieren ist
    # schlechter (die Signatur laeuft mit dem Zertifikat ab), aber deutlich
    # besser als gar nicht – und der Zustand sagt es ausdruecklich, damit
    # niemand eine Haltbarkeit annimmt, die es nicht gibt.
    versuche = [tsa, ""] if tsa else [""]
    letzter = ""
    for ts in versuche:
        ok, grund = _signieren_einmal(exe, kennwort, ts)
        if ok:
            ohne = " (OHNE Zeitstempel – die Signatur wird ungueltig, sobald "
            hinweis = ""
            if tsa and not ts:
                hinweis = (ohne + "das Zertifikat am %s ablaeuft. Grund: %s)"
                           % (d.get("gueltig_bis") or "?", letzter))
            with _sperre:
                akt = _laden()
                akt["letzter_fehler"] = hinweis
                akt["letzte_signatur"] = time.time()
                akt["ohne_zeitstempel"] = bool(tsa and not ts)
                _speichern(akt)
            return (True, hinweis)
        letzter = grund

    with _sperre:
        akt = _laden()
        akt["letzter_fehler"] = letzter
        _speichern(akt)
    return (False, letzter)


def _signieren_einmal(exe: Path, kennwort: str, tsa: str) -> tuple[bool, str]:
    """Ein Aufruf von ``osslsigncode``. ``(erfolg, grund)``."""
    from backend import ai_mouse  # noqa: PLC0415

    ziel = exe.with_suffix(exe.suffix + ".signiert")
    pw_datei = None
    try:
        # Das Kennwort in eine Datei mit 0600, die sofort wieder verschwindet.
        fd, pw_name = tempfile.mkstemp(prefix=".aimouse-pw-", dir=str(_DATA))
        pw_datei = Path(pw_name)
        os.fchmod(fd, 0o600)
        # Auch hier: ein harter Abbruch laesst sie liegen, und als root waere
        # sie fuer den Dienst nicht einmal loeschbar.
        _eigentuemer_erhalten(pw_datei)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(kennwort or "")

        marke, _akzent = ai_mouse.branding()
        befehl = [
            WERKZEUG, "sign",
            "-pkcs12", str(PFX_DATEI),
            "-readpass", str(pw_datei),
            "-h", HASH_ALGO,
            "-n", marke or "Jarvis",
            "-in", str(exe),
            "-out", str(ziel),
        ]
        if tsa:
            # `-ts` ist RFC 3161; `-t` waere der alte Authenticode-Weg.
            befehl += ["-ts", tsa]

        r = subprocess.run(befehl, capture_output=True, text=True,
                           timeout=ZEITDECKEL_S)
        if r.returncode != 0:
            grund = (r.stderr or r.stdout or "").strip()[-400:] or "unbekannt"
            return (False, "osslsigncode: %s" % grund)

        # ⚠ MASSGEBLICH IST DIE DATEI, NICHT DER RUECKGABEWERT – dieselbe Regel
        # wie bei tika_setup und beim Bau selbst. Ein „Erfolg", der nichts
        # hergestellt hat, ist eine Zusage, die der naechste Abruf kassiert.
        if not ziel.is_file() or not ist_signiert(ziel):
            return (False, "osslsigncode meldete Erfolg, aber die erzeugte "
                           "Datei traegt keine Signatur.")

        # Rechte der Vorlage uebernehmen und erst dann einwechseln: ein
        # abgebrochenes Kopieren darf keine halbe EXE hinterlassen.
        try:
            os.chmod(ziel, exe.stat().st_mode & 0o777)
        except OSError:
            pass
        os.replace(ziel, exe)
        return (True, "")
    except subprocess.TimeoutExpired:
        return (False, "Das Signieren hat laenger als %d s gedauert "
                       "(Zeitstempel-Dienst nicht erreichbar?)." % ZEITDECKEL_S)
    except Exception as e:  # noqa: BLE001
        return (False, str(e))
    finally:
        for p in (pw_datei, ziel):
            try:
                if p is not None:
                    Path(p).unlink()
            except OSError:
                pass


# ── Zustand ─────────────────────────────────────────────────────────────────
def zustand() -> dict:
    """Alles, was die Oberflaeche braucht – **nie** Zertifikat oder Kennwort.

    ⚠ ES GIBT KEINEN WEG, DAS ZERTIFIKAT ODER DAS KENNWORT WIEDER
    HERAUSZULESEN. Das ist Absicht und unterscheidet diesen Bereich bewusst von
    `secret_reveal`: ein privater Signierschluessel ist kein Zugangsdatum, das
    ein Benutzer „nachsehen" muss – wer ihn braucht, hat ihn.
    """
    from backend import ai_mouse  # noqa: PLC0415

    d = _laden()
    da = zertifikat_da()
    try:
        exe = ai_mouse.exe_pfad()
        exe_signiert = ist_signiert(exe) if exe.is_file() else False
    except Exception:  # noqa: BLE001
        exe_signiert = False

    ablauf = float(d.get("ablauf_ts") or 0.0)
    return {
        "zertifikat": da,
        "betreff": d.get("betreff", "") if da else "",
        "aussteller": d.get("aussteller", "") if da else "",
        "gueltig_bis": d.get("gueltig_bis", "") if da else "",
        "abgelaufen": bool(da and ablauf and ablauf < time.time()),
        "tsa": d.get("tsa", "") if d.get("tsa") is not None else "",
        "tsa_standard": TSA_STANDARD,
        "exe_signiert": exe_signiert,
        "ohne_zeitstempel": bool(d.get("ohne_zeitstempel")) if exe_signiert else False,
        "letzter_fehler": str(d.get("letzter_fehler") or ""),
        "werkzeug_da": werkzeug_da(),
        "werkzeug_hinweis": werkzeug_hinweis(),
    }


def zustand_kurz() -> dict:
    """Die knappe Fassung fuer ``/api/ai-mouse/health`` (jeder Seitenaufbau).

    Bewusst ohne Betreff und Aussteller: das ist eine Angabe ueber die
    Hauskonfiguration, die niemand braucht, der nur die Anwendung holen will.
    """
    d = _laden()
    try:
        from backend import ai_mouse  # noqa: PLC0415
        exe = ai_mouse.exe_pfad()
        sig = ist_signiert(exe) if exe.is_file() else False
    except Exception:  # noqa: BLE001
        sig = False
    return {
        "zertifikat": zertifikat_da(),
        "exe_signiert": sig,
        "letzter_fehler": str(d.get("letzter_fehler") or ""),
    }


def _reset_fuer_tests() -> None:
    """Nur fuer Waechter: Zustand aus dem Speicher werfen."""
    # Das Modul haelt keinen Cache; die Funktion existiert, damit ein Test
    # dieselbe Form benutzen kann wie bei den Nachbarmodulen.
    return None
