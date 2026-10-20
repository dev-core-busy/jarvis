"""Hauptschluessel ausserhalb von data/ – fuer Modulschluessel und settings.json (BSI M5).

BEFUND M5 (BSI-Abgleich 2026-09-29): "Sammelgeheimnisse im Klartext in
settings.json (0600); Fernet-Schluessel neben Chiffrat". Sieben Module
(mail/sap/vemas/jira/confluence_accounts, mount_credentials, ai_mouse_signatur)
legten ihren Fernet-Schluessel als ``data/.<name>key`` NEBEN die Datei mit dem
Chiffrat – wer ``data/`` kopiert (Sicherung, Datei-Werkzeug, Fehlkonfiguration),
hatte beides. Und settings.json trug LLM-Schluessel, Agent-API-Keys, das
AD-Bind-Kennwort und alle Sammelzugaenge der Skills im Klartext.

DER HAUPTSCHLUESSEL liegt root-eigen in ``/etc/jarvis/geheimnis.key`` (0600).
Angelegt wird er von ``deploy/security/haertung_installieren.sh`` bei jedem
Broker-Start, der ihn per ``LoadCredential=geheimnis:...`` an jarvis.service
reicht (Drop-in ``40-geheimnis.conf``). Der Dienstbenutzer kann die Datei
selbst NICHT lesen – er bekommt eine Kopie unter ``$CREDENTIALS_DIRECTORY``,
die nur sein Prozess sieht. Ein root-Prozess (Broker, Alt-Betrieb als root)
liest die Datei direkt. Entscheidung des Betreibers 2026-10-05: Root-Datei
statt systemd-creds/TPM – kopierbar fuer Sicherung und Umzug.

ZWEI ANWENDUNGEN:
  * **Modulschluessel verpacken** (``modul_schluessel``): die Datei
    ``data/.mailkey`` usw. enthaelt danach ``JGK1:<Fernet-Token>`` statt des
    rohen Schluessels. Das CHIFFRAT der Konten bleibt unveraendert – es wird
    nichts umgeschluesselt, ein Fehler beim Verpacken kann also keine Kennwoerter
    kosten. Ein Altbestand (roher Schluessel) wird beim ersten Zugriff mit
    vorhandenem Hauptschluessel verpackt.
  * **Felder in settings.json** (``verschluessele_baum``/``entschluessele_baum``):
    Werte mit geheimem Feldnamen werden beim Schreiben zu ``JGS1:<Token>``,
    beim Lesen zurueck. config.py tut das an der Dateigrenze; im Speicher und
    fuer alle Aufrufer bleibt alles wie bisher.

OHNE HAUPTSCHLUESSEL (Entwicklungsrechner, Docker ohne Datei, Dienst vor dem
ersten Broker-Lauf) bleibt alles wie VOR M5: roher Schluessel, Klartext-Felder.
Das ist bewusst KEIN fail-closed: ein fehlender Schluessel darf die Anwendung
nicht lahmlegen, und schlechter als vorher wird nichts. Den Zustand meldet
``status()`` (Sicherheitsseite), damit er nicht still bleibt.

WAS NIE PASSIEREN DARF – und wie es verhindert wird:
  * Ein verpackter Wert wird OHNE Schluessel nie "repariert": ``JGS1:``-Werte,
    die sich nicht oeffnen lassen, bleiben unveraendert stehen und werden
    unveraendert zurueckgeschrieben. Ein Dienststart ohne Credential verliert
    also nichts, er kann die Werte nur nicht benutzen.
  * Ein verpackter Modulschluessel wird ohne Hauptschluessel NICHT durch einen
    neuen ersetzt (das wuerde alle Kennwoerter des Moduls entwerten) – es
    gibt einen sprechenden Fehler.
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path

PRAEFIX_SCHLUESSEL = b"JGK1:"
PRAEFIX_WERT = "JGS1:"
CREDENTIAL_NAME = "geheimnis"
# Ueberschreibbar fuer Docker (kein systemd) und Tests.
ROOT_DATEI = Path(os.environ.get("JARVIS_GEHEIMNIS_DATEI") or "/etc/jarvis/geheimnis.key")


class TresorFehler(Exception):
    """Ein verpackter Schluessel/Wert laesst sich nicht oeffnen."""


_lock = threading.Lock()
_cache: dict = {}            # {"fernet": Fernet|None, "quelle": str}


def _zuruecksetzen_fuer_test() -> None:
    with _lock:
        _cache.clear()


def _kandidaten() -> list[tuple[Path, str]]:
    aus = []
    cd = os.environ.get("CREDENTIALS_DIRECTORY", "").strip()
    if cd:
        aus.append((Path(cd) / CREDENTIAL_NAME, "systemd-Credential"))
    datei = Path(os.environ.get("JARVIS_GEHEIMNIS_DATEI") or ROOT_DATEI)
    aus.append((datei, str(datei)))
    return aus


def hauptfernet():
    """Fernet ueber den Hauptschluessel – oder None, wenn keiner erreichbar ist.

    Gemerkt fuer die Lebensdauer des Prozesses: der Schluessel kommt mit dem
    Dienststart (Credential) und aendert sich nicht im Lauf.
    """
    with _lock:
        if "fernet" in _cache:
            return _cache["fernet"]
        f, quelle, fehler = None, "", ""
        try:
            from cryptography.fernet import Fernet  # noqa: PLC0415
        except Exception as e:  # noqa: BLE001
            Fernet, fehler = None, f"cryptography fehlt: {e}"
        if Fernet is not None:
            for pfad, name in _kandidaten():
                try:
                    roh = pfad.read_bytes().strip()
                except OSError:
                    continue
                if not roh:
                    continue
                try:
                    f, quelle = Fernet(roh), name
                except Exception as e:  # noqa: BLE001
                    # Kaputte Datei: NICHT still auf den naechsten Kandidaten
                    # ausweichen – ein falscher Schluessel wuerde neue Werte
                    # unter einem Schluessel ablegen, der nach dem Reparieren
                    # nicht mehr passt.
                    fehler = f"{name} ist kein gueltiger Schluessel: {e}"
                break
        _cache["fernet"] = f
        _cache["quelle"] = quelle
        _cache["fehler"] = fehler
        if fehler:
            print(f"[Tresor] {fehler}", flush=True)
        return f


def status() -> dict:
    """Fuer die Sicherheitsseite: ist ein Hauptschluessel aktiv, woher?"""
    f = hauptfernet()
    return {"aktiv": f is not None, "quelle": _cache.get("quelle", ""),
            "fehler": _cache.get("fehler", "")}


# ─── Modulschluessel ────────────────────────────────────────────────────────

def _schreibe_atomar(datei: Path, inhalt: bytes, modus: int) -> None:
    """tmp mit Modus anlegen, schreiben, umbenennen; Eigentuemer erhalten."""
    st = None
    try:
        st = datei.stat()
    except OSError:
        st = None
    tmp = datei.with_name(datei.name + ".tmp")
    # Erst mit Modus anlegen, DANN schreiben – nie kurz mit 0644 auf der Platte.
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, modus)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(inhalt)
            fh.flush()
            os.fsync(fh.fileno())
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    os.chmod(tmp, modus)
    if st is not None and os.geteuid() == 0:
        try:
            os.chown(tmp, st.st_uid, st.st_gid)
        except OSError:
            pass
    os.replace(tmp, datei)


def modul_schluessel(datei: Path, modus: int = 0o600, anlegen: bool = True) -> bytes:
    """Roher Fernet-Schluessel eines Moduls (``data/.mailkey`` usw.).

    * verpackt (``JGK1:``) → mit dem Hauptschluessel oeffnen; ohne ihn
      TresorFehler (nie einen neuen anlegen – das entwertete alle Kennwoerter);
    * roh (Altbestand) → zurueckgeben und, wenn ein Hauptschluessel da ist,
      die Datei verpacken (misslingt das, bleibt sie roh – nichts geht verloren);
    * fehlt → neu anlegen (verpackt, wenn moeglich), sofern ``anlegen``.
    """
    datei = Path(datei)
    haupt = hauptfernet()
    roh = b""
    if datei.exists():
        roh = datei.read_bytes().strip()
    if roh.startswith(PRAEFIX_SCHLUESSEL):
        if haupt is None:
            raise TresorFehler(
                f"{datei.name} ist mit dem Hauptschluessel verpackt, der in diesem "
                f"Prozess fehlt (/etc/jarvis/geheimnis.key bzw. systemd-Credential "
                f"'{CREDENTIAL_NAME}'). Dienst ueber systemd starten.")
        try:
            return haupt.decrypt(roh[len(PRAEFIX_SCHLUESSEL):])
        except Exception as e:  # noqa: BLE001
            raise TresorFehler(
                f"{datei.name} passt nicht zum Hauptschluessel – wurde "
                f"/etc/jarvis/geheimnis.key ersetzt?") from e
    if roh:
        if haupt is not None:
            try:
                _schreibe_atomar(datei, PRAEFIX_SCHLUESSEL + haupt.encrypt(roh), modus)
                print(f"[Tresor] {datei.name} mit dem Hauptschluessel verpackt", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"[Tresor] {datei.name} nicht verpackt: {e}", flush=True)
        return roh
    if not anlegen:
        raise FileNotFoundError(str(datei))
    from cryptography.fernet import Fernet  # noqa: PLC0415
    neu = Fernet.generate_key()
    datei.parent.mkdir(parents=True, exist_ok=True)
    inhalt = PRAEFIX_SCHLUESSEL + haupt.encrypt(neu) if haupt is not None else neu
    _schreibe_atomar(datei, inhalt, modus)
    return neu


# Die Schluesseldateien der Konten-Module (Namen wie in den Modulen selbst).
MODUL_SCHLUESSEL = (".mailkey", ".sapkey", ".vemaskey", ".jirakey", ".confluencekey",
                    ".mountkey", ".aimousesignkey")


def alle_modulschluessel_verpacken(data_dir: Path) -> dict:
    """Beim Dienststart: jede VORHANDENE rohe Schluesseldatei verpacken.

    Ohne das bliebe der Schluessel eines selten benutzten Bereichs (ein
    Postfach, das niemand oeffnet) roh in data/ liegen – genau bis zum ersten
    Zugriff. Legt nichts an, was fehlt. Ohne Hauptschluessel: nichts.
    Rueckgabe: {name: "verpackt"|"war verpackt"|"fehlt"|"fehler: ..."}."""
    aus = {}
    if hauptfernet() is None:
        return aus
    for name in MODUL_SCHLUESSEL:
        pf = Path(data_dir) / name
        if not pf.exists():
            aus[name] = "fehlt"
            continue
        if ist_verpackt(pf):
            aus[name] = "war verpackt"
            continue
        try:
            modul_schluessel(pf, anlegen=False)
            aus[name] = "verpackt" if ist_verpackt(pf) else "roh geblieben"
        except Exception as e:  # noqa: BLE001
            aus[name] = "fehler: %s" % e
    return aus


def verpackt_ohne_schluessel(data_dir: Path) -> list[str]:
    """Dateien in data/, die VERPACKTES enthalten, waehrend in diesem Prozess
    KEIN Hauptschluessel da ist – leer, wenn alles in Ordnung ist.

    Genau der Zustand vom Vorfall ECHT 2026-10-05 (Backend vor dem Drop-in
    gestartet): nichts geht verloren, aber der Dienst kann weder LLM-Schluessel
    noch Tokens noch Sitzungen benutzen – und ohne diese Meldung sah das wie
    viele unabhaengige Stoerungen aus."""
    if hauptfernet() is not None:
        return []
    d = Path(data_dir)
    aus = [n for n in MODUL_SCHLUESSEL + (".secret_key",) if ist_verpackt(d / n)]
    for n in ("settings.json", "auth_state.json", "knowledge_sync.json"):
        try:
            if PRAEFIX_WERT in (d / n).read_text(encoding="utf-8"):
                aus.append(n)
        except OSError:
            pass
    return aus


def ist_verpackt(datei: Path) -> bool:
    try:
        return Path(datei).read_bytes().strip().startswith(PRAEFIX_SCHLUESSEL)
    except OSError:
        return False


# ─── Felder in settings.json ────────────────────────────────────────────────
#
# Welche Felder geheim sind, entscheidet der NAME – EINE Regel fuer die ganze
# Datei, weil die Geheimnisse dort an vielen Stellen stehen (Profile, extra,
# skills.*.config, mcp_servers[].env) und jeder neue Skill weitere bringt. Eine
# Pfadliste liefe beim naechsten Feld auseinander.
#
# Bewusst KEIN Teilstring "token"/"pass": vemas hat ``token_json_path``,
# ``token_header``, ``login_pass_field`` – Konfiguration, kein Geheimnis.
GEHEIME_NAMEN = frozenset({
    "password", "passwort", "kennwort", "secret", "client_secret",
    "api_key", "apikey", "api_token", "bot_token", "bearer_token", "token",
    "session_key", "agent_api_key", "access_token", "refresh_token",
    "private_key",
})
# "_token" deckt auch Umgebungsvariablen von MCP-Servern (GITHUB_TOKEN) –
# Namen werden klein verglichen. "token_json_path" endet NICHT darauf.
GEHEIME_ENDUNGEN = ("_password", "_passwort", "_kennwort", "_secret",
                    "_api_key", "_apikey", "_token", "_secret_key",
                    "_private_key", "_pat")
# Listen, deren Eintraege ein Feld "key" als Geheimnis tragen.
_LISTEN_MIT_KEY = frozenset({"agent_api_keys"})


def ist_geheimer_name(name) -> bool:
    n = str(name or "").strip().lower()
    if not n or n.endswith("_enc"):          # schon Chiffrat eines Moduls
        return False
    return n in GEHEIME_NAMEN or n.endswith(GEHEIME_ENDUNGEN)


# Werte, die in einem geheimen FELD stehen, aber kein Geheimnis SIND – sie
# bleiben Klartext.
#
# ⚠ WARUM (gemessen auf DEV am 2026-10-20, Stunden nach dem Einbau): seit das
# 2FA-Geheimnis eines Kontos im Root-Broker liegen kann, traegt
# ``auth_state.json`` dort nur noch den Verweis ``"broker"``. Der steht im Feld
# ``totp_secret``, und das ist ein geheimer Name – also hat ``_load_auth_state``
# den Verweis fuer einen Klartext-Altbestand gehalten und VERPACKT. Es
# funktionierte trotzdem (beim Lesen wird wieder entpackt), aber:
#   * Fehlt der Hauptschluessel, bleibt ``JGS1:…`` stehen. Dann trifft weder
#     ``_totp_im_broker`` noch ``_totp_secret_lesbar`` zu → 503, obwohl das
#     Geheimnis root-eigen daneben liegt und der Broker antworten koennte.
#     Genau dieses Fenster gab es am 2026-10-05 wirklich (Broker und Backend
#     starteten zugleich, das Credential-Drop-in kam zwei Sekunden zu spaet).
#   * Die Datei behauptet, dort laege ein Geheimnis. Es liegt keines dort.
# Ein Verweis gehoert nicht verschluesselt. Die Ausnahme ist bewusst eine
# WERTLISTE und keine Feldausnahme: ``totp_secret`` muss ein echtes Secret
# weiterhin verpacken.
KLARTEXT_WERTE = frozenset({"broker"})


def wert_verschluesseln(wert: str) -> str:
    f = hauptfernet()
    if f is None or not isinstance(wert, str) or not wert or wert.startswith(PRAEFIX_WERT):
        return wert
    if wert in KLARTEXT_WERTE:
        return wert
    return PRAEFIX_WERT + f.encrypt(wert.encode("utf-8")).decode("ascii")


def wert_entschluesseln(wert):
    """Klartext – oder der Wert UNVERAENDERT, wenn er sich nicht oeffnen laesst."""
    if not isinstance(wert, str) or not wert.startswith(PRAEFIX_WERT):
        return wert
    f = hauptfernet()
    if f is None:
        return wert
    try:
        return f.decrypt(wert[len(PRAEFIX_WERT):].encode("ascii")).decode("utf-8")
    except Exception:  # noqa: BLE001
        print("[Tresor] ein Wert in settings.json passt nicht zum Hauptschluessel "
              "– bleibt verpackt stehen", flush=True)
        return wert


def _baum(o, fn_geheim, geheim_key: bool = False):
    if isinstance(o, dict):
        aus = {}
        for k, v in o.items():
            if isinstance(v, str) and (ist_geheimer_name(k) or (geheim_key and k == "key")):
                aus[k] = fn_geheim(v)
            else:
                aus[k] = _baum(v, fn_geheim, geheim_key=False) if not isinstance(v, list) \
                    else [_baum(x, fn_geheim, geheim_key=(str(k) in _LISTEN_MIT_KEY)) for x in v]
        return aus
    if isinstance(o, list):
        return [_baum(x, fn_geheim) for x in o]
    return o


def verschluessele_baum(daten):
    """Kopie mit verpackten Geheimfeldern (ohne Hauptschluessel: unveraendert)."""
    if hauptfernet() is None:
        return daten
    return _baum(daten, wert_verschluesseln)


def entschluessele_baum(daten):
    """Kopie mit geoeffneten ``JGS1:``-Werten – an JEDER Stelle, nicht nur an
    geheimen Namen: ein Wert, der einmal verpackt wurde, wird immer geoeffnet,
    auch wenn sich die Namensregel spaeter aendert."""
    def _alle(o):
        if isinstance(o, dict):
            return {k: _alle(v) for k, v in o.items()}
        if isinstance(o, list):
            return [_alle(x) for x in o]
        return wert_entschluesseln(o)
    return _alle(daten)


def klartext_felder(daten) -> list[str]:
    """Pfade geheimer Felder, die noch im Klartext stehen (fuer Migration/Status).

    ``KLARTEXT_WERTE`` zaehlen NICHT mit – sie stehen absichtlich im Klartext.
    ⚠ Ohne diese Ausnahme meldet ``_load_auth_state`` den Broker-Verweis bei
    JEDEM Start als Altbestand, schreibt die Datei neu (samt neuer ``.bak``) und
    gibt "2FA-Geheimnisse verpackt" ins Journal – eine Meldung im Normalbetrieb,
    die das Journal entwertet. Auf DEV am 2026-10-20 bei drei Neustarts in Folge
    gesehen.
    """
    gefunden: list[str] = []

    def _geh(o, pfad, geheim_key=False):
        if isinstance(o, dict):
            for k, v in o.items():
                p = f"{pfad}.{k}" if pfad else str(k)
                if isinstance(v, str) and v and not v.startswith(PRAEFIX_WERT) \
                        and v not in KLARTEXT_WERTE \
                        and (ist_geheimer_name(k) or (geheim_key and k == "key")):
                    gefunden.append(p)
                elif isinstance(v, list):
                    for i, x in enumerate(v):
                        _geh(x, f"{p}[{i}]", geheim_key=(str(k) in _LISTEN_MIT_KEY))
                else:
                    _geh(v, p)
    _geh(daten, "")
    return gefunden


__all__ = [
    "TresorFehler", "PRAEFIX_SCHLUESSEL", "PRAEFIX_WERT", "CREDENTIAL_NAME",
    "hauptfernet", "status", "modul_schluessel", "ist_verpackt", "MODUL_SCHLUESSEL",
    "alle_modulschluessel_verpacken", "verpackt_ohne_schluessel",
    "ist_geheimer_name", "wert_verschluesseln", "wert_entschluesseln",
    "verschluessele_baum", "entschluessele_baum", "klartext_felder",
]
