"""Lizenzierung – Pruefseite in Jarvis.

Der Gegenpart (Ausstellen, Widerrufen, Veroeffentlichen) liegt im Werkzeug
`license-manager/`, das ABSICHTLICH nicht im Repo ist. Hier steht nur, was ein
Kundensystem koennen muss: ein Token pruefen, die eigene Hardware erkennen und
taeglich den Widerrufsstand von GitHub holen.

Format (v1)
-----------
Token (das, was der Kunde eintraegt) – vier Teile, Punkt-getrennt:

    JARVIS-LIC-1.<b64u(nutzdaten)>.<b64u(signatur)>.<b64u(zertifikat)>

`nutzdaten` traegt Firma/Abteilung/Mail/Art/Laufzeit und die Lizenz-UUID (v5,
aus `firma|abteilung|mail|nr`). Signiert wird mit dem Ausgabe-Schluessel; dass
DIESER echt ist, beweist das mitgelieferte Zertifikat, das wiederum vom
Root-Schluessel signiert ist. Jarvis kennt nur den Root-Public-Key
(`backend/license_root.pub`) – der Ausgabe-Schluessel ist damit rotierbar,
ohne jede Installation anzufassen.

Statusdatei (taeglich von GitHub geholt, oeffentlich lesbar):

    {"v":1,"stand":"<ISO>","eintraege":{"<lid>":{...}},"zert":{...},"sig":"..."}

`lid` ist SHA256 der Lizenz-UUID – **kein Klartext**. In der Datei stehen weder
Firma noch Mail; ein Aussenstehender sieht eine anonyme Statusliste. Die Datei
ist als Ganzes signiert, sonst genuegte ein Fork plus manipulierte Namens-
aufloesung, um jede Lizenz auf ENTERPRISE zu heben.

Die Regeln, die man kennen muss
-------------------------------
* **Ohne Bindung gilt FREE.** Eine frisch ausgestellte Lizenz traegt in der
  Statusdatei `hwid: null`. Jarvis bindet sich beim ersten Start zwar selbst
  (lokal), massgeblich ist aber der Eintrag im Statusdienst – erst wenn dort
  die Hardware-Kennung steht, gilt die gekaufte Stufe. Ohne diese Regel liesse
  sich derselbe Schluessel auf beliebig vielen Maschinen aktivieren, denn ein
  Rueckkanal existiert nicht (die Kundensysteme haben kein GitHub-Token).
* **Zwei Karenzen, die man nicht verwechseln darf.** `NETZ_KARENZ_TAGE` (14)
  ueberbrueckt einen unerreichbaren Statusdienst mit dem zuletzt bekannten
  Stand. `EINFUEHRUNG_KARENZ_TAGE` (30) gilt fuer Systeme, die noch nie eine
  gueltige Lizenz hatten: dort laeuft zunaechst alles unveraendert weiter,
  damit ein Update nicht ueber Nacht Skills abschaltet.
* **Fail-closed, aber nie totsperrend.** Jeder Fehler endet bei FREE, nicht bei
  einem gesperrten System. Ein internes Betriebssystem, das sich wegen einer
  Lizenzfrage selbst abschaltet, trifft im Zweifel den Falschen.
* **Wer root hat, kann das hier patchen.** Das ist bekannt und akzeptiert: das
  Modul ist eine Vertragskontrolle, kein Kopierschutz. Es soll erkennbar und
  nachweisbar machen, was benutzt wird – nicht unmoeglich.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = PROJECT_ROOT / "data" / "license.json"
ROOT_PUB_FILE = Path(__file__).resolve().parent / "license_root.pub"

TOKEN_PREFIX = "JARVIS-LIC-1"

# Namespace fuer die Lizenz-UUID (v5). Muss mit dem license-manager
# uebereinstimmen – wird hier nur zum Nachrechnen der UUID benutzt.
UUID_NAMESPACE = uuid.UUID("6f9a1f2c-7b3d-5e4a-9c81-2d0f5a7b3e11")

ARTEN = ("FREE", "BASIC", "ENTERPRISE")

# Netz-Karenz: so lange gilt der zuletzt geholte Stand weiter, wenn GitHub
# nicht erreichbar ist. Danach FREE. 14 Tage, weil eine Firewall-Umstellung
# oder ein Betriebsurlaub sonst mitten in den Betrieb schlagen wuerde.
NETZ_KARENZ_TAGE = 14
# Einfuehrungs-Karenz fuer Systeme ohne (gueltige) Lizenz: Grenzen greifen
# erst danach. Verhindert, dass ein Update auf Bestandssystemen sofort Skills
# abschaltet.
EINFUEHRUNG_KARENZ_TAGE = 30

# Abrufziel. Eigenes Repo, damit ein Widerruf nicht am Release-Rhythmus des
# Codes haengt.
STATUS_URL = os.environ.get(
    "JARVIS_LICENSE_URL",
    "https://raw.githubusercontent.com/dev-core-busy/jarvis-licenses/main/status.json",
)
ABRUF_TIMEOUT = 15

# Grenzen je Stufe. None = unbegrenzt.
#   profile   – gleichzeitig nutzbare LLM-Profile
#   skills    – gleichzeitig aktive Skills
#   benutzer  – verschiedene Personen mit Anmeldung in den letzten 30 Tagen
#   rag       – Dateien in der Wissensdatenbank
#   standort_sync – Wissensordner von anderen Jarvis-Standorten spiegeln
#                   (Einstellungen -> Wissen -> Pull-Synchronisation). Ein
#                   Merkmal, kein Zaehler: Mehr-Standort-Betrieb ist die
#                   ENTERPRISE-Eigenschaft. Gespiegelte Dateien zaehlen NICHT
#                   gegen `rag` (siehe license_enforce.anzahl_rag) – sie sind am
#                   abgebenden Standort schon lizenziert.
GRENZEN = {
    "FREE":       {"updates": "keine",   "auto_update": False, "standort_sync": False,
                   "profile": 1, "skills": 5, "benutzer": 5,  "rag": 50},
    "BASIC":      {"updates": "manuell", "auto_update": False, "standort_sync": False,
                   "profile": 1, "skills": 5, "benutzer": 10, "rag": 100},
    "ENTERPRISE": {"updates": "alle",    "auto_update": True,  "standort_sync": True,
                   "profile": None, "skills": None, "benutzer": None, "rag": None},
}

BENUTZER_FENSTER_TAGE = 30

_lock = threading.RLock()
_state: dict | None = None

# Zwischenspeicher. `zustand()` haengt an jeder Rechtefrage (Login, Skill-
# Schalter, Update-Knopf) und wird dadurch oft aufgerufen; die Hardware-Kennung
# kostet einen Unterprozess (findmnt). Beides aendert sich im Betrieb praktisch
# nie – der Zustand nur durch einen Prueflauf oder das Eintragen eines
# Schluessels, und genau dort wird der Speicher verworfen.
_ZUSTAND_TTL = 30.0
_hwid_cache: str = ""
_zustand_cache: tuple[float, dict] | None = None


def _cache_leeren() -> None:
    global _zustand_cache
    with _lock:
        _zustand_cache = None


# ─── Hilfen ────────────────────────────────────────────────────────────────

def _b64e(roh: bytes) -> str:
    return base64.urlsafe_b64encode(roh).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    text = (text or "").strip()
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def kanonisch(daten: dict) -> bytes:
    """Byte-Darstellung fuer Signaturen.

    Muss im license-manager identisch sein – sortierte Schluessel, keine
    Leerzeichen, UTF-8 ohne Escapes. Wer hier etwas aendert, macht alle
    ausgestellten Lizenzen ungueltig.
    """
    return json.dumps(daten, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def lizenz_id(lizenz_uuid: str) -> str:
    """Oeffentliche Kennung einer Lizenz: SHA256 der UUID, 32 Hex-Zeichen.

    In der Statusdatei steht nur dieser Wert. Ein Aussenstehender kann daraus
    weder die UUID noch den Kunden ableiten, aber jedes System findet seinen
    eigenen Eintrag.
    """
    return hashlib.sha256(f"jarvis-lizenz|{lizenz_uuid}".encode()).hexdigest()[:32]


def _jetzt() -> float:
    return time.time()


def _iso(ts: float | None) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def _tage_seit(ts: float | None) -> float | None:
    if not ts:
        return None
    return max(0.0, (_jetzt() - ts) / 86400.0)


def _datum_ok(bis: str | None) -> bool:
    """True, wenn `bis` leer (unbegrenzt) oder noch nicht vergangen ist."""
    if not bis:
        return True
    try:
        d = datetime.fromisoformat(str(bis).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        # Ablauf am Ende des Tages
        return d.timestamp() + 86400 > _jetzt()
    except Exception:
        return False


def _tage_bis(bis: str | None) -> int | None:
    if not bis:
        return None
    try:
        d = datetime.fromisoformat(str(bis).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return int((d.timestamp() + 86400 - _jetzt()) // 86400)
    except Exception:
        return None


# ─── Hardware-Kennung ──────────────────────────────────────────────────────
#
# Drei Merkmale, einzeln gehasht, Vergleich mit Toleranz "2 von 3". Ein
# exakter Vergleich wuerde jeden NIC-Tausch und jede VM-Migration zum
# Supportfall machen; ein einzelnes Merkmal (z.B. nur die MAC) waere zu leicht
# nachzustellen. Ausgegeben werden nur Hashes – die Kennung darf gefahrlos per
# Mail verschickt werden und verraet weder MAC noch Maschinen-ID.

def _lies(pfad: str) -> str:
    try:
        return Path(pfad).read_text().strip()
    except Exception:
        return ""


def _machine_id() -> str:
    return _lies("/etc/machine-id") or _lies("/var/lib/dbus/machine-id")


def _rootfs_uuid() -> str:
    """UUID des Wurzel-Dateisystems (ueberlebt einen Netzwerkkarten-Tausch)."""
    try:
        r = subprocess.run(["findmnt", "-no", "UUID", "/"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    # Rueckfall: Geraetenummer des Wurzel-Dateisystems. Schwaecher, aber
    # besser als ein leeres Merkmal (leer zaehlt nie als Uebereinstimmung).
    try:
        return f"dev:{os.stat('/').st_dev}"
    except Exception:
        return ""


def _mac() -> str:
    """MAC der ersten echten Netzwerkkarte (alphabetisch, ohne lo/virtuelle)."""
    basis = Path("/sys/class/net")
    try:
        namen = sorted(p.name for p in basis.iterdir())
    except Exception:
        return ""
    for name in namen:
        if name == "lo" or name.startswith(("veth", "docker", "br-", "virbr", "tun", "tap")):
            continue
        # Virtuelle Geraete haben keinen 'device'-Verweis – die MAC einer
        # Bruecke aendert sich mit ihren Mitgliedern und taugt nicht.
        if not (basis / name / "device").exists():
            continue
        adresse = _lies(str(basis / name / "address"))
        if adresse and adresse != "00:00:00:00:00:00":
            return adresse.lower()
    return ""


def _merkmal(typ: str, wert: str) -> str:
    if not wert:
        return ""
    return hashlib.sha256(f"jarvis-hwid-1|{typ}|{wert}".encode()).hexdigest()[:12]


def hwid() -> str:
    """Hardware-Kennung dieses Systems, Format `H1-<a>-<b>-<c>`.

    Ein leeres Merkmal erscheint als `-` und zaehlt beim Vergleich nie als
    Treffer; zwei fehlende Merkmale machen die Bindung damit unmoeglich –
    absichtlich, denn sonst genuegte eine Maschine ohne machine-id und ohne
    Netzwerkkarte, um jede Kennung zu erfuellen.

    Wird einmal je Prozesslauf ermittelt: `findmnt` ist ein Unterprozess, und
    die Kennung aendert sich zur Laufzeit nicht (eine Hardware-Aenderung
    bedeutet ohnehin einen Neustart).
    """
    global _hwid_cache
    if _hwid_cache:
        return _hwid_cache
    teile = [
        _merkmal("machine-id", _machine_id()) or "-",
        _merkmal("rootfs", _rootfs_uuid()) or "-",
        _merkmal("mac", _mac()) or "-",
    ]
    _hwid_cache = "H1-" + "-".join(teile)
    return _hwid_cache


def hwid_passt(erwartet: str, aktuell: str | None = None) -> bool:
    """2 von 3 Merkmalen muessen uebereinstimmen (positionsgenau)."""
    aktuell = aktuell or hwid()
    try:
        a = str(erwartet).split("-")
        b = str(aktuell).split("-")
        if len(a) != 4 or len(b) != 4 or a[0] != "H1" or b[0] != "H1":
            return False
        treffer = sum(1 for x, y in zip(a[1:], b[1:]) if x == y and x != "-")
        return treffer >= 2
    except Exception:
        return False


# ─── Signaturpruefung ──────────────────────────────────────────────────────

def _ed25519_pruefen(pub_b64: str, signatur_b64: str, daten: bytes) -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        pub = Ed25519PublicKey.from_public_bytes(_b64d(pub_b64))
        pub.verify(_b64d(signatur_b64), daten)
        return True
    except Exception:
        # Auch ein fehlendes `cryptography` landet hier: ohne Pruefbarkeit
        # gilt keine Lizenz (fail-closed).
        return False


def root_pubkey() -> str:
    """Root-Public-Key aus `backend/license_root.pub` (Base64, eine Zeile)."""
    try:
        text = ROOT_PUB_FILE.read_text().strip()
        # Kommentarzeilen erlauben, damit die Datei erklaerbar bleibt
        for zeile in text.splitlines():
            zeile = zeile.strip()
            if zeile and not zeile.startswith("#"):
                return zeile
    except Exception:
        pass
    return ""


def zertifikat_pruefen(zert: dict) -> tuple[bool, str]:
    """Prueft ein Ausgabe-Zertifikat gegen den Root-Schluessel."""
    if not isinstance(zert, dict):
        return False, "Zertifikat fehlt"
    root = root_pubkey()
    if not root:
        return False, "Root-Schlüssel nicht hinterlegt (backend/license_root.pub)"
    kern = {k: zert.get(k) for k in ("kid", "pub", "gueltig_bis")}
    if not kern.get("pub"):
        return False, "Zertifikat unvollständig"
    if not _ed25519_pruefen(root, zert.get("sig_root", ""), kanonisch(kern)):
        return False, "Zertifikat nicht vom Root-Schlüssel signiert"
    if not _datum_ok(kern.get("gueltig_bis")):
        return False, "Ausgabe-Zertifikat abgelaufen"
    return True, ""


def token_pruefen(token: str) -> tuple[dict | None, str]:
    """Zerlegt und prueft ein Lizenz-Token.

    Rueckgabe: (nutzdaten, fehler). Bei Erfolg ist `fehler` leer.
    Geprueft werden Aufbau, Zertifikatskette, Signatur und – als
    Konsistenzprobe – dass die UUID wirklich zu den Kundendaten passt. Die
    UUID ist deterministisch (v5); eine abweichende Kennung waere ein Zeichen
    dafuer, dass jemand die Nutzdaten nachtraeglich veraendert hat, ohne
    signieren zu koennen.
    """
    token = (token or "").strip()
    if not token:
        return None, "Kein Lizenzschlüssel eingetragen"
    # Zeilenumbrueche/Leerzeichen aus Copy&Paste entfernen
    token = re.sub(r"\s+", "", token)
    teile = token.split(".")
    if len(teile) != 4 or teile[0] != TOKEN_PREFIX:
        # Die Meldung muss sagen, WAS zu tun ist. "Unbekanntes Format" ist
        # richtig und trotzdem nutzlos – die beiden Verwechslungen, die
        # tatsaechlich vorkommen, werden deshalb einzeln benannt.
        try:
            uuid.UUID(token)
            return None, ("Das ist die Lizenzkennung, nicht der Lizenzschlüssel. "
                          "Der Schlüssel ist ein langer Text, der mit "
                          "„JARVIS-LIC-1.“ beginnt – er steht beim Anbieter "
                          "unter „Schlüssel anzeigen“.")
        except Exception:
            pass
        if token.startswith(TOKEN_PREFIX):
            return None, (f"Der Lizenzschlüssel ist unvollständig: erwartet werden "
                          f"vier durch Punkt getrennte Teile, gefunden sind "
                          f"{len(teile)}. Bitte den gesamten Text kopieren.")
        return None, ("Das sieht nicht nach einem Lizenzschlüssel aus. Er beginnt "
                      "mit „JARVIS-LIC-1.“ und ist mehrere hundert Zeichen lang.")
    try:
        nutzdaten = json.loads(_b64d(teile[1]).decode("utf-8"))
        zert = json.loads(_b64d(teile[3]).decode("utf-8"))
    except Exception:
        return None, "Lizenzschlüssel ist beschädigt"
    if not isinstance(nutzdaten, dict) or not isinstance(zert, dict):
        return None, "Lizenzschlüssel ist beschädigt"

    ok, fehler = zertifikat_pruefen(zert)
    if not ok:
        return None, fehler

    if not _ed25519_pruefen(zert.get("pub", ""), teile[2], kanonisch(nutzdaten)):
        return None, "Signatur des Lizenzschlüssels stimmt nicht"

    if nutzdaten.get("v") != 1:
        return None, "Lizenzversion wird nicht unterstützt"
    if nutzdaten.get("art") not in ARTEN:
        return None, "Unbekannte Lizenzart"

    # Die Kennung muss VORHANDEN und wohlgeformt sein – sie ist der Schluessel
    # in den Statusdienst.
    #
    # Frueher wurde hier zusaetzlich nachgerechnet, ob sie sich aus
    # `firma|abteilung|mail|nr` ableiten laesst (v5). Diese Probe ist am
    # 2026-08-07 ENTFALLEN, aus zwei Gruenden:
    #   1. Sie schuetzte nichts. Wer die Nutzdaten aendert, bricht die
    #      Signatur; wer signieren kann, setzt die Kennung passend mit. Sie war
    #      eine Selbstpruefung des Ausgabewerkzeugs – und die gehoert dorthin,
    #      nicht in jedes Kundensystem (`lizenzmanager.py` prueft es beim
    #      Anlegen und wehrt dort auch Kollisionen ab).
    #   2. Sie machte Firma und Abteilung UNVERAENDERLICH: eine Umfirmierung
    #      haette die Kennung verschoben, damit den Eintrag im Statusdienst und
    #      die Hardware-Bindung – der Kunde waere ohne eigenes Zutun auf FREE
    #      gefallen. Die Kennung ist jetzt die dauerhafte Identitaet, die
    #      Stammdaten sind veraenderliche Angaben.
    try:
        uuid.UUID(str(nutzdaten.get("uuid", "")))
    except Exception:
        return None, "Lizenzkennung fehlt oder ist unbrauchbar"

    return nutzdaten, ""


# ─── Zustand auf Platte ────────────────────────────────────────────────────

def _leer() -> dict:
    return {
        "token": "",
        "eingetragen_am": None,
        "eingetragen_von": "",
        "gebunden_hwid": "",       # HWID beim ersten Start mit diesem Token
        "gebunden_am": None,
        "letzter_check": None,     # letzter VERSUCH
        "letzter_erfolg": None,    # letzter erfolgreicher Abruf
        "letzter_fehler": "",
        "status_stand": "",        # Zeitstempel der zuletzt akzeptierten Datei
        "status_eintrag": None,    # eigener Eintrag daraus
        "etag": "",
        "ohne_lizenz_seit": None,  # Beginn der Einfuehrungs-Karenz
        "manipulation": "",        # Klartext, wenn etwas nicht stimmt
    }


def _laden() -> dict:
    global _state
    with _lock:
        if _state is None:
            daten = _leer()
            try:
                if STATE_FILE.exists():
                    gelesen = json.loads(STATE_FILE.read_text())
                    if isinstance(gelesen, dict):
                        daten.update({k: v for k, v in gelesen.items() if k in daten})
            except Exception as e:  # noqa: BLE001
                print(f"[Lizenz] Zustandsdatei unlesbar: {e}", flush=True)
            _state = daten
        return _state


def _speichern() -> None:
    """Atomar schreiben und auf 0640 setzen.

    Die Datei enthaelt Firma, Abteilung und Ansprechpartner-Mail – sie geht
    niemanden an, der Shell-Zugriff in der Sandbox hat.
    """
    with _lock:
        daten = _laden()
        # Jede Zustandsaenderung geht hier durch – der einzige Ort, an dem der
        # Zwischenspeicher sicher verworfen werden kann.
        _cache_leeren()
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(daten, indent=2, ensure_ascii=False))
            os.replace(tmp, STATE_FILE)
            try:
                os.chmod(STATE_FILE, 0o640)
            except Exception:
                pass
        except Exception as e:  # noqa: BLE001
            print(f"[Lizenz] Zustand konnte nicht gespeichert werden: {e}", flush=True)


# ─── Statusdatei von GitHub ────────────────────────────────────────────────

def _statusdatei_pruefen(roh: bytes) -> tuple[dict | None, str]:
    """Signatur und Aufbau der Statusdatei pruefen."""
    try:
        daten = json.loads(roh.decode("utf-8"))
    except Exception:
        return None, "Statusdatei ist kein gültiges JSON"
    if not isinstance(daten, dict) or daten.get("v") != 1:
        return None, "Statusdatei hat eine unbekannte Version"
    zert = daten.get("zert")
    ok, fehler = zertifikat_pruefen(zert)
    if not ok:
        return None, f"Statusdatei: {fehler}"
    kern = {"v": daten.get("v"), "stand": daten.get("stand"),
            "eintraege": daten.get("eintraege")}
    if not _ed25519_pruefen(zert.get("pub", ""), daten.get("sig", ""), kanonisch(kern)):
        return None, "Statusdatei ist nicht korrekt signiert"
    if not isinstance(daten.get("eintraege"), dict):
        return None, "Statusdatei ohne Einträge"
    return daten, ""


def _abrufen(etag: str = "") -> tuple[bytes | None, str, str]:
    """Statusdatei laden. Rueckgabe: (inhalt, etag, fehler).

    `inhalt=None` mit leerem Fehler heisst: unveraendert (HTTP 304).
    """
    import urllib.error
    import urllib.request

    anfrage = urllib.request.Request(STATUS_URL, headers={
        "User-Agent": "jarvis-license/1",
        "Accept": "application/json",
    })
    if etag:
        anfrage.add_header("If-None-Match", etag)
    try:
        with urllib.request.urlopen(anfrage, timeout=ABRUF_TIMEOUT) as antwort:
            inhalt = antwort.read(4 * 1024 * 1024)
            return inhalt, antwort.headers.get("ETag", "") or etag, ""
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return None, etag, ""
        return None, etag, f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return None, etag, str(e)


def pruefen(force: bool = False) -> dict:
    """Einen Prueflauf ausfuehren (Netzzugriff!) und den Zustand fortschreiben.

    Laeuft synchron – Aufrufer sollen `asyncio.to_thread` benutzen.
    """
    from backend import audit_log

    with _lock:
        zustand_vorher = zustand()
        daten = _laden()
        daten["letzter_check"] = _jetzt()

        nutzdaten, fehler = token_pruefen(daten.get("token", ""))
        if not nutzdaten:
            daten["letzter_fehler"] = fehler
            # Nur ein EINGETRAGENER, aber ungueltiger Schluessel ist ein
            # Manipulationsverdacht. "Kein Schluessel" ist der Normalzustand
            # einer frischen Installation und darf kein Warnbanner ausloesen.
            daten["manipulation"] = fehler if daten.get("token") else ""
            _speichern()
            return _nach_pruefung(zustand_vorher, force)

        # Selbstbindung beim ersten Start mit diesem Schluessel
        eigene = hwid()
        if not daten.get("gebunden_hwid"):
            daten["gebunden_hwid"] = eigene
            daten["gebunden_am"] = _jetzt()
            try:
                audit_log.log_tool("system", "lizenz_aktivierung",
                                   {"uuid": nutzdaten.get("uuid"), "hwid": eigene}, 0, 0)
            except Exception:
                pass

        inhalt, etag, netzfehler = _abrufen(daten.get("etag", ""))
        if netzfehler:
            daten["letzter_fehler"] = netzfehler
            _speichern()
            return _nach_pruefung(zustand_vorher, force)

        daten["etag"] = etag
        if inhalt is None:
            # 304: der bekannte Stand gilt weiter und ist frisch bestaetigt
            daten["letzter_erfolg"] = _jetzt()
            daten["letzter_fehler"] = ""
            _speichern()
            return _nach_pruefung(zustand_vorher, force)

        status, fehler = _statusdatei_pruefen(inhalt)
        if not status:
            daten["letzter_fehler"] = fehler
            daten["manipulation"] = fehler
            _speichern()
            return _nach_pruefung(zustand_vorher, force)

        # Rueckspielschutz: ein aelterer Stand als der bekannte wird nicht
        # angenommen. Sonst genuegte es, eine alte Datei erneut auszuliefern,
        # um einen Widerruf rueckgaengig zu machen.
        stand_neu = str(status.get("stand") or "")
        stand_alt = str(daten.get("status_stand") or "")
        if stand_alt and stand_neu < stand_alt:
            daten["letzter_fehler"] = "Statusdatei ist älter als der bekannte Stand"
            daten["manipulation"] = daten["letzter_fehler"]
            _speichern()
            return _nach_pruefung(zustand_vorher, force)

        eintrag = status["eintraege"].get(lizenz_id(str(nutzdaten.get("uuid"))))
        daten["status_stand"] = stand_neu
        daten["status_eintrag"] = eintrag if isinstance(eintrag, dict) else None
        daten["letzter_erfolg"] = _jetzt()
        daten["letzter_fehler"] = ""
        daten["manipulation"] = ""
        _speichern()
        return _nach_pruefung(zustand_vorher, force)


def _nach_pruefung(vorher: dict, force: bool) -> dict:
    """Folgen eines Prueflaufs: Stufenwechsel protokollieren und durchsetzen."""
    nachher = zustand()
    if vorher.get("art") != nachher.get("art") or force:
        try:
            from backend import audit_log
            audit_log.log_tool("system", "lizenz_status", {
                "vorher": vorher.get("art"), "nachher": nachher.get("art"),
                "grund": nachher.get("grund", ""),
            }, 0, 0)
        except Exception:
            pass
    try:
        from backend import license_enforce
        nachher["durchgesetzt"] = license_enforce.anwenden(nachher)
    except Exception as e:  # noqa: BLE001
        print(f"[Lizenz] Durchsetzung fehlgeschlagen: {e}", flush=True)
    return nachher


# ─── Zustand berechnen ─────────────────────────────────────────────────────

def zustand() -> dict:
    """Aktuelle Lage – ohne Netzzugriff, nur aus dem gespeicherten Stand.

    Das ist die Funktion, die alle Aufrufer benutzen sollen. Sie ist billig
    (30 s zwischengespeichert) und darf bei jeder Anfrage aufgerufen werden.
    """
    global _zustand_cache
    with _lock:
        if _zustand_cache and (_jetzt() - _zustand_cache[0]) < _ZUSTAND_TTL:
            return dict(_zustand_cache[1])
        info = _zustand_berechnen()
        _zustand_cache = (_jetzt(), info)
        return dict(info)


def _zustand_berechnen() -> dict:
    with _lock:
        daten = _laden()

        # Beginn der Einfuehrungs-Karenz festhalten, sobald das System zum
        # ersten Mal ohne gueltige Lizenz gesehen wird.
        nutzdaten, fehler = token_pruefen(daten.get("token", ""))

        info = {
            "art": "FREE",
            "art_lizenz": (nutzdaten or {}).get("art", ""),
            "gueltig": False,
            "grund": "",
            "hinweis": "",
            "banner": "",
            "hwid": hwid(),
            "gebunden": False,
            "firma": (nutzdaten or {}).get("firma", ""),
            "abteilung": (nutzdaten or {}).get("abteilung", ""),
            "mail": (nutzdaten or {}).get("mail", ""),
            "uuid": (nutzdaten or {}).get("uuid", ""),
            "gueltig_bis": (nutzdaten or {}).get("gueltig_bis") or "",
            "tage_bis_ablauf": _tage_bis((nutzdaten or {}).get("gueltig_bis")),
            "hat_token": bool(daten.get("token")),
            "letzter_check": _iso(daten.get("letzter_check")),
            "letzter_erfolg": _iso(daten.get("letzter_erfolg")),
            "letzter_fehler": daten.get("letzter_fehler", ""),
            "status_stand": daten.get("status_stand", ""),
            "karenz_tage_rest": None,
            "einfuehrung_karenz": False,
            "einfuehrung_rest_tage": None,
        }

        if not nutzdaten:
            info["grund"] = fehler
            if daten.get("token"):
                info["banner"] = fehler
        else:
            eintrag = daten.get("status_eintrag")
            netz_alter = _tage_seit(daten.get("letzter_erfolg"))
            # Das MASSGEBLICHE Ablaufdatum kommt aus dem Statusdienst, wenn er
            # eines nennt – sonst aus dem Token. Beide Angaben tragen dieselbe
            # Signatur derselben Ausgabestelle; die aus dem Statusdienst ist nur
            # die frischere. Deshalb darf sie **verlängern und verkürzen**, und
            # eine Vertragsverlängerung braucht keinen neuen Schlüsseltext beim
            # Kunden mehr.
            #   Das Token-Datum bleibt trotzdem wirksam, wo es gebraucht wird:
            #   ohne erreichbaren Statusdienst gilt es weiter, und nach
            #   NETZ_KARENZ_TAGE ohne Kontakt endet ohnehin alles bei FREE. Eine
            #   Verlängerung wirkt also nur gegen frischen Nachweis.
            #   `"gueltig_bis" in eintrag` statt `.get(...)`: ein leerer Wert
            #   heisst "unbegrenzt" und ist eine Aussage – ein FEHLENDES Feld
            #   (älterer/fremder Statusgenerator) ist keine und fällt auf das
            #   Token zurück.
            ablauf = nutzdaten.get("gueltig_bis")
            if isinstance(eintrag, dict) and "gueltig_bis" in eintrag:
                ablauf = eintrag.get("gueltig_bis")
            if daten.get("letzter_erfolg") is None:
                info["grund"] = "Lizenzstatus wurde noch nie erfolgreich geprüft"
            elif netz_alter is not None and netz_alter > NETZ_KARENZ_TAGE:
                info["grund"] = (f"Lizenzstatus seit {int(netz_alter)} Tagen nicht "
                                 f"erreichbar (Karenz {NETZ_KARENZ_TAGE} Tage)")
                info["banner"] = info["grund"]
            elif eintrag is None:
                info["grund"] = "Lizenz ist im Statusdienst nicht bekannt"
                info["banner"] = info["grund"]
            elif str(eintrag.get("status", "")).lower() == "revoked":
                info["grund"] = "Lizenz wurde widerrufen"
                info["banner"] = info["grund"]
            elif not _datum_ok(ablauf):
                info["grund"] = "Lizenz ist abgelaufen"
            elif not eintrag.get("hwid"):
                info["grund"] = ("Lizenz ist noch nicht an dieses System gebunden – "
                                 "Hardware-Kennung beim Anbieter hinterlegen")
                info["gebunden"] = False
            elif not hwid_passt(str(eintrag.get("hwid")), info["hwid"]):
                info["grund"] = "Lizenz ist an eine andere Hardware gebunden"
                info["banner"] = info["grund"]
            else:
                art = str(eintrag.get("art") or nutzdaten.get("art") or "FREE").upper()
                if art not in ARTEN:
                    art = "FREE"
                info["art"] = art
                info["gueltig"] = True
                info["gebunden"] = True
                # Angezeigt wird das massgebliche Datum – sonst stuende im Panel
                # ein Ablauf, der laengst verschoben wurde.
                info["gueltig_bis"] = ablauf or ""
                info["tage_bis_ablauf"] = _tage_bis(ablauf)
                if netz_alter is not None and netz_alter > 1:
                    # Aufrunden: nach 3,0001 Tagen sind noch 11 Tage Karenz uebrig,
                    # nicht 10. Ein Abrunden verschenkt dem Benutzer einen ganzen
                    # Tag und laesst die Anzeige zu frueh dramatisch aussehen.
                    info["karenz_tage_rest"] = max(0, math.ceil(NETZ_KARENZ_TAGE - netz_alter))

        # Einfuehrungs-Karenz: gilt fuer Systeme, die noch nie eine gueltige
        # Lizenz hatten. Waehrend dieser Zeit werden KEINE Grenzen durchgesetzt.
        if info["gueltig"]:
            if daten.get("ohne_lizenz_seit"):
                daten["ohne_lizenz_seit"] = None
                _speichern()
        else:
            if not daten.get("ohne_lizenz_seit"):
                daten["ohne_lizenz_seit"] = _jetzt()
                _speichern()
            alter = _tage_seit(daten.get("ohne_lizenz_seit")) or 0.0
            if alter < EINFUEHRUNG_KARENZ_TAGE:
                info["einfuehrung_karenz"] = True
                info["einfuehrung_rest_tage"] = max(
                    1, math.ceil(EINFUEHRUNG_KARENZ_TAGE - alter))

        # Ein festgestellter Manipulationsverdacht ueberlebt den Prueflauf: er
        # steht im gespeicherten Zustand und muss auch dann sichtbar sein, wenn
        # die Kette oben (mangels brauchbarem Statusstand) keinen eigenen Grund
        # gefunden hat. Ohne das waere eine gefaelschte Statusdatei nur eine
        # Zeile im Journal.
        if not info["banner"] and daten.get("manipulation"):
            info["banner"] = daten["manipulation"]

        info["grenzen"] = dict(GRENZEN[info["art"]])
        info["durchsetzung_aktiv"] = not info["einfuehrung_karenz"]
        if info["einfuehrung_karenz"]:
            # Waehrend der Karenz gilt faktisch keine Beschraenkung.
            info["grenzen"] = dict(GRENZEN["ENTERPRISE"])
        return info


# ─── Abfragen fuer die Durchsetzung ────────────────────────────────────────

def grenze(name: str):
    """Aktuelle Grenze fuer `profile|skills|benutzer|rag` (None = unbegrenzt)."""
    try:
        return zustand()["grenzen"].get(name)
    except Exception:
        return None


def updates_erlaubt() -> tuple[bool, str]:
    """Darf ein Update angewendet werden?"""
    z = zustand()
    if z["grenzen"].get("updates") == "keine":
        return False, ("Software-Updates sind mit dieser Lizenz nicht enthalten. "
                       "Bitte einen gültigen Lizenzschlüssel eintragen "
                       "(Einstellungen → KI & System → System-Einstellungen).")
    return True, ""


def auto_update_erlaubt() -> tuple[bool, str]:
    """Darf ein zeitgesteuertes Update eingerichtet werden?"""
    z = zustand()
    if not z["grenzen"].get("auto_update"):
        if z["grenzen"].get("updates") == "keine":
            return False, ("Software-Updates sind mit dieser Lizenz nicht enthalten.")
        return False, ("Automatische Updates sind der ENTERPRISE-Lizenz vorbehalten. "
                       "Manuelle Updates bleiben möglich.")
    return True, ""


def standort_sync_erlaubt() -> tuple[bool, str]:
    """Darf dieser Server Wissensordner anderer Standorte spiegeln?

    Waehrend der Einfuehrungs-Karenz gelten die ENTERPRISE-Grenzen, das Merkmal
    ist dort also an – so schaltet ein Update auf einem Bestandssystem nichts
    ueber Nacht ab.
    """
    z = zustand()
    if not z["grenzen"].get("standort_sync"):
        return False, ("Die Synchronisation mit anderen Standorten ist der "
                       "ENTERPRISE-Lizenz vorbehalten. Bereits gespiegeltes Wissen "
                       "bleibt lesbar und durchsuchbar.")
    return True, ""


def setze_token(token: str, benutzer: str = "") -> dict:
    """Neuen Lizenzschluessel eintragen. Prueft sofort (inkl. Netzabruf).

    Wirft `ValueError`, wenn der Schluessel unbrauchbar ist – und laesst den
    bisherigen Zustand dann **unangetastet**. Das ist wichtig: sonst zerstoert
    eine Fehleingabe (z.B. die Lizenzkennung statt des Schluessels) eine
    laufende Lizenz samt Hardware-Bindung, und das System faellt bis zur
    erneuten Eingabe auf FREE. Live aufgefallen am 2026-08-07.

    Ein formal gueltiger Schluessel wird dagegen IMMER uebernommen, auch wenn
    er im Statusdienst noch unbekannt ist – das ist der Normalzustand zwischen
    Ausstellen und Binden.
    """
    nutzdaten, fehler = token_pruefen(token)
    if not nutzdaten:
        raise ValueError(fehler)
    with _lock:
        daten = _laden()
        alt = re.sub(r"\s+", "", daten.get("token") or "")
        neu = re.sub(r"\s+", "", token or "")
        daten["token"] = neu
        daten["eingetragen_am"] = _jetzt()
        daten["eingetragen_von"] = benutzer or ""
        if neu != alt:
            # Bindung und Statuscache gehoeren zum alten Schluessel.
            daten["gebunden_hwid"] = ""
            daten["gebunden_am"] = None
            daten["status_eintrag"] = None
            daten["status_stand"] = ""
            daten["etag"] = ""
            daten["letzter_erfolg"] = None
        _speichern()
    return pruefen(force=True)


def entferne_token(benutzer: str = "") -> dict:
    """Lizenzschluessel entfernen (System faellt auf FREE zurueck)."""
    with _lock:
        daten = _laden()
        daten.update({
            "token": "", "gebunden_hwid": "", "gebunden_am": None,
            "status_eintrag": None, "status_stand": "", "etag": "",
            "letzter_erfolg": None, "letzter_fehler": "", "manipulation": "",
            "eingetragen_von": benutzer or "",
        })
        _speichern()
    try:
        from backend import audit_log
        audit_log.log_tool(benutzer or "system", "lizenz_entfernt", {}, 0, 0)
    except Exception:
        pass
    return zustand()


def _reset_fuer_tests() -> None:
    """Zwischenspeicher verwerfen (nur fuer Tests)."""
    global _state
    with _lock:
        _state = None
