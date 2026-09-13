"""Kennwoerter der Netzwerk-Freigaben verschluesselt ablegen (2026-09-13).

⚠ WARUM ES DAS GIBT: die Zugangsdaten der SMB-/NFS-Freigaben standen bis
2026-09-13 im KLARTEXT in ``data/settings.json`` – Benutzername und Kennwort,
lesbar in einer Datei, die auch Profile, Schalter und Skill-Konfiguration
traegt. Fuer SAP, VEMAS, Jira und die Postfaecher gibt es diese
Verschluesselung seit Langem; die Freigaben waren der Ausreisser.

WAS DAS AENDERT UND WAS NICHT: die Datei ist 0640 und steht in
``_APP_DENY_REL`` – ein Shell-Befehl in der Sandbox kam schon vorher nicht
heran. Der Gewinn liegt woanders: in einer Sicherung, einem Restore, einem
Support-Export oder einem versehentlich weitergereichten Konfigurations-Auszug
steht das Kennwort jetzt nicht mehr lesbar. **Wer Lesezugriff auf den Server
hat, kommt weiterhin an beides** – Schluessel und Ablage liegen
naturgemaess auf derselben Maschine. Das ist eine Verschluesselung im
Ruhezustand, kein Schutz gegen einen Angreifer mit Dateizugriff.

⚠ EIGENE SCHLUESSELDATEI (``data/.mountkey``), NICHT die des SAP-Moduls.
Ein gemeinsamer Schluessel verbaende zwei Bereiche, und ein Restore eines
einzelnen machte den anderen unlesbar – dieselbe Begruendung, aus der
``.sapkey``, ``.vemaskey`` und ``.jirakey`` getrennt sind.

FELDNAME: ``password_enc``. Das alte ``password`` bleibt als Feld erhalten,
solange ein Altbestand es traegt – ``kennwort_aus()`` liest beide, und
``migriere()`` zieht es beim naechsten Start um. Ein Klartext-RUECKFALL beim
SCHREIBEN gibt es ausdruecklich nicht.
"""
import logging
import os
from pathlib import Path

_log = logging.getLogger("jarvis.mount_credentials")

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
SCHLUESSEL_DATEI = DATA_DIR / ".mountkey"
SCHLUESSEL_MODUS = 0o600

# Feldnamen: verschluesselt und (Altbestand) Klartext.
FELD_ENC = "password_enc"
FELD_ALT = "password"


class MountKennwortFehler(Exception):
    """Kennwort nicht les-/schreibbar. Traegt eine Meldung mit Abhilfe."""


def _fernet():
    """Fernet-Instanz mit dem lokalen Schluessel; legt ihn beim ersten Mal an."""
    try:
        from cryptography.fernet import Fernet  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        raise MountKennwortFehler(
            "Das Paket 'cryptography' fehlt – Freigabe-Kennwoerter koennen "
            "nicht verschluesselt gespeichert werden. Ein Klartext-Rueckfall "
            "ist ausdruecklich nicht vorgesehen.") from e
    try:
        if SCHLUESSEL_DATEI.exists():
            roh = SCHLUESSEL_DATEI.read_bytes().strip()
            if roh:
                return Fernet(roh)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        neu = Fernet.generate_key()
        # Erst mit 0600 anlegen, DANN schreiben: zwischen open() und chmod()
        # laege der Schluessel sonst kurz mit 0644 auf der Platte.
        fd = os.open(str(SCHLUESSEL_DATEI), os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                     SCHLUESSEL_MODUS)
        with os.fdopen(fd, "wb") as f:
            f.write(neu)
        os.chmod(SCHLUESSEL_DATEI, SCHLUESSEL_MODUS)
        return Fernet(neu)
    except MountKennwortFehler:
        raise
    except Exception as e:  # noqa: BLE001
        raise MountKennwortFehler("Schluesseldatei nicht nutzbar (%s): %s"
                                  % (SCHLUESSEL_DATEI, e)) from e


def verschluesseln(klartext: str) -> str:
    if not klartext:
        return ""
    return _fernet().encrypt(str(klartext).encode("utf-8")).decode("ascii")


def entschluesseln(gespeichert: str) -> str:
    """Kennwort zurueckholen. Bei ungueltigem Wert: sprechender Fehler.

    Haeufigster Fall ist eine verlorene oder ersetzte Schluesseldatei (Restore
    ohne ``.mountkey``). "InvalidToken" sagt niemandem etwas – die Meldung
    nennt deshalb die Abhilfe.
    """
    if not gespeichert:
        return ""
    try:
        return _fernet().decrypt(str(gespeichert).encode("ascii")).decode("utf-8")
    except MountKennwortFehler:
        raise
    except Exception as e:  # noqa: BLE001
        raise MountKennwortFehler(
            "Das gespeicherte Freigabe-Kennwort laesst sich nicht "
            "entschluesseln – vermutlich wurde die Schluesseldatei "
            "data/.mountkey ersetzt oder sie fehlt. Bitte das Kennwort unter "
            "Einstellungen → Wissen → Netzwerk-Freigaben neu eintragen. (%s)"
            % type(e).__name__) from e


def kennwort_aus(mount: dict) -> str:
    """Klartext-Kennwort eines Freigabe-Eintrags – egal wie es abgelegt ist.

    ⚠ DER VERSCHLUESSELTE WERT HAT VORRANG. Traegt ein Eintrag (nach einer
    halben Migration, einem Restore, einer handgeschriebenen settings.json)
    BEIDE Felder, ist der verschluesselte der gepflegte: `speichern()`
    entfernt das Klartext-Feld, ein verbliebenes ist also der aeltere Stand.
    Umgekehrt herum liefe man Gefahr, ein altes Kennwort zu benutzen und den
    Mount scheitern zu lassen, obwohl das richtige daneben liegt.
    """
    if not isinstance(mount, dict):
        return ""
    enc = str(mount.get(FELD_ENC) or "").strip()
    if enc:
        return entschluesseln(enc)
    return str(mount.get(FELD_ALT) or "")


def setze_kennwort(mount: dict, klartext: str) -> dict:
    """Kennwort verschluesselt in den Eintrag legen und den Klartext entfernen.

    Ein LEERER Klartext loescht das Kennwort – "leer = unveraendert" ist die
    Entscheidung des AUFRUFERS (der Endpunkt), nicht dieser Funktion: sie
    waere hier eine stille Sonderregel, und ein Kennwort loeschen zu koennen
    muss moeglich bleiben.
    """
    if not isinstance(mount, dict):
        return mount
    mount.pop(FELD_ALT, None)
    if klartext:
        mount[FELD_ENC] = verschluesseln(klartext)
    else:
        mount.pop(FELD_ENC, None)
    return mount


def uebernehme_kennwort(neu: dict, alt: dict) -> dict:
    """Kennwort aus dem BESTEHENDEN Eintrag in den neuen uebernehmen.

    Fuer den Fall "leer = unveraendert" beim Bearbeiten. Uebernommen wird der
    gespeicherte Wert unveraendert – NICHT entschluesselt und neu
    verschluesselt: das braeuchte den Schluessel fuer einen Vorgang, der ihn
    gar nicht noetig hat, und liefe bei einer unlesbaren Schluesseldatei in
    einen Fehler, obwohl nichts am Kennwort geaendert werden soll.
    """
    if not isinstance(neu, dict) or not isinstance(alt, dict):
        return neu
    enc = str(alt.get(FELD_ENC) or "").strip()
    if enc:
        neu[FELD_ENC] = enc
        neu.pop(FELD_ALT, None)
    elif str(alt.get(FELD_ALT) or ""):
        # Altbestand im Klartext: bei dieser Gelegenheit verschluesseln.
        try:
            neu[FELD_ENC] = verschluesseln(str(alt[FELD_ALT]))
            neu.pop(FELD_ALT, None)
        except Exception:  # noqa: BLE001 – lieber unveraendert als verloren
            neu[FELD_ALT] = alt[FELD_ALT]
    return neu


def hat_kennwort(mount: dict) -> bool:
    """Ist ueberhaupt eines hinterlegt? Ohne es zu entschluesseln."""
    if not isinstance(mount, dict):
        return False
    return bool(str(mount.get(FELD_ENC) or "").strip()
                or str(mount.get(FELD_ALT) or "").strip())


def migriere(mounts) -> int:
    """Klartext-Kennwoerter im Bestand verschluesseln. Gibt die Anzahl zurueck.

    Arbeitet AUF DER LISTE (in-place) und ueberlaesst das Speichern dem
    Aufrufer – nur der weiss, wohin die Skill-Konfiguration gehoert, und nur
    er kann entscheiden, ob ein Schreibvorgang gerade zulaessig ist.

    ⚠ FAIL-SAFE: schlaegt die Verschluesselung eines Eintrags fehl (fehlendes
    `cryptography`, nicht schreibbare Schluesseldatei), bleibt dieser Eintrag
    UNVERAENDERT im Klartext stehen. Ihn zu leeren waere ein Datenverlust, der
    die Freigabe unbrauchbar macht – die harmlosere Halbfehlerstellung ist,
    dass das Kennwort noch eine Weile lesbar bleibt und die naechste Runde es
    erneut versucht.
    """
    if not isinstance(mounts, list):
        return 0
    n = 0
    for m in mounts:
        if not isinstance(m, dict):
            continue
        klar = str(m.get(FELD_ALT) or "")
        if not klar:
            # Kein Klartext da: ein leeres Altfeld darf trotzdem weg.
            if FELD_ALT in m:
                m.pop(FELD_ALT, None)
                n += 1
            continue
        try:
            m[FELD_ENC] = verschluesseln(klar)
            m.pop(FELD_ALT, None)
            n += 1
        except Exception as e:  # noqa: BLE001
            _log.warning("Freigabe-Kennwort konnte nicht verschluesselt werden "
                         "(bleibt vorerst im Klartext): %s", e)
    return n
