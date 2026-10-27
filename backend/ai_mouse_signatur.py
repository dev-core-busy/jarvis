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

──────────────────────────────────────────────────────────────────────────────
ZWEITER WEG: AZURE KEY VAULT (seit 2026-10-27)

Das Haus signiert seine Artefakte mit einem Zertifikat im Azure Key Vault; der
private Schluessel verlaesst den Vault NIE. Signiert wird mit ``jsign`` (Java,
Apache-2.0) – das Windows-Werkzeug ``AzureSignTool`` aus der Hausanleitung
laeuft auf diesem Server nicht, jsign spricht dieselbe Key-Vault-Schnittstelle
(``GET /certificates/<name>``, ``POST <kid>/sign``) unter Linux.

* Zugang: Verzeichnis-ID (Tenant), Anwendungs-ID (Client), Client-Secret,
  Vault und Zertifikatsname. ALLE Werte sind Konfiguration, keiner steht im
  Code (das Repo ist oeffentlich). Das Secret liegt verschluesselt in
  ``KONFIG_DATEI`` wie das PFX-Kennwort, es gibt keinen Weg, es auszulesen.
* Anmeldeadresse (Vorgabe ``AZURE_ANMELDUNG``) und Bezugsquelle von jsign
  (Vorgabe Maven Central) sind ebenfalls einstellbar. Fest bleiben nur die
  Sicherheitsgrenze des Vaults (``.vault.azure.net``) und Protokollwerte
  (Scope, API-Version, jsign-Fassung samt Pruefsummen).
* Das Secret geht nur an die eingestellte Anmeldeadresse, das
  daraus geholte Zugriffstoken nur an einen Vault unter ``.vault.azure.net``
  und an jsign ueber die UMGEBUNG (``env:``), nie als Argument.
* ⚠ DER VAULT LAESST NUR FREIGEGEBENE ABSENDER-ADRESSEN ZU (Netzwerkregel der
  Cloud-IT). Ein Server ausserhalb dieser Liste bekommt 403
  „ForbiddenByFirewall" – die Meldung sagt das ausdruecklich, sonst sucht man
  den Fehler beim Secret.
* Erst pruefen, dann speichern: ``keyvault_setzen`` holt ein Token, liest das
  Zertifikat UND laesst den Vault einmal probehalber signieren (Pruefung gegen
  den oeffentlichen Schluessel). Damit faellt eine fehlende Signier-Berechtigung
  beim Einrichten auf und nicht beim naechsten Bau.
* Das Werkzeug (``vendor/jsign.jar``) wird bei Bedarf von Maven Central
  geladen und VOR JEDEM AUFRUF gegen die hier gepinnte SHA-256 geprueft – die
  Datei bekommt ein Zugriffstoken fuer den Signierschluessel des Hauses.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
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

# ── Azure Key Vault (zweiter Weg) ───────────────────────────────────────────
VERFAHREN_PFX = "pfx"
VERFAHREN_KV = "keyvault"

JSIGN_JAR = Path(__file__).resolve().parent.parent / "vendor" / "jsign.jar"
# ⚠ GEPRUEFT WIRD DER INHALT: die SHA-1 veroeffentlicht Maven Central (nur die,
# .sha256 gibt es dort nicht – nachgesehen), die SHA-256 ist die Fassung, gegen
# die gemessen wurde. Gleiches Verfahren wie deploy/tika_setup.sh.
JSIGN_VERSION = "7.6"
JSIGN_SHA1 = "843c90ab50bc0da16fc1aac9e2c6bba986dc4a36"
JSIGN_SHA256 = "6cf58aa080e7ff82656f320cff8d4a3bff30408df8766806dcba3740dd839fa5"
JSIGN_URL = ("https://repo1.maven.org/maven2/net/jsign/jsign/%s/jsign-%s.jar"
             % (JSIGN_VERSION, JSIGN_VERSION))
MAX_JAR_BYTES = 16 * 1024 * 1024

AZURE_ANMELDUNG = "https://login.microsoftonline.com"
AZURE_SCOPE = "https://vault.azure.net/.default"
KV_API = "7.4"
# Name der Umgebungsvariable, ueber die jsign das Token bekommt (``env:``).
KV_TOKEN_VAR = "JARVIS_KV_TOKEN"
NETZ_ZEITDECKEL_S = 30

_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                      r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
# Vault-Namen: 3–24 Zeichen, Buchstaben/Ziffern/Bindestrich (Azure-Regel).
_VAULT_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]{1,22}[A-Za-z0-9]$")
_KV_ZERT_RE = re.compile(r"^[A-Za-z0-9-]{1,127}$")

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

    # BSI M5: verpackt mit dem Hauptschluessel ausserhalb von data/
    # (backend/geheimnis_tresor.py); legt die Datei bei Bedarf an (0600 vor
    # dem Schreiben) und verpackt einen Altbestand. Ein root-Lauf liest den
    # Hauptschluessel direkt aus /etc/jarvis – derselbe Schluessel wie im Dienst.
    from backend import geheimnis_tresor as _tresor  # noqa: PLC0415
    neu_angelegt = not SCHLUESSEL_DATEI.exists()
    roh = _tresor.modul_schluessel(SCHLUESSEL_DATEI, SCHLUESSEL_MODUS)
    if neu_angelegt:
        _eigentuemer_erhalten(SCHLUESSEL_DATEI)
    return Fernet(roh)


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
        # ⚠ ERST DEN GANZEN NEUEN ZUSTAND BAUEN, DANN DAS PFX EINSETZEN
        # (Review 2026-09-28 #13). Bisher stand `os.replace` VOR
        # `_tsa_normieren`/`_verschluesseln`: eine vertippte TSA-Adresse warf
        # erst, als das neue PFX schon lag – mit altem Kennwort und alten
        # Metadaten daneben, und jeder spaetere Bau scheiterte.
        d = _laden()
        d.update(meta)
        d["pw_enc"] = _verschluesseln(kennwort)
        d["tsa"] = _tsa_normieren(tsa if tsa is not None else d.get("tsa", ""))
        d["gesetzt_am"] = time.time()
        # Ein frisch hinterlegtes Zertifikat hat noch nichts signiert – ein
        # stehengebliebener Fehler von vorher waere eine Falschaussage.
        d["letzter_fehler"] = ""
        # Wer ein Zertifikat hochlaedt, will damit signieren – auch wenn
        # daneben ein Key-Vault-Zugang hinterlegt ist.
        d["verfahren"] = VERFAHREN_PFX

        _DATA.mkdir(parents=True, exist_ok=True)
        # Das bisherige PFX merken: scheitert das Speichern der Konfiguration
        # NACH dem Einsetzen, kommt es zurueck – PFX und Kennwort gehoeren
        # zusammen, ein halber Wechsel ist schlechter als keiner.
        try:
            alt = PFX_DATEI.read_bytes()
        except FileNotFoundError:
            alt = None
        # Wieder: erst mit 0600 anlegen, dann schreiben.
        tmp = PFX_DATEI.with_suffix(".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, PFX_MODUS)
        with os.fdopen(fd, "wb") as f:
            f.write(daten)
        os.chmod(tmp, PFX_MODUS)
        os.replace(tmp, PFX_DATEI)
        try:
            os.chmod(PFX_DATEI, PFX_MODUS)
            _eigentuemer_erhalten(PFX_DATEI)
            _speichern(d)
        except BaseException:
            _pfx_zurueck(alt)
            raise
    return zustand()


def _pfx_zurueck(alt: bytes | None) -> None:
    """Das vorherige PFX wiederherstellen (oder entfernen, wenn es keines gab)."""
    try:
        if alt is None:
            PFX_DATEI.unlink(missing_ok=True)
            return
        tmp = PFX_DATEI.with_suffix(".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, PFX_MODUS)
        with os.fdopen(fd, "wb") as f:
            f.write(alt)
        os.chmod(tmp, PFX_MODUS)
        os.replace(tmp, PFX_DATEI)
        _eigentuemer_erhalten(PFX_DATEI)
    except Exception:  # noqa: BLE001
        pass


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
        # Bleibt der Key Vault, signiert ab jetzt er – sonst niemand.
        d["verfahren"] = VERFAHREN_KV if _kv_konfiguriert(d) else VERFAHREN_PFX
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


# ── Azure Key Vault ─────────────────────────────────────────────────────────
def _kv(d: dict) -> dict:
    """Der Key-Vault-Teil der Ablage (immer ein dict)."""
    kv = d.get("kv")
    return kv if isinstance(kv, dict) else {}


def _kv_konfiguriert(d: dict) -> bool:
    kv = _kv(d)
    return all(kv.get(k) for k in ("vault", "tenant", "client", "secret_enc", "zertifikat"))


def _weg(d: dict) -> str:
    """Welcher Weg signiert? Key Vault nur, wenn ausgewaehlt UND vollstaendig.
    EINE Stelle fuer die Frage – Zustand und Signieren lesen beide hier."""
    if d.get("verfahren") == VERFAHREN_KV and _kv_konfiguriert(d):
        return VERFAHREN_KV
    return VERFAHREN_PFX


def verfahren() -> str:
    return _weg(_laden())


def eingerichtet() -> bool:
    """Ist der GERADE GELTENDE Weg eingerichtet (es wird also signiert)?"""
    if verfahren() == VERFAHREN_KV:
        return True
    return zertifikat_da()


def _vault_normieren(roh: str) -> str:
    """Vault als ``https://<name>.vault.azure.net`` – oder ``SignaturFehler``.

    ⚠ NUR DIESE FORM, und das ist eine Sicherheitsgrenze: an die Vault-Adresse
    geht das Zugriffstoken fuer den Signierschluessel des Hauses. Eine frei
    waehlbare Adresse waere ein Weg, es abzugreifen (Register: der
    Ersatzwert, der an eine beliebige Adresse geht).
    """
    wert = (roh or "").strip().rstrip("/")
    name = ""
    if _VAULT_NAME_RE.match(wert):
        name = wert
    else:
        m = re.match(r"^https://([A-Za-z0-9-]+)\.vault\.azure\.net$", wert, re.IGNORECASE)
        if m and _VAULT_NAME_RE.match(m.group(1)):
            name = m.group(1)
    if not name:
        raise SignaturFehler(
            "Der Key Vault muss als Name (z.B. meinvault) oder als Adresse "
            "https://<name>.vault.azure.net angegeben werden.")
    return "https://%s.vault.azure.net" % name.lower()


def _guid_pruefen(wert: str, was: str) -> str:
    w = (wert or "").strip()
    if not _GUID_RE.match(w):
        raise SignaturFehler("%s muss eine GUID sein (8-4-4-4-12 Hex-Zeichen)." % was)
    return w.lower()


def _json_anfrage(url: str, *, daten: bytes | None = None, kopf: dict | None = None,
                  methode: str = "GET") -> tuple[int, dict]:
    """``(status, json)`` – Netzfehler werden zu ``SignaturFehler`` mit Grund."""
    req = urllib.request.Request(url, data=daten, method=methode, headers=kopf or {})
    try:
        with urllib.request.urlopen(req, timeout=NETZ_ZEITDECKEL_S) as r:
            roh = r.read(1024 * 1024)
            status = r.status
    except urllib.error.HTTPError as e:
        roh = e.read(1024 * 1024) if e.fp else b""
        status = e.code
    except Exception as e:  # noqa: BLE001
        host = urllib.parse.urlsplit(url).netloc
        raise SignaturFehler("%s ist nicht erreichbar: %s" % (host, e)) from None
    try:
        obj = json.loads(roh.decode("utf-8") or "{}")
    except Exception:  # noqa: BLE001
        obj = {}
    return status, obj if isinstance(obj, dict) else {}


def _anmeldung_normieren(roh: str) -> str:
    """Anmeldeadresse – ``""`` heisst die Vorgabe ``AZURE_ANMELDUNG``.

    Nur ``https://<host>[:port]`` ohne Pfad: an diese Adresse geht das
    Client-Secret im Klartext des Formulars."""
    wert = (roh or "").strip().rstrip("/")
    if not wert:
        return ""
    if not re.match(r"^https://[A-Za-z0-9.-]+(?::\d{1,5})?$", wert) or len(wert) > 200:
        raise SignaturFehler(
            "Die Anmeldeadresse muss eine https-Adresse ohne Pfad sein, z.B. "
            "%s – oder leer bleiben (dann gilt diese Vorgabe)." % AZURE_ANMELDUNG)
    return wert.lower()


def _jsign_quelle_normieren(roh: str) -> str:
    """Bezugsquelle fuer jsign – ``""`` heisst Maven Central (``JSIGN_URL``).

    http ist hier zugelassen (interner Spiegel): die Datei wird ohnehin nur
    mit der gepinnten SHA-1 UND SHA-256 verwendet."""
    wert = (roh or "").strip()
    if not wert:
        return ""
    if not re.match(r"^https?://[^\s<>\"']+$", wert, re.IGNORECASE) or len(wert) > 400:
        raise SignaturFehler("Die Bezugsquelle fuer jsign muss eine http(s)-Adresse "
                             "der .jar-Datei sein – oder leer bleiben (Maven Central).")
    return wert


def _kv_token(tenant: str, client: str, secret: str, anmeldung: str = "") -> str:
    """Zugriffstoken fuer den Vault (OAuth2 Client Credentials)."""
    url = "%s/%s/oauth2/v2.0/token" % (anmeldung or AZURE_ANMELDUNG,
                                        urllib.parse.quote(tenant))
    daten = urllib.parse.urlencode({
        "grant_type": "client_credentials", "client_id": client,
        "client_secret": secret, "scope": AZURE_SCOPE}).encode("ascii")
    status, obj = _json_anfrage(url, daten=daten, methode="POST", kopf={
        "Content-Type": "application/x-www-form-urlencoded"})
    token = str(obj.get("access_token") or "")
    if status == 200 and token:
        return token
    beschr = str(obj.get("error_description") or obj.get("error") or "HTTP %d" % status)
    # Die haeufigen Faelle in Worten – der AADSTS-Code allein sagt dem
    # Administrator nicht, welches Feld falsch ist.
    if "AADSTS7000215" in beschr or "AADSTS7000222" in beschr:
        grund = "Das Client-Secret ist falsch oder abgelaufen."
    elif "AADSTS700016" in beschr:
        grund = "Die Anwendungs-ID (Client) ist in diesem Verzeichnis unbekannt."
    elif "AADSTS90002" in beschr or "AADSTS900023" in beschr:
        grund = "Die Verzeichnis-ID (Tenant) ist unbekannt."
    else:
        grund = "Anmeldung bei Microsoft abgelehnt."
    raise SignaturFehler("%s (%s)" % (grund, beschr.splitlines()[0][:200]))


def _kv_fehler(status: int, obj: dict, was: str) -> SignaturFehler:
    """Antwort des Vaults als Klartext – der Netzwerk-Fall ausdruecklich."""
    err = obj.get("error") if isinstance(obj.get("error"), dict) else {}
    code = str(err.get("code") or "")
    inner = err.get("innererror") if isinstance(err.get("innererror"), dict) else {}
    icode = str(inner.get("code") or "")
    msg = str(err.get("message") or "HTTP %d" % status)[:240]
    if icode == "ForbiddenByFirewall" or "firewall" in msg.lower() \
            or "Client address is not authorized" in msg:
        return SignaturFehler(
            "Der Key Vault laesst diesen Server nicht zu: seine ausgehende "
            "Adresse steht nicht in der Netzwerk-Freigabe des Vaults. Die "
            "Freigabe pflegt die Cloud-IT. (%s)" % msg)
    if status in (401, 403):
        return SignaturFehler(
            "Der Vault verweigert %s – dem Dienstkonto fehlt die Berechtigung "
            "(%s: %s)." % (was, code or status, msg))
    if status == 404:
        return SignaturFehler("%s: im Vault nicht gefunden (%s)." % (was, msg))
    return SignaturFehler("Der Vault antwortet bei %s mit %s: %s" % (was, code or status, msg))


def _kv_zertifikat(vault: str, name: str, token: str):
    """``(zertifikat_x509, kid)`` des aktuellen Zertifikats im Vault."""
    from cryptography import x509  # noqa: PLC0415

    status, obj = _json_anfrage(
        "%s/certificates/%s?api-version=%s" % (vault, urllib.parse.quote(name), KV_API),
        kopf={"Authorization": "Bearer " + token})
    if status != 200:
        raise _kv_fehler(status, obj, "das Zertifikat „%s\"" % name)
    try:
        zert = x509.load_der_x509_certificate(base64.b64decode(obj.get("cer") or ""))
    except Exception as e:  # noqa: BLE001
        raise SignaturFehler("Der Vault lieferte kein lesbares Zertifikat: %s" % e) from None
    return zert, str(obj.get("kid") or "")


def _kv_probesignatur(vault: str, kid: str, zert, token: str) -> None:
    """Den Vault einmal signieren lassen und das Ergebnis PRUEFEN.

    ⚠ ERST HIER FAELLT EINE FEHLENDE SIGNIER-BERECHTIGUNG AUF: Zertifikat
    lesen darf ein Konto auch ohne ``sign`` – ohne diese Probe saehe die
    Einrichtung gruen aus und der naechste Bau scheiterte.
    """
    from cryptography.hazmat.primitives import hashes  # noqa: PLC0415
    from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa, utils  # noqa: PLC0415

    # ⚠ DER SCHLUESSEL MUSS IM SELBEN VAULT LIEGEN: an die kid-Adresse geht
    #   das Token. Eine Antwort, die woandershin zeigt, bekommt es nicht.
    # Hostnamen sind gross/klein-unabhaengig, der Pfad danach nicht.
    if not kid.lower().startswith(vault.lower() + "/keys/"):
        raise SignaturFehler("Der Vault nannte keinen Schluessel zum Zertifikat "
                             "in diesem Vault (kid: %s)." % kid[:120])
    oeff = zert.public_key()
    if isinstance(oeff, rsa.RSAPublicKey):
        alg = "RS256"
    elif isinstance(oeff, ec.EllipticCurvePublicKey):
        alg = "ES256"
    else:
        raise SignaturFehler("Unbekannter Schluesseltyp im Zertifikat.")
    digest = hashlib.sha256(b"jarvis-ai-maus-probesignatur").digest()
    status, obj = _json_anfrage(
        "%s/sign?api-version=%s" % (kid, KV_API), methode="POST",
        daten=json.dumps({"alg": alg, "value": base64.urlsafe_b64encode(digest)
                          .decode("ascii").rstrip("=")}).encode("utf-8"),
        kopf={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    if status != 200:
        raise _kv_fehler(status, obj, "das Signieren")
    try:
        sig = base64.urlsafe_b64decode(str(obj.get("value") or "") + "==")
        if alg == "RS256":
            oeff.verify(sig, digest, padding.PKCS1v15(), utils.Prehashed(hashes.SHA256()))
        else:
            # Key Vault liefert ECDSA als r||s, cryptography erwartet DER.
            n = len(sig) // 2
            der = utils.encode_dss_signature(int.from_bytes(sig[:n], "big"),
                                             int.from_bytes(sig[n:], "big"))
            oeff.verify(der, digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    except Exception:  # noqa: BLE001
        raise SignaturFehler(
            "Die Probesignatur des Vaults passt nicht zum Zertifikat – "
            "Schluessel und Zertifikat gehoeren nicht zusammen.") from None


def _x509_meta(zert) -> dict:
    """Betreff, Aussteller, Laufzeit – dieselbe Form wie beim PFX."""
    from cryptography.x509.oid import NameOID  # noqa: PLC0415

    def _name(x) -> str:
        try:
            teile = x.get_attributes_for_oid(NameOID.COMMON_NAME)
            return str(teile[0].value) if teile else x.rfc4514_string()
        except Exception:  # noqa: BLE001
            return ""
    ende = getattr(zert, "not_valid_after_utc", None) or getattr(zert, "not_valid_after", None)
    return {
        "betreff": _name(zert.subject),
        "aussteller": _name(zert.issuer),
        "gueltig_bis": ende.strftime("%Y-%m-%d") if ende else "",
        "ablauf_ts": ende.timestamp() if ende else 0.0,
    }


def keyvault_setzen(vault: str, tenant: str, client: str, secret: str,
                    zertifikat: str, tsa: str | None = None,
                    anmeldung: str = "", jsign_quelle: str = "") -> dict:
    """Key-Vault-Zugang hinterlegen. Wirft ``SignaturFehler``, ohne etwas zu aendern.

    ``secret`` leer = das gespeicherte behalten – aber NUR, solange Vault,
    Tenant, Client UND Anmeldeadresse dieselben bleiben. Sonst ginge ein
    gespeichertes Secret an ein Ziel, fuer das es nie eingegeben wurde.
    """
    a = _anmeldung_normieren(anmeldung)
    q = _jsign_quelle_normieren(jsign_quelle)
    v = _vault_normieren(vault)
    t = _guid_pruefen(tenant, "Die Verzeichnis-ID (Tenant)")
    c = _guid_pruefen(client, "Die Anwendungs-ID (Client)")
    z = (zertifikat or "").strip()
    if not _KV_ZERT_RE.match(z):
        raise SignaturFehler("Der Zertifikatsname darf nur Buchstaben, Ziffern "
                             "und Bindestriche enthalten.")
    alt = _kv(_laden())
    geheim = (secret or "").strip()
    if not geheim:
        if (alt.get("vault"), alt.get("tenant"), alt.get("client"),
                alt.get("anmeldung", "")) != (v, t, c, a):
            raise SignaturFehler(
                "Bitte das Client-Secret eingeben – Vault, Tenant, Client oder "
                "Anmeldeadresse haben sich geaendert, das gespeicherte gilt nur "
                "fuer den bisherigen Zugang.")
        geheim = _entschluesseln(alt.get("secret_enc", ""))
        if not geheim:
            raise SignaturFehler("Das gespeicherte Client-Secret ist nicht "
                                 "lesbar – bitte neu eingeben.")
    tsa_neu = _tsa_normieren(tsa) if tsa is not None else None

    # ⚠ ERST PRUEFEN, DANN SCHREIBEN – auch die Signier-Berechtigung.
    token = _kv_token(t, c, geheim, a)
    zert, kid = _kv_zertifikat(v, z, token)
    _kv_probesignatur(v, kid, zert, token)
    meta = _x509_meta(zert)

    with _sperre:
        d = _laden()
        d["kv"] = {"vault": v, "tenant": t, "client": c, "zertifikat": z,
                   "anmeldung": a, "jsign_quelle": q,
                   "secret_enc": _verschluesseln(geheim), "gesetzt_am": time.time(),
                   "geprueft_am": time.time(), **meta}
        if tsa_neu is not None:
            d["tsa"] = tsa_neu
        d["verfahren"] = VERFAHREN_KV
        d["letzter_fehler"] = ""
        _speichern(d)
    # Das Werkzeug gleich mitholen – der Hinweis im Zustand verspricht es.
    # Ein Fehlschlag kippt die Einrichtung nicht: der Zustand nennt ihn, und
    # das Signieren versucht es erneut.
    jsign_bereitstellen()
    return zustand()


def verfahren_setzen(weg: str) -> dict:
    """Den geltenden Weg umstellen – nur auf einen, der eingerichtet ist.

    Ohne diese Schranke stuende „Key Vault" in der Anzeige, waehrend
    mangels Zugang weiter das PFX (oder gar nichts) signiert."""
    with _sperre:
        d = _laden()
        if weg == VERFAHREN_KV:
            if not _kv_konfiguriert(d):
                raise SignaturFehler("Es ist kein Key-Vault-Zugang hinterlegt.")
        elif weg == VERFAHREN_PFX:
            if not zertifikat_da():
                raise SignaturFehler("Es ist keine Zertifikatsdatei hinterlegt.")
        else:
            raise SignaturFehler("Unbekannter Signierweg.")
        if d.get("verfahren") != weg:
            d["verfahren"] = weg
            _speichern(d)
    return zustand()


def keyvault_entfernen() -> dict:
    """Key-Vault-Zugang loeschen; liegt ein PFX bereit, signiert ab jetzt das."""
    with _sperre:
        d = _laden()
        d.pop("kv", None)
        d["verfahren"] = VERFAHREN_PFX
        d["letzter_fehler"] = ""
        _speichern(d)
    return zustand()


# ── jsign bereitstellen ─────────────────────────────────────────────────────
def _sha(pfad: Path, algo: str) -> str:
    h = hashlib.new(algo)
    with open(pfad, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def jsign_gueltig() -> bool:
    """Liegt GENAU die gepinnte jsign-Fassung bereit? (Inhalt, nicht Name)"""
    try:
        return JSIGN_JAR.is_file() and _sha(JSIGN_JAR, "sha256") == JSIGN_SHA256
    except OSError:
        return False


def _jsign_url() -> str:
    """Die eingestellte Bezugsquelle – sonst Maven Central."""
    return str(_kv(_laden()).get("jsign_quelle") or "") or JSIGN_URL


def jsign_bereitstellen() -> str:
    """jsign von Maven Central laden und pruefen. ``""`` = bereit, sonst Grund.

    ⚠ AUTOMATIK STATT HINWEIS (Register): der Server laedt das Werkzeug
    selbst, sobald der Key Vault es braucht. Geschrieben wird erst nach
    bestandener Pruefung beider Pruefsummen.
    """
    if jsign_gueltig():
        return ""
    quelle = _jsign_url()
    try:
        JSIGN_JAR.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".jsign-", dir=str(JSIGN_JAR.parent))
        tmp_p = Path(tmp)
        try:
            with urllib.request.urlopen(quelle, timeout=NETZ_ZEITDECKEL_S * 4) as r, \
                    os.fdopen(fd, "wb") as f:
                gelesen = 0
                for block in iter(lambda: r.read(256 * 1024), b""):
                    gelesen += len(block)
                    if gelesen > MAX_JAR_BYTES:
                        return "jsign: die geladene Datei ist unerwartet gross."
                    f.write(block)
            if _sha(tmp_p, "sha1") != JSIGN_SHA1 or _sha(tmp_p, "sha256") != JSIGN_SHA256:
                return ("jsign: die geladene Datei hat nicht die erwartete "
                        "Pruefsumme – nicht verwendet.")
            os.chmod(tmp_p, 0o644)
            os.replace(tmp_p, JSIGN_JAR)
            _eigentuemer_erhalten(JSIGN_JAR)
            return ""
        finally:
            try:
                tmp_p.unlink()
            except OSError:
                pass
    except Exception as e:  # noqa: BLE001
        return "jsign liess sich nicht laden (%s): %s" % (quelle, e)


def _java() -> str:
    return shutil.which("java") or ""


def kv_werkzeug_hinweis() -> str:
    """Was dem Key-Vault-Weg fehlt – oder ``""``."""
    if not _java():
        return ("Zum Signieren ueber den Key Vault fehlt Java. Von Hand: "
                "apt-get install -y default-jre-headless")
    if not jsign_gueltig():
        return ("Das Signierprogramm jsign %s ist noch nicht geladen – das "
                "geschieht beim Speichern des Zugangs bzw. beim naechsten "
                "Signieren automatisch." % JSIGN_VERSION)
    return ""


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
    if verfahren() == VERFAHREN_KV:
        return _signieren_kv(exe)
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

    return _versuchen(lambda ts: _signieren_einmal(exe, kennwort, ts),
                      str(d.get("tsa") or ""), d.get("gueltig_bis") or "?")


def _versuchen(einmal, tsa: str, gueltig_bis: str) -> tuple[bool, str]:
    """Mit Zeitstempel, notfalls ohne – fuer BEIDE Wege dieselbe Regel."""
    # ⚠ ZWEI ANLAEUFE, UND DAS IST EINE ABWAEGUNG: ein Zeitstempel-Dienst ist
    # ein FREMDER Server und faellt aus. Ohne Zeitstempel zu signieren ist
    # schlechter (die Signatur laeuft mit dem Zertifikat ab), aber deutlich
    # besser als gar nicht – und der Zustand sagt es ausdruecklich, damit
    # niemand eine Haltbarkeit annimmt, die es nicht gibt.
    versuche = [tsa, ""] if tsa else [""]
    letzter = ""
    for ts in versuche:
        ok, grund = einmal(ts)
        if ok:
            ohne = " (OHNE Zeitstempel – die Signatur wird ungueltig, sobald "
            hinweis = ""
            if tsa and not ts:
                hinweis = (ohne + "das Zertifikat am %s ablaeuft. Grund: %s)"
                           % (gueltig_bis, letzter))
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


def _kv_fehlschlag(grund: str) -> tuple[bool, str]:
    with _sperre:
        akt = _laden()
        akt["letzter_fehler"] = grund
        _speichern(akt)
    return (False, grund)


def _signieren_kv(exe: Path) -> tuple[bool, str]:
    """Signieren ueber den Key Vault. Gleiche Zusagen wie der PFX-Weg:
    fail-open, aber laut; Ablauf vor fehlendem Werkzeug."""
    d = _laden()
    kv = _kv(d)
    secret = _entschluesseln(kv.get("secret_enc", ""))
    if not secret:
        return _kv_fehlschlag("Das gespeicherte Client-Secret ist nicht lesbar "
                              "– bitte den Key-Vault-Zugang neu speichern.")
    # ⚠ ZERTIFIKAT JEDES MAL NEU LESEN: der Vault erneuert es (neue Version
    #   unter demselben Namen). Ein gemerktes Ablaufdatum wuerde nach der
    #   Erneuerung das Signieren dauerhaft sperren.
    try:
        token = _kv_token(kv["tenant"], kv["client"], secret, kv.get("anmeldung", ""))
        zert, _kid = _kv_zertifikat(kv["vault"], kv["zertifikat"], token)
    except SignaturFehler as f:
        return _kv_fehlschlag(str(f))
    meta = _x509_meta(zert)
    with _sperre:
        akt = _laden()
        if isinstance(akt.get("kv"), dict):
            akt["kv"].update(meta)
            akt["kv"]["geprueft_am"] = time.time()
            _speichern(akt)
    if meta["ablauf_ts"] and meta["ablauf_ts"] < time.time():
        return _kv_fehlschlag("Das Zertifikat im Key Vault ist am %s abgelaufen."
                              % (meta["gueltig_bis"] or "?"))
    if not _java():
        return _kv_fehlschlag(kv_werkzeug_hinweis())
    grund = jsign_bereitstellen()
    if grund:
        return _kv_fehlschlag(grund)
    if not exe.is_file():
        return _kv_fehlschlag("Die zu signierende Datei fehlt: %s" % exe)
    return _versuchen(lambda ts: _signieren_kv_einmal(exe, kv, token, ts),
                      str(d.get("tsa") or ""), meta["gueltig_bis"] or "?")


def _jsign_befehl(kv: dict, ziel: Path, tsa: str) -> list[str]:
    """Der jsign-Aufruf – das Token steht NICHT darin (``env:``)."""
    from backend import ai_mouse  # noqa: PLC0415

    marke, _akzent = ai_mouse.branding()
    befehl = [
        _java() or "java", "-jar", str(JSIGN_JAR),
        "--storetype", "AZUREKEYVAULT",
        "--keystore", kv["vault"],
        "--storepass", "env:" + KV_TOKEN_VAR,
        "--alias", kv["zertifikat"],
        "--alg", "SHA-256",
        "--name", marke or "Jarvis",
        # Eine bereits vorhandene Signatur (Nachsignieren nach dem Speichern)
        # wird ersetzt, nicht verschachtelt.
        "--replace",
    ]
    info = info_url(ai_mouse.einkompilierte_basis())
    if info:
        befehl += ["--url", info]
    if tsa:
        befehl += ["--tsaurl", tsa, "--tsmode", "RFC3161"]
    return befehl + [str(ziel)]


def _java_grund(text: str) -> str:
    """Die Fehlermeldung aus einer Java-Ausgabe – OHNE den Stacktrace.

    ⚠ DAS ENDE DER AUSGABE IST DIE SCHLECHTESTE WAHL (Register, Tika): dort
    stehen ``at …JsignCLI.main(…)`` und der Hilfehinweis, die eigentliche
    Ausnahme steht oben. Gemessen am 2026-10-27: der Rest der letzten 400
    Zeichen war reiner Stacktrace."""
    zeilen = []
    for z in (text or "").splitlines():
        t = z.strip()
        if not t or t.startswith("at ") or t.startswith("...") \
                or t.startswith("Try `java") or t.startswith("Try 'java"):
            continue
        zeilen.append(t)
    return " | ".join(zeilen)[:400] or "unbekannt"


def _signieren_kv_einmal(exe: Path, kv: dict, token: str, tsa: str) -> tuple[bool, str]:
    """Ein Aufruf von jsign auf einer KOPIE. ``(erfolg, grund)``."""
    ziel = exe.with_suffix(exe.suffix + ".signiert")
    try:
        # ⚠ JEDES MAL DEN INHALT PRUEFEN: die Datei bekommt gleich ein Token
        #   fuer den Signierschluessel des Hauses.
        if not jsign_gueltig():
            return (False, "jsign hat nicht die erwartete Pruefsumme – nicht verwendet.")
        # jsign signiert an Ort und Stelle; die Vorlage bleibt bis zum Erfolg
        # unberuehrt.
        shutil.copyfile(exe, ziel)
        umgebung = dict(os.environ)
        umgebung[KV_TOKEN_VAR] = token
        r = subprocess.run(_jsign_befehl(kv, ziel, tsa), capture_output=True,
                           text=True, timeout=ZEITDECKEL_S, env=umgebung)
        if r.returncode != 0:
            g = _java_grund(r.stderr or r.stdout or "")
            return (False, g if g.startswith("jsign") else "jsign: " + g)
        if not ist_signiert(ziel):
            return (False, "jsign meldete Erfolg, aber die erzeugte Datei "
                           "traegt keine Signatur.")
        try:
            os.chmod(ziel, exe.stat().st_mode & 0o777)
        except OSError:
            pass
        os.replace(ziel, exe)
        return (True, "")
    except subprocess.TimeoutExpired:
        return (False, "Das Signieren hat laenger als %d s gedauert "
                       "(Key Vault oder Zeitstempel-Dienst nicht erreichbar?)." % ZEITDECKEL_S)
    except Exception as e:  # noqa: BLE001
        return (False, str(e))
    finally:
        try:
            ziel.unlink()
        except OSError:
            pass


def info_url(basis: str) -> str:
    """Die Info-Adresse der Signatur (``-i``): die Anleitungsseite der AI-Maus.

    ``basis`` ist die in die Anwendung einkompilierte Serveradresse – damit
    zeigt der Link genau auf den Server, mit dem die EXE ohnehin spricht, und
    es entsteht keine zweite Einstellung, die auseinanderlaufen kann.

    ⚠ NUR https, sonst ``""`` (dann wird ohne ``-i`` signiert): die Adresse
    steht unveraenderlich in der signierten Datei, und die Anwendung selbst
    nimmt ebenfalls nur https an (``EndpointResolver.Basis``). Ein Link auf
    http waere eine Einladung, ihn im Klartext umzulenken.
    """
    b = str(basis or "").strip().rstrip("/")
    if not re.match(r"^https://[^\s/\"'<>]+(?:/[^\s\"'<>]*)?$", b):
        return ""
    return b + "/ai-mouse"


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
        info = info_url(ai_mouse.einkompilierte_basis())
        if info:
            # Erscheint in Windows als Link im Signaturdialog
            # (SpcSpOpusInfo.moreInfo).
            befehl += ["-i", info]
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
    kv = _kv(d)
    kv_da = _kv_konfiguriert(d)
    kv_ablauf = float(kv.get("ablauf_ts") or 0.0)
    weg = _weg(d)
    if weg == VERFAHREN_KV:
        # Die Zertifikatszeile und das Werkzeug gelten fuer den GELTENDEN Weg –
        # sonst stuende „kein Zertifikat" ueber einer signierten Anwendung.
        aktiv = {"betreff": kv.get("betreff", ""), "aussteller": kv.get("aussteller", ""),
                 "gueltig_bis": kv.get("gueltig_bis", ""),
                 "abgelaufen": bool(kv_ablauf and kv_ablauf < time.time())}
        hinweis = kv_werkzeug_hinweis()
        wz_da = not hinweis
    else:
        aktiv = {"betreff": d.get("betreff", "") if da else "",
                 "aussteller": d.get("aussteller", "") if da else "",
                 "gueltig_bis": d.get("gueltig_bis", "") if da else "",
                 "abgelaufen": bool(da and ablauf and ablauf < time.time())}
        hinweis = werkzeug_hinweis()
        wz_da = werkzeug_da()
    return {
        "verfahren": weg,
        "eingerichtet": kv_da if weg == VERFAHREN_KV else da,
        "zertifikat": da,
        **aktiv,
        # ⚠ NIE das Secret – nur, OB eines gespeichert ist.
        "keyvault": {
            "eingerichtet": kv_da,
            "vault": kv.get("vault", ""), "tenant": kv.get("tenant", ""),
            "client": kv.get("client", ""), "zertifikat": kv.get("zertifikat", ""),
            "secret_gesetzt": bool(kv.get("secret_enc")),
            # Leer = Vorgabe; die Vorgabe geht mit, damit die Oberflaeche sie
            # als Platzhalter zeigen kann (eine Quelle, kein Abtippen im JS).
            "anmeldung": kv.get("anmeldung", ""), "anmeldung_standard": AZURE_ANMELDUNG,
            "jsign_quelle": kv.get("jsign_quelle", ""), "jsign_quelle_standard": JSIGN_URL,
        },
        "tsa": d.get("tsa", "") if d.get("tsa") is not None else "",
        "tsa_standard": TSA_STANDARD,
        "exe_signiert": exe_signiert,
        "ohne_zeitstempel": bool(d.get("ohne_zeitstempel")) if exe_signiert else False,
        "letzter_fehler": str(d.get("letzter_fehler") or ""),
        "werkzeug_da": wz_da,
        "werkzeug_hinweis": hinweis,
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
        # „wird signiert?" – ueber BEIDE Wege, nicht nur die PFX-Datei.
        "zertifikat": eingerichtet(),
        "exe_signiert": sig,
        "letzter_fehler": str(d.get("letzter_fehler") or ""),
    }


def _reset_fuer_tests() -> None:
    """Nur fuer Waechter: Zustand aus dem Speicher werfen."""
    # Das Modul haelt keinen Cache; die Funktion existiert, damit ein Test
    # dieselbe Form benutzen kann wie bei den Nachbarmodulen.
    return None
