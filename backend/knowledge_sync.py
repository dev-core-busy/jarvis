"""Pull-Synchronisation von Wissensordnern zwischen Jarvis-Standorten.

Eine Einbahnstrasse: Standort 3 HOLT einen Ordner, den ein Administrator an
Standort 1 oder 2 freigegeben hat. Der Geber schickt nie von sich aus etwas –
alle Verbindungen gehen vom Nehmer aus. Damit funktioniert das auch, wenn der
Nehmer hinter NAT sitzt und nur ausgehend darf.

Zwei Rollen, ein Modul – jede Instanz kann beides gleichzeitig sein:

  GEBER   `shares`  – Freigabe = EIN Ordner samt komplettem Unterbaum + EIN
                      Token. Der freigegebene Ordner mit zehn Unterordnern
                      braucht also genau ein Token; mehrere Token entstehen nur,
                      wenn ein Administrator bewusst mehrere GETRENNTE Freigaben
                      anlegt (dann ist auch der Widerruf einzeln moeglich).
  NEHMER  `peers`   – Ein Eintrag = ein Standort + ein Token = ein Ordner. Das
                      Ziel wird lokal wie eine gewoehnliche Wissensquelle
                      behandelt: Ordner unter ``data/``, Aufnahme in die
                      Ordner-Liste, Zuordnung zu einer Wissensgruppe, danach
                      normale Indizierung. Nach dem Lauf liegt das entfernte
                      Wissen als lokale Kopie UND als RAG-Eintraege vor.

Grundregeln, die den Rest des Moduls erklaeren:

* **Der entfernte Stand gewinnt.** Der Zielordner ist ein SPIEGEL: entfernt
  geloeschte Dateien werden lokal entfernt, lokale Aenderungen ueberschrieben.
  Damit das nicht zur Datenfalle wird, ist der Ordner lokal schreibgesperrt
  (``ist_spiegel``) – kein Upload, keine Unterordner, kein Extraktor-Ziel.
* **Inkrementell.** Uebertragen wird nur die Differenz zum letzten Lauf. Ein
  vollstaendiger Abgleich bei jedem Durchlauf waere bei mehreren hundert
  Dateien ueber eine Standortverbindung unbenutzbar.
* **Nichts wird geraten.** Ein Ziel, das sich nicht sicher unter den Zielordner
  aufloesen laesst, wird verworfen (nicht "bereinigt"); ein Zertifikat, das
  nicht zum gespeicherten Fingerabdruck passt, bricht den Lauf ab; ein
  entzogener Token laesst die lokale Kopie stehen und meldet den Grund.
* **Fail-closed bei der Lizenz.** Mehr-Standort-Betrieb ist ENTERPRISE; ohne
  das Merkmal laeuft kein Sync (und der Container sagt es).

Persistenz: ``data/knowledge_sync.json`` (0640, in den Sandbox-Sperrlisten).
Die Datei enthaelt die Token FREMDER Standorte im Klartext – sie ist damit so
sensibel wie eine Skill-Zugangsdatei und geht einen Shell-Befehl in der Sandbox
nichts an.
"""

import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import socket
import ssl
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
STATE_PATH = PROJECT_ROOT / "data" / "knowledge_sync.json"

# ─── Grenzen ─────────────────────────────────────────────────────────────────
# Deckel je Lauf. Sie sind KEINE Aufbewahrungs-Schranke (siehe die Lehre zu
# Stueckzahlen im Projekt), sondern eine Notbremse gegen einen versehentlich
# freigegebenen Riesenordner. Wird gekuerzt, steht die Zahl im Ergebnis – ein
# stiller Schnitt liesse den Nehmer glauben, er haette alles.
MAX_DATEIEN = 5000
MAX_BYTES = 5 * 1024 * 1024 * 1024          # 5 GB je Lauf
MAX_DATEI_BYTES = 512 * 1024 * 1024         # 512 MB je Einzeldatei
HTTP_TIMEOUT = 60.0                         # Sekunden je Anfrage
PULL_LOG_MAX = 50                           # Abruf-Protokoll je Freigabe

# Untergrenze fuer die Automatik. Ein Intervall von einer Minute waere ein
# Dauerlauf ueber die Standortverbindung, ohne dass sich Wissen so schnell
# aendert.
MIN_INTERVALL_SEK = 300
EINHEITEN = {"minutes": 60, "hours": 3600, "days": 86400}

TOKEN_PREFIX = "JARVIS-KBS-1."

_lock = threading.RLock()
_state: dict | None = None

# Ein Sync je Standort, und nie zwei gleichzeitig: der Neuaufbau des Index darf
# keinen halb kopierten Ordner einlesen.
_sync_lock = threading.Lock()
_laufend: dict = {}        # peer_id -> Fortschritt (nur im Speicher)


# ─── Hilfen ──────────────────────────────────────────────────────────────────

def _jetzt() -> float:
    return time.time()


def _neue_id() -> str:
    return secrets.token_hex(8)


def _rel(pfad) -> str:
    """Normalisiert auf einen relativen Posix-Pfad zu PROJECT_ROOT."""
    p = Path(pfad)
    try:
        if p.is_absolute():
            p = p.relative_to(PROJECT_ROOT)
    except ValueError:
        pass
    return p.as_posix().strip("/")


def _text(wert, max_len: int = 200) -> str:
    return str(wert or "").strip()[:max_len]


def rechnername() -> str:
    """Vorbelegung fuer den Standortnamen dieser Instanz."""
    try:
        return socket.gethostname() or "jarvis"
    except Exception:  # noqa: BLE001
        return "jarvis"


def _slug(wert: str) -> str:
    """Ordner-taugliche Fassung eines Namens (fuer die Vorbelegung des Ziels)."""
    s = (wert or "").strip().lower()
    s = (s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
          .replace("ß", "ss"))
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "standort"


# ─── Zustand laden/speichern ────────────────────────────────────────────────

def _leer() -> dict:
    return {"site_name": "", "shares": [], "peers": []}


def _laden() -> dict:
    global _state
    with _lock:
        if _state is not None:
            return _state
        daten = _leer()
        try:
            if STATE_PATH.exists():
                roh = json.loads(STATE_PATH.read_text(encoding="utf-8"))
                if isinstance(roh, dict):
                    daten["site_name"] = _text(roh.get("site_name"), 80)
                    daten["shares"] = [s for s in roh.get("shares", [])
                                       if isinstance(s, dict) and s.get("id")]
                    daten["peers"] = [p for p in roh.get("peers", [])
                                      if isinstance(p, dict) and p.get("id")]
        except Exception as e:  # noqa: BLE001
            # Beschaedigte Datei darf den Start nicht verhindern; sie wird beim
            # naechsten Speichern ersetzt. Lieber ohne Freigaben weiterlaufen
            # als der Dienst gar nicht.
            print(f"[KB-Sync] Zustand nicht lesbar, starte leer: {e}", flush=True)
            daten = _leer()
        _state = daten
        return _state


def _speichern() -> None:
    """Atomar schreiben, Eigentuemer und 0640 erhalten.

    Eigentuemer: der Root-Broker kann diese Datei anfassen – gehoerte sie danach
    root, koennte das unprivilegierte Backend seine eigenen Freigaben nicht mehr
    speichern (dieselbe Falle wie bei settings.json).
    """
    with _lock:
        daten = _state if _state is not None else _leer()
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        st = None
        try:
            if STATE_PATH.exists():
                st = STATE_PATH.stat()
        except Exception:  # noqa: BLE001
            st = None
        tmp = STATE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(daten, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, STATE_PATH)
        try:
            os.chmod(STATE_PATH, 0o640)
        except Exception:  # noqa: BLE001
            pass
        try:
            if st is not None and os.geteuid() == 0 and (st.st_uid != 0 or st.st_gid != 0):
                os.chown(STATE_PATH, st.st_uid, st.st_gid)
        except Exception:  # noqa: BLE001
            pass


def _reset_fuer_tests() -> None:
    global _state
    with _lock:
        _state = None
        _laufend.clear()


# ─── Standortname dieser Instanz ────────────────────────────────────────────

def site_name() -> str:
    """Name dieses Standorts. Er geht als Kennung an den Geber (der zeigt damit,
    WER gezogen hat) und belegt beim Nehmer den Zielordner vor."""
    return _laden().get("site_name") or rechnername()


def set_site_name(name: str) -> str:
    with _lock:
        _laden()["site_name"] = _text(name, 80)
        _speichern()
    return site_name()


# ─── Rolle GEBER: Freigaben ─────────────────────────────────────────────────

def _share_public(s: dict, mit_token: bool = False) -> dict:
    aus = {
        "id": s["id"],
        "folder": s.get("folder", ""),
        "label": s.get("label", ""),
        "enabled": bool(s.get("enabled", True)),
        "created_at": s.get("created_at"),
        "created_by": s.get("created_by", ""),
        "pulls": list(s.get("pulls", []))[:PULL_LOG_MAX],
    }
    if mit_token:
        aus["token"] = s.get("token", "")
    return aus


def list_shares(mit_token: bool = False) -> list[dict]:
    with _lock:
        return [_share_public(s, mit_token) for s in _laden()["shares"]]


def get_share(share_id: str) -> dict | None:
    with _lock:
        for s in _laden()["shares"]:
            if s["id"] == share_id:
                return s
    return None


def share_fuer_ordner(rel_folder: str) -> dict | None:
    """Freigabe eines bestimmten Ordners (fuer das Symbol an der Ordnerzeile)."""
    rel = _rel(rel_folder)
    with _lock:
        for s in _laden()["shares"]:
            if s.get("folder") == rel:
                return s
    return None


def create_share(rel_folder: str, label: str = "", benutzer: str = "") -> dict:
    """Legt eine Freigabe an und erzeugt ihr Token.

    Der Ordner muss existieren und ein Wissensordner (oder ein Unterordner
    davon) sein – eine Freigabe auf ``/etc`` waere sonst ein Dateiserver.
    """
    rel = _rel(rel_folder)
    absolut = _wissenspfad(rel)
    if absolut is None:
        raise ValueError("Der Ordner liegt nicht in den Wissensordnern.")
    if not absolut.is_dir():
        raise ValueError("Ordner nicht gefunden.")
    with _lock:
        daten = _laden()
        for s in daten["shares"]:
            if s.get("folder") == rel:
                raise ValueError("Für diesen Ordner besteht schon eine Freigabe.")
        sid = _neue_id()
        share = {
            "id": sid,
            "folder": rel,
            "label": _text(label, 120) or Path(rel).name,
            "token": TOKEN_PREFIX + sid + "." + secrets.token_urlsafe(32),
            "enabled": True,
            "created_at": _jetzt(),
            "created_by": _text(benutzer, 120),
            "pulls": [],
        }
        daten["shares"].append(share)
        _speichern()
        return _share_public(share, mit_token=True)


# Nur diese Felder darf PATCH aendern. Ohne Whitelist nimmt ein Merge beliebige
# Felder – dann liesse sich `folder` auf einen fremden Pfad umschreiben oder ein
# eigenes `token` unterschieben (dieselbe Luecke wie scheduler.update_job bis
# 2026-07-28). `id`, `folder` und `token` sind unveraenderlich.
SHARE_UPDATABLE = ("label", "enabled")


def update_share(share_id: str, **felder) -> dict | None:
    with _lock:
        for s in _laden()["shares"]:
            if s["id"] != share_id:
                continue
            for k, v in felder.items():
                if k not in SHARE_UPDATABLE:
                    continue
                if k == "enabled":
                    s[k] = bool(v)
                else:
                    s[k] = _text(v, 120)
            _speichern()
            return _share_public(s, mit_token=True)
    return None


def delete_share(share_id: str) -> bool:
    """Widerruf. Das Token ist danach wertlos – ein laufender Pull des Nehmers
    endet mit "Freigabe entzogen", seine lokale Kopie bleibt liegen."""
    with _lock:
        daten = _laden()
        vorher = len(daten["shares"])
        daten["shares"] = [s for s in daten["shares"] if s["id"] != share_id]
        if len(daten["shares"]) == vorher:
            return False
        _speichern()
        return True


def rotate_token(share_id: str) -> dict | None:
    """Neues Token, gleiche Freigabe – fuer den Fall, dass ein Token abgeflossen
    ist, ohne den Ordner neu einrichten zu muessen."""
    with _lock:
        for s in _laden()["shares"]:
            if s["id"] == share_id:
                s["token"] = TOKEN_PREFIX + s["id"] + "." + secrets.token_urlsafe(32)
                _speichern()
                return _share_public(s, mit_token=True)
    return None


def share_by_token(token: str) -> dict | None:
    """Freigabe zu einem Token – die Auth der Pull-Routen.

    Der Vergleich laeuft ueber ``hmac.compare_digest``: ein zeichenweiser
    Vergleich verraet ueber die Laufzeit, wie viele Zeichen stimmen. Die
    Freigabe-Kennung steckt im Token, damit ohne Durchprobieren aller Freigaben
    nachgesehen werden kann – sie ist kein Geheimnis, das Geheimnis ist der
    dritte Teil.
    """
    tok = (token or "").strip()
    if not tok.startswith(TOKEN_PREFIX):
        return None
    teile = tok[len(TOKEN_PREFIX):].split(".", 1)
    if len(teile) != 2 or not teile[0] or not teile[1]:
        return None
    sid = teile[0]
    with _lock:
        for s in _laden()["shares"]:
            if s["id"] != sid:
                continue
            if not s.get("enabled", True):
                return None
            if hmac.compare_digest(str(s.get("token", "")), tok):
                return s
            return None
    return None


def record_pull(share_id: str, standort: str, adresse: str,
                dateien: int, bytes_: int, art: str = "datei") -> None:
    """Abruf protokollieren. Der Geber soll sehen, WELCHE Standorte ziehen –
    nicht nur, dass irgendwer gezogen hat.

    Nur Manifest-Abrufe erzeugen einen Eintrag; jede einzelne Datei zu
    protokollieren wuerde das Protokoll mit hunderten Zeilen je Lauf fuellen und
    die Aussage "wer war das" darin begraben.
    """
    if art != "manifest":
        return
    with _lock:
        for s in _laden()["shares"]:
            if s["id"] != share_id:
                continue
            s.setdefault("pulls", []).insert(0, {
                "ts": _jetzt(),
                "site": _text(standort, 80) or "unbekannt",
                "ip": _text(adresse, 60),
                "files": int(dateien),
                "bytes": int(bytes_),
            })
            del s["pulls"][PULL_LOG_MAX:]
            _speichern()
            return


# ─── Manifest (Geber) ───────────────────────────────────────────────────────

def _wissenspfad(rel: str) -> Path | None:
    """Aufgeloester Pfad, sofern er in einem konfigurierten Wissensordner liegt.

    Aufgeloest (``resolve``), nicht per Textvergleich: ein Symlink im
    Wissensordner koennte sonst auf ``/etc`` zeigen und die Freigabe waere ein
    Dateiserver. Dieselbe Lehre wie bei den Shell-Redirect-Zielen (2026-08-05).
    """
    rel = _rel(rel)
    if not rel or ".." in Path(rel).parts:
        return None
    try:
        ziel = (PROJECT_ROOT / rel).resolve()
    except (OSError, ValueError):
        return None
    try:
        from backend.tools.knowledge import _get_folders
        wurzeln = _get_folders()
    except Exception:  # noqa: BLE001
        wurzeln = [PROJECT_ROOT / "data" / "knowledge"]
    for w in wurzeln:
        try:
            wa = Path(w).resolve()
        except (OSError, ValueError):
            continue
        if ziel == wa or wa in ziel.parents:
            return ziel
    return None


def _endungen() -> set:
    """Indizierbare Endungen – dieselbe Liste, die der Upload akzeptiert.

    Etwas anderes zu uebertragen waere sinnlos: der Nehmer koennte es nicht
    indizieren, und der Ordner ist bei ihm schreibgesperrt.
    """
    try:
        from backend.tools.knowledge import (
            EXTENSIONS_TEXT, EXTENSIONS_PDF, EXTENSIONS_DOCX, EXTENSIONS_XLSX,
            EXTENSIONS_PPTX, EXTENSIONS_VIDEO, EXTENSIONS_AUDIO, EXTENSIONS_IMAGE)
        return (EXTENSIONS_TEXT | EXTENSIONS_PDF | EXTENSIONS_DOCX | EXTENSIONS_XLSX
                | EXTENSIONS_PPTX | EXTENSIONS_VIDEO | EXTENSIONS_AUDIO
                | EXTENSIONS_IMAGE)
    except Exception:  # noqa: BLE001
        return {".txt", ".md", ".pdf", ".docx", ".xlsx", ".pptx", ".csv"}


def sha256_datei(pfad: Path, blocks: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(pfad, "rb") as f:
        while True:
            block = f.read(blocks)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def build_manifest(share: dict) -> dict:
    """Dateiliste einer Freigabe mit Groesse, mtime und SHA-256.

    Der Hash ist die Grundlage des inkrementellen Abgleichs UND die
    Integritaetspruefung beim Nehmer. Er wird nur fuer Dateien berechnet, deren
    Groesse/mtime sich seit dem letzten Manifest geaendert hat – ein
    Neu-Hashen von 900 PDF-Dateien bei jedem Abruf waere sonst der teuerste Teil
    des Verfahrens.
    """
    wurzel = _wissenspfad(share.get("folder", ""))
    if wurzel is None or not wurzel.is_dir():
        raise FileNotFoundError("Freigegebener Ordner nicht gefunden.")
    exts = _endungen()
    cache = share.get("hash_cache") or {}
    neuer_cache: dict = {}
    dateien: list[dict] = []
    gesamt = 0
    gekuerzt = 0
    for root, dirs, fs in os.walk(wurzel, onerror=lambda e: None):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(fs):
            if name.startswith("."):
                continue
            p = Path(root) / name
            if p.suffix.lower() not in exts:
                continue
            # Symlinks werden nicht gefolgt: ein Link im freigegebenen Ordner
            # koennte auf .env oder einen fremden Chat-Verlauf zeigen.
            try:
                st = p.lstat()
            except OSError:
                continue
            if not os.path.isfile(p) or os.path.islink(p):
                continue
            if st.st_size > MAX_DATEI_BYTES:
                gekuerzt += 1
                continue
            if len(dateien) >= MAX_DATEIEN or gesamt + st.st_size > MAX_BYTES:
                gekuerzt += 1
                continue
            rel = p.relative_to(wurzel).as_posix()
            alt = cache.get(rel)
            if (isinstance(alt, dict) and alt.get("size") == st.st_size
                    and abs(float(alt.get("mtime", 0)) - st.st_mtime) < 0.001
                    and alt.get("sha256")):
                digest = alt["sha256"]
            else:
                try:
                    digest = sha256_datei(p)
                except OSError:
                    continue
            eintrag = {"path": rel, "size": st.st_size,
                       "mtime": round(st.st_mtime, 3), "sha256": digest}
            dateien.append(eintrag)
            neuer_cache[rel] = eintrag
            gesamt += st.st_size
    # Hash-Zwischenspeicher fortschreiben (nur Nebenwirkung, kein Zustand, auf
    # den sich etwas verlaesst – ein Verlust kostet nur Rechenzeit).
    with _lock:
        for s in _laden()["shares"]:
            if s["id"] == share["id"]:
                s["hash_cache"] = neuer_cache
                _speichern()
                break
    return {
        "schema": "jarvis-kb-sync/v1",
        "site": site_name(),
        "share": share["id"],
        "label": share.get("label", ""),
        "folder_name": Path(share.get("folder", "")).name,
        "generated_at": _jetzt(),
        "file_count": len(dateien),
        "total_bytes": gesamt,
        "skipped": gekuerzt,
        "files": dateien,
    }


def resolve_share_file(share: dict, rel_path: str) -> Path | None:
    """Absoluter Pfad einer Datei INNERHALB der Freigabe.

    Fail-closed an vier Stellen: kein ``..``, kein absoluter Pfad, das
    aufgeloeste Ziel muss unter der Freigabe liegen (Symlink!), und es muss eine
    normale Datei mit erlaubter Endung sein. Ohne die Aufloesung waere ein
    Symlink im freigegebenen Ordner der Weg zu ``settings.json``.
    """
    wurzel = _wissenspfad(share.get("folder", ""))
    if wurzel is None:
        return None
    rel = (rel_path or "").strip().replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/") or "\x00" in rel:
        return None
    try:
        ziel = (wurzel / rel).resolve()
        ziel.relative_to(wurzel.resolve())
    except (ValueError, OSError):
        return None
    if not ziel.is_file() or ziel.suffix.lower() not in _endungen():
        return None
    if ziel.name.startswith("."):
        return None
    return ziel


# ─── Rolle NEHMER: Standorte ────────────────────────────────────────────────

def _peer_public(p: dict) -> dict:
    """Standort-Eintrag fuer die Oberflaeche. Das Token geht NICHT hinaus –
    es ist das Geheimnis des Gebers, und die Oberflaeche braucht es nach dem
    Eintragen nie wieder (es gibt einen eigenen Weg, es zu ersetzen)."""
    return {
        "id": p["id"],
        "name": p.get("name", ""),
        "url": p.get("url", ""),
        "fingerprint": p.get("fingerprint", ""),
        "target_folder": p.get("target_folder", ""),
        "group_id": p.get("group_id", ""),
        "state": p.get("state", "active"),
        "auto": bool(p.get("auto", False)),
        "interval": int(p.get("interval", 24) or 24),
        "unit": p.get("unit", "hours"),
        "token_set": bool(p.get("token")),
        "remote_site": p.get("remote_site", ""),
        "remote_label": p.get("remote_label", ""),
        "last_sync": p.get("last_sync"),
        "last_error": p.get("last_error", ""),
        "file_count": int(p.get("file_count", 0) or 0),
        "total_bytes": int(p.get("total_bytes", 0) or 0),
        "running": p["id"] in _laufend,
        "progress": _laufend.get(p["id"], {}),
        "next_run": naechster_lauf(p),
    }


def list_peers() -> list[dict]:
    with _lock:
        return [_peer_public(p) for p in _laden()["peers"]]


def get_peer(peer_id: str) -> dict | None:
    with _lock:
        for p in _laden()["peers"]:
            if p["id"] == peer_id:
                return p
    return None


def normalisiere_url(url: str) -> str:
    """Basis-Adresse des Gebers: Schema + Host + Port, ohne Pfad.

    Nur ``https``. Ein ``http``-Standort waere ein Token im Klartext im
    Firmennetz – und das Token ist der ganze Zugang zur Freigabe.
    """
    u = (url or "").strip()
    if not u:
        raise ValueError("Adresse fehlt.")
    # Das Schema wird ERGAENZT, bevor gekuerzt wird: ein `rstrip("/")` auf
    # "https://" macht daraus "https:", das Praefix passt danach nicht mehr und
    # aus Muell entstuende die gueltig aussehende Adresse "https://https".
    if "://" not in u:
        u = "https://" + u
    # Schemata sind laut RFC gross/klein-gleich: "HTTPS://host" aus der
    # Adresszeile darf nicht als unbekanntes Schema abgewiesen werden.
    schema = u.split("://", 1)[0].lower()
    u = schema + "://" + u.split("://", 1)[1]
    if schema == "http":
        raise ValueError("Nur https:// ist erlaubt – ein Token darf nicht im Klartext "
                         "übertragen werden.")
    if schema != "https":
        raise ValueError("Nur https:// ist erlaubt.")
    from urllib.parse import urlparse
    teile = urlparse(u.rstrip("/"))
    if not teile.hostname:
        raise ValueError("Adresse ist unvollständig.")
    port = f":{teile.port}" if teile.port else ""
    return f"https://{teile.hostname}{port}"


def _intervall_sek(p: dict) -> int:
    faktor = EINHEITEN.get(p.get("unit", "hours"), 3600)
    try:
        n = int(p.get("interval", 24) or 24)
    except (TypeError, ValueError):
        n = 24
    return max(MIN_INTERVALL_SEK, n * faktor)


def naechster_lauf(p: dict) -> float | None:
    """Zeitpunkt des naechsten automatischen Laufs (None = keine Automatik)."""
    if not p.get("auto") or p.get("state") != "active":
        return None
    letzte = (p.get("last_sync") or {}).get("ts") or 0
    return float(letzte) + _intervall_sek(p)


def ziel_vorschlag(standort: str, ordnername: str) -> str:
    """Vorbelegung des Zielordners: ``data/<standort>_<ordner>``.

    Vorbelegt, nicht erzwungen – zwei Standorte mit gleich benannten Ordnern
    kollidieren sonst, und ein Tippfehler soll nicht stillschweigend einen
    zweiten Spiegel anlegen.
    """
    a, b = _slug(standort), _slug(ordnername)
    name = f"{a}_{b}".strip("_") or "standort_wissen"
    return f"data/{name[:60]}"


PEER_UPDATABLE = ("name", "url", "token", "fingerprint", "group_id",
                  "state", "auto", "interval", "unit")


def _pruefe_ziel(rel_ziel: str, eigene_id: str = "") -> str:
    """Zielordner pruefen: unter ``data/``, kein bestehender Wissensordner, kein
    Ziel eines anderen Standorts.

    Der zweite Punkt ist der wichtige: ein Spiegel LOESCHT lokal, was entfernt
    fehlt. Auf einen gewachsenen Wissensordner gerichtet waere der erste Lauf
    ein Datenverlust.
    """
    rel = _rel(rel_ziel)
    if not rel.startswith("data/"):
        raise ValueError("Der Zielordner muss unter data/ liegen.")
    name = rel[len("data/"):]
    if not name or "/" in name or ".." in name or name.startswith("."):
        raise ValueError("Bitte einen einfachen Ordnernamen unter data/ angeben.")
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,60}", name):
        raise ValueError("Erlaubt sind Buchstaben, Zahlen, Unterstrich und Bindestrich.")
    with _lock:
        for p in _laden()["peers"]:
            if p["id"] != eigene_id and _rel(p.get("target_folder", "")) == rel:
                raise ValueError(f"Der Ordner '{rel}' ist schon das Ziel von "
                                 f"'{p.get('name') or p['id']}'.")
    # Ein bereits konfigurierter Wissensordner darf nicht zum Spiegel werden,
    # solange er nicht schon dieser Spiegel ist.
    try:
        from backend.tools.knowledge import _get_folders
        for f in _get_folders():
            if _rel(f) == rel and not ist_spiegel(rel):
                raise ValueError(f"'{rel}' ist bereits ein Wissensordner. Bitte einen "
                                 "neuen, leeren Ordnernamen wählen – ein Spiegel "
                                 "löscht lokal, was am anderen Standort fehlt.")
    except ValueError:
        raise
    except Exception:  # noqa: BLE001
        pass
    return rel


def create_peer(name: str, url: str, token: str, target_folder: str,
                group_id: str = "", fingerprint: str = "", auto: bool = False,
                interval: int = 24, unit: str = "hours",
                remote: dict | None = None) -> dict:
    rel_ziel = _pruefe_ziel(target_folder)
    basis = normalisiere_url(url)
    if not (token or "").strip().startswith(TOKEN_PREFIX):
        raise ValueError(f"Das Token muss mit '{TOKEN_PREFIX}' beginnen. "
                         "Es wird am anderen Standort unter Wissen → Ordner → Freigabe erzeugt.")
    with _lock:
        daten = _laden()
        peer = {
            "id": _neue_id(),
            "name": _text(name, 80) or basis,
            "url": basis,
            "token": (token or "").strip(),
            "fingerprint": _text(fingerprint, 200),
            "target_folder": rel_ziel,
            "group_id": _text(group_id, 80),
            "state": "active",
            "auto": bool(auto),
            "interval": max(1, int(interval or 24)),
            "unit": unit if unit in EINHEITEN else "hours",
            "created_at": _jetzt(),
            "manifest": {},
            "last_sync": None,
            "last_error": "",
            "file_count": 0,
            "total_bytes": 0,
            "remote_site": _text((remote or {}).get("site"), 80),
            "remote_label": _text((remote or {}).get("label"), 120),
        }
        daten["peers"].append(peer)
        _speichern()
        return _peer_public(peer)


def update_peer(peer_id: str, **felder) -> dict | None:
    with _lock:
        for p in _laden()["peers"]:
            if p["id"] != peer_id:
                continue
            for k, v in felder.items():
                if k not in PEER_UPDATABLE:
                    continue
                if k == "auto":
                    p[k] = bool(v)
                elif k == "interval":
                    try:
                        p[k] = max(1, int(v))
                    except (TypeError, ValueError):
                        pass
                elif k == "unit":
                    if v in EINHEITEN:
                        p[k] = v
                elif k == "state":
                    if v in ("active", "paused"):
                        p[k] = v
                elif k == "url":
                    p[k] = normalisiere_url(v)
                elif k == "token":
                    tok = (v or "").strip()
                    if tok:                     # leer = unveraendert
                        if not tok.startswith(TOKEN_PREFIX):
                            raise ValueError(f"Das Token muss mit '{TOKEN_PREFIX}' beginnen.")
                        p[k] = tok
                elif k == "fingerprint":
                    neu = _text(v, 200)
                    # Ein NEUER Fingerabdruck heisst: der Administrator hat ein
                    # geaendertes Zertifikat bewusst uebernommen. Das gebundene
                    # Zertifikat muss dann weg, sonst wuerde die TLS-Schicht
                    # weiter das alte verlangen und der Lauf scheiterte trotz
                    # bestaetigter Uebernahme. `_pem_sicherstellen` holt das neue
                    # und prueft es gegen genau diesen Fingerabdruck.
                    if neu and neu != p.get("fingerprint"):
                        p["cert_pem"] = ""
                    p[k] = neu
                else:
                    p[k] = _text(v, 200)
            _speichern()
            return _peer_public(p)
    return None


def delete_peer(peer_id: str, daten_entfernen: bool = False) -> dict:
    """Standort entfernen. Die lokale Kopie bleibt, sofern nicht ausdruecklich
    ``daten_entfernen`` gesetzt ist – ein Konfigurationsschritt darf nicht
    nebenbei Wissen loeschen."""
    with _lock:
        daten = _laden()
        peer = None
        for p in daten["peers"]:
            if p["id"] == peer_id:
                peer = p
                break
        if peer is None:
            return {"ok": False, "error": "Standort nicht gefunden."}
        ziel = _rel(peer.get("target_folder", ""))
        daten["peers"] = [p for p in daten["peers"] if p["id"] != peer_id]
        _speichern()
    entfernt = 0
    if daten_entfernen and ziel:
        entfernt = _ordner_abraeumen(ziel)
    return {"ok": True, "removed_files": entfernt, "folder": ziel,
            "folder_kept": (not daten_entfernen)}


def _ordner_abstellen(rel_ziel: str) -> bool:
    """Zielordner aus der Wissensordner-Liste nehmen (Gegenstueck zur Aufnahme).

    Nur beim ausdruecklichen Loeschen der Daten: bleibt die Kopie liegen, soll
    sie auch weiter durchsuchbar sein.
    """
    try:
        from backend.config import config
        states = config.get_skill_states()
        state = states.get("knowledge", {})
        cfg = dict(state.get("config", {}))
        liste = [f.strip() for f in str(cfg.get("folders") or "").split(",") if f.strip()]
        rest = [f for f in liste if _rel(f) != _rel(rel_ziel)]
        if len(rest) == len(liste):
            return False
        cfg["folders"] = ",".join(rest) or "data/knowledge"
        state["config"] = cfg
        state.setdefault("enabled", True)
        config.save_skill_state("knowledge", state)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[KB-Sync] Ordner {rel_ziel} nicht abgemeldet: {e}", flush=True)
        return False


def _ordner_abraeumen(rel_ziel: str) -> int:
    """Spiegel-Ordner samt Index und Ordner-Registrierung entfernen."""
    entfernt = 0
    absolut = PROJECT_ROOT / rel_ziel
    _ordner_abstellen(rel_ziel)
    try:
        from backend.tools.knowledge import purge_folder_index
        purge_folder_index(absolut)
    except Exception as e:  # noqa: BLE001
        print(f"[KB-Sync] Index-Bereinigung fuer {rel_ziel} fehlgeschlagen: {e}", flush=True)
    try:
        if absolut.is_dir():
            entfernt = sum(1 for _ in absolut.rglob("*") if _.is_file())
            shutil.rmtree(absolut, ignore_errors=True)
    except Exception as e:  # noqa: BLE001
        print(f"[KB-Sync] Ordner {rel_ziel} nicht entfernt: {e}", flush=True)
    return entfernt


# ─── Spiegel-Schutz ─────────────────────────────────────────────────────────

def spiegel_ordner() -> list[str]:
    """Alle Zielordner (relative Pfade)."""
    with _lock:
        return [_rel(p.get("target_folder", "")) for p in _laden()["peers"]
                if p.get("target_folder")]


def ist_spiegel(rel_path: str) -> bool:
    """Liegt ``rel_path`` in einem Spiegel-Ordner (oder IST einer)?

    Fail-closed benutzt: die Aufrufer sperren das Schreiben, wenn True. Ein
    Fehler hier darf keine Schreiberlaubnis erzeugen.
    """
    rel = _rel(rel_path)
    if not rel:
        return False
    for ziel in spiegel_ordner():
        if rel == ziel or rel.startswith(ziel + "/"):
            return True
    return False


def spiegel_fuer(rel_path: str) -> dict | None:
    """Standort-Eintrag, zu dem ``rel_path`` gehoert (fuer Klartext-Meldungen)."""
    rel = _rel(rel_path)
    with _lock:
        for p in _laden()["peers"]:
            ziel = _rel(p.get("target_folder", ""))
            if ziel and (rel == ziel or rel.startswith(ziel + "/")):
                return p
    return None


def schreibsperre(rel_path: str) -> str:
    """Leerer String = erlaubt, sonst der Grund im Klartext.

    Die Meldung nennt den Standort: "schreibgeschützt" allein ist für einen
    Administrator, der gerade eine Datei hochladen will, nicht deutbar.
    """
    p = spiegel_fuer(rel_path)
    if p is None:
        return ""
    return (f"Der Ordner '{_rel(p.get('target_folder'))}' ist eine Kopie von "
            f"'{p.get('name') or 'einem anderen Standort'}' und wird bei jeder "
            "Synchronisation überschrieben. Änderungen daran wären beim nächsten "
            "Lauf verloren – bitte am Ursprungs-Standort arbeiten.")


def gespiegelte_dateien() -> int:
    """Anzahl gespiegelter Dateien (Stand des letzten Laufs).

    Grundlage der Lizenz-Ausnahme: gespiegelte Dateien zaehlen nicht gegen die
    Wissensdatei-Grenze, weil sie am Geber schon lizenziert sind. Bewusst der
    Stand des letzten Laufs statt eines eigenen Verzeichnis-Durchlaufs – die
    Zaehlung haengt an `anzahl_rag()` und damit an jeder Upload-Pruefung.
    """
    with _lock:
        return sum(int(p.get("file_count", 0) or 0) for p in _laden()["peers"])


# ─── Lizenz ─────────────────────────────────────────────────────────────────

def erlaubt() -> tuple[bool, str]:
    """Darf dieser Server Standort-Synchronisation nutzen? (ENTERPRISE)"""
    try:
        from backend import license as lic
        return lic.standort_sync_erlaubt()
    except Exception:  # noqa: BLE001
        # Fail-open NUR hier: ist das Lizenzmodul nicht ladbar, ist das ein
        # Installationsfehler und keine Aussage ueber die Lizenz. Alle harten
        # Schranken (Token, Pfade, Spiegel) sind davon unabhaengig.
        return True, ""


# ─── HTTPS mit Fingerabdruck-Bindung ────────────────────────────────────────

def _ssl_kontext(peer: dict | None = None) -> ssl.SSLContext:
    """TLS-Kontext. Ist ein Zertifikat gebunden, PRUEFT die TLS-Schicht selbst.

    Jarvis liefert selbst ausgestellte Zertifikate aus, eine gewoehnliche
    CA-Pruefung waere hier immer falsch. Die Bindung laeuft deshalb ueber den
    Vertrauensspeicher: das beim Einrichten bestaetigte Zertifikat wird als
    einziger Vertrauensanker geladen (``cadata``). Damit gilt genau dieses
    Zertifikat – und nichts anderes.

    **Warum nicht der Fingerabdruck aus der Antwort:** Die erste Fassung las ihn
    per ``antwort.extensions["network_stream"]`` und verglich ihn NACH dem
    Verbindungsaufbau. Auf DEV lieferte das nichts (httpx gibt den Stream nur
    waehrend eines offenen ``stream()``-Aufrufs heraus), womit JEDER Lauf mit
    "Zertifikat nicht lesbar" abbrach. Und selbst wenn es ginge, waere es eine
    Pruefung NACH dem Senden des Tokens – die TLS-Schicht ist der richtige Ort.

    ``check_hostname`` bleibt aus: die Standorte werden ueblicherweise ueber IP
    oder einen internen Namen angesprochen, der im Zertifikat nicht steht. Das
    ist unbedenklich, weil nicht "irgendein gueltiges" Zertifikat akzeptiert
    wird, sondern genau das gebundene.
    """
    pem = (peer or {}).get("cert_pem") or ""
    if pem:
        ctx = ssl.create_default_context(cadata=pem)
        ctx.check_hostname = False
        return ctx                       # verify_mode bleibt CERT_REQUIRED
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE      # nur zum ERMITTELN (siehe zertifikat_abfragen)
    return ctx


def zertifikat_abfragen(url: str) -> dict:
    """Zertifikat eines Standorts holen – fuer die Bestaetigung beim Einrichten.

    Gibt Fingerabdruck (fuer die Anzeige) UND das Zertifikat als PEM zurueck
    (fuer die Bindung). Der Administrator sieht den Fingerabdruck, bevor er
    speichert; gebunden wird danach das Zertifikat selbst.
    """
    basis = normalisiere_url(url)
    from urllib.parse import urlparse
    teile = urlparse(basis)
    host, port = teile.hostname, teile.port or 443
    ctx = _ssl_kontext()
    with socket.create_connection((host, port), timeout=10) as rohe:
        with ctx.wrap_socket(rohe, server_hostname=host) as tls:
            der = tls.getpeercert(binary_form=True)
    return {"url": basis, "host": host, "port": port,
            "fingerprint": "sha256:" + hashlib.sha256(der).hexdigest(),
            "cert_pem": ssl.DER_cert_to_PEM_cert(der)}


class FingerprintFehler(RuntimeError):
    pass


def _pem_sicherstellen(peer: dict) -> dict:
    """Sorgt dafuer, dass zum gebundenen Fingerabdruck auch das Zertifikat vorliegt.

    Zwei Faelle:
      * Kein Fingerabdruck gebunden -> das Zertifikat wird geholt UND gebunden
        (erstmaliges Einrichten ohne Pruefung, z.B. per API).
      * Fingerabdruck gebunden, PEM fehlt -> Zertifikat holen und NUR uebernehmen,
        wenn der Fingerabdruck passt. Sonst ist es eine andere Gegenstelle.
    """
    if peer.get("cert_pem"):
        return peer
    zert = zertifikat_abfragen(peer["url"])
    erwartet = (peer.get("fingerprint") or "").strip()
    if erwartet and not hmac.compare_digest(erwartet, zert["fingerprint"]):
        raise FingerprintFehler(_zert_meldung(erwartet, zert["fingerprint"]))
    with _lock:
        for p in _laden()["peers"]:
            if p["id"] == peer["id"]:
                p["cert_pem"] = zert["cert_pem"]
                p["fingerprint"] = zert["fingerprint"]
                _speichern()
                peer = dict(p)
                break
    return peer


def _zert_meldung(erwartet: str, gefunden: str) -> str:
    return ("Das Zertifikat des Standorts hat sich geändert.\n"
            f"erwartet: {erwartet}\ngefunden: {gefunden or 'unbekannt'}\n"
            "Das kann ein erneuertes Zertifikat sein – oder eine fremde Gegenstelle. "
            "Bitte im Standort-Eintrag „Verbindung prüfen\" drücken und den neuen "
            "Fingerabdruck bewusst übernehmen.")


def _zert_fehler_deuten(peer: dict, fehler: Exception) -> Exception:
    """Aus einem TLS-Fehler eine Meldung machen, mit der man etwas anfangen kann.

    Ein ``CERTIFICATE_VERIFY_FAILED`` heisst bei gebundenem Zertifikat: die
    Gegenstelle zeigt ein anderes. Der rohe OpenSSL-Text sagt das niemandem –
    deshalb wird der tatsaechlich gezeigte Fingerabdruck nachgeschlagen und
    genannt (nur zur Diagnose, akzeptiert wird nichts).
    """
    text = str(fehler)
    if "CERTIFICATE_VERIFY_FAILED" not in text and "certificate verify failed" not in text:
        return fehler
    gefunden = ""
    try:
        gefunden = zertifikat_abfragen(peer["url"])["fingerprint"]
    except Exception:  # noqa: BLE001
        pass
    return FingerprintFehler(_zert_meldung(peer.get("fingerprint") or "?", gefunden))


# ─── Sync ───────────────────────────────────────────────────────────────────

def _fortschritt(peer_id: str, **werte) -> None:
    if peer_id in _laufend:
        _laufend[peer_id].update(werte)


def sync_status() -> dict:
    return {"running": list(_laufend.keys()), "progress": dict(_laufend)}


def sync_peer(peer_id: str, ausloeser: str = "manuell") -> dict:
    """Einen Standort synchronisieren (blockierend – in einem Thread aufrufen).

    Ablauf: Manifest holen → Differenz bilden → fehlende/geaenderte Dateien
    laden und pruefen → entfernt geloeschte lokal entfernen → Gruppen-Zuordnung
    setzen → Index nachziehen.
    """
    ok, grund = erlaubt()
    if not ok:
        return {"ok": False, "error": grund, "license": True}
    peer = get_peer(peer_id)
    if peer is None:
        return {"ok": False, "error": "Standort nicht gefunden."}
    if peer.get("state") != "active":
        return {"ok": False, "error": "Der Standort ist pausiert."}
    if not _sync_lock.acquire(blocking=False):
        return {"ok": False, "error": "Es läuft schon eine Synchronisation. Bitte kurz warten.",
                "busy": True}
    _laufend[peer_id] = {"phase": "manifest", "done": 0, "total": 0,
                         "started_at": _jetzt(), "trigger": ausloeser}
    try:
        bericht = _sync_intern(peer)
    except FingerprintFehler as e:
        bericht = {"ok": False, "error": str(e), "fingerprint": True}
    except Exception as e:  # noqa: BLE001
        bericht = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        _laufend.pop(peer_id, None)
        _sync_lock.release()
    # Ergebnis am Standort festhalten – auch den Fehlschlag. Ein Standort, der
    # seit Tagen nichts holt, muss das in der Oberflaeche zeigen.
    with _lock:
        for p in _laden()["peers"]:
            if p["id"] != peer_id:
                continue
            p["last_sync"] = {"ts": _jetzt(), "ok": bool(bericht.get("ok")),
                              "trigger": ausloeser,
                              "added": bericht.get("added", 0),
                              "updated": bericht.get("updated", 0),
                              "removed": bericht.get("removed", 0),
                              "bytes": bericht.get("bytes", 0),
                              "duration": round(_jetzt() - (bericht.get("_start") or _jetzt()), 1)}
            p["last_error"] = "" if bericht.get("ok") else str(bericht.get("error", ""))[:1000]
            if bericht.get("ok"):
                p["file_count"] = bericht.get("file_count", p.get("file_count", 0))
                p["total_bytes"] = bericht.get("total_bytes", p.get("total_bytes", 0))
                if bericht.get("remote_site"):
                    p["remote_site"] = bericht["remote_site"]
                if bericht.get("remote_label"):
                    p["remote_label"] = bericht["remote_label"]
            _speichern()
            break
    bericht.pop("_start", None)
    return bericht


def _sync_intern(peer: dict) -> dict:
    import httpx

    start = _jetzt()
    peer_id = peer["id"]
    basis = peer["url"]
    ziel_rel = _rel(peer["target_folder"])
    ziel = PROJECT_ROOT / ziel_rel
    kopf = {
        "X-Jarvis-Share-Token": peer.get("token", ""),
        "X-Jarvis-Site": site_name(),
        "User-Agent": "jarvis-kb-sync/1",
    }
    # Zertifikat binden, BEVOR das Token ueber die Leitung geht.
    peer = _pem_sicherstellen(peer)
    with httpx.Client(verify=_ssl_kontext(peer), timeout=HTTP_TIMEOUT,
                      follow_redirects=False, headers=kopf) as client:
        try:
            antwort = client.get(basis + "/api/knowledge/pull/manifest")
        except Exception as e:  # noqa: BLE001
            raise _zert_fehler_deuten(peer, e) from e
        if antwort.status_code == 403:
            raise RuntimeError("Freigabe entzogen oder Token ungültig – die lokale Kopie "
                               "bleibt unverändert erhalten.")
        if antwort.status_code == 404:
            raise RuntimeError("Der freigegebene Ordner existiert am anderen Standort nicht mehr.")
        if antwort.status_code != 200:
            raise RuntimeError(f"Gegenstelle antwortete mit HTTP {antwort.status_code}.")
        manifest = antwort.json()
        if manifest.get("schema") != "jarvis-kb-sync/v1":
            raise RuntimeError("Unerwartete Antwort – ist die Adresse wirklich ein Jarvis-Standort?")

        fern = {f["path"]: f for f in manifest.get("files", [])
                if isinstance(f, dict) and f.get("path")}
        gespeichert = peer.get("manifest") or {}

        # Differenz. Ein Eintrag gilt als unveraendert, wenn Hash UND die lokale
        # Datei mit passender Groesse vorhanden sind – sonst wird geladen. Ein
        # reiner Manifest-Vergleich ohne Blick auf die Platte wuerde eine von
        # Hand geloeschte Datei nie wiederherstellen.
        laden: list[dict] = []
        for rel, eintrag in fern.items():
            alt = gespeichert.get(rel) or {}
            lokal = ziel / rel
            passt = (alt.get("sha256") == eintrag.get("sha256"))
            if passt:
                try:
                    passt = lokal.is_file() and lokal.stat().st_size == int(eintrag.get("size", -1))
                except OSError:
                    passt = False
            if not passt:
                laden.append(eintrag)
        entfernen = [rel for rel in list(gespeichert.keys()) + _lokale_dateien(ziel)
                     if rel not in fern]
        entfernen = sorted(set(entfernen))

        _fortschritt(peer_id, phase="download", total=len(laden), done=0)
        ziel.mkdir(parents=True, exist_ok=True)
        neu = geaendert = 0
        bytes_geladen = 0
        fehler: list[str] = []
        for i, eintrag in enumerate(laden, 1):
            rel = eintrag["path"]
            _fortschritt(peer_id, done=i, current=rel)
            zielpfad = _sicheres_ziel(ziel, rel)
            if zielpfad is None:
                fehler.append(f"{rel}: unzulässiger Pfad, übersprungen")
                continue
            existierte = zielpfad.exists()
            try:
                geladen = _datei_holen(client, basis, rel, eintrag, zielpfad)
            except Exception as e:  # noqa: BLE001
                fehler.append(f"{rel}: {e}")
                continue
            bytes_geladen += geladen
            if existierte:
                geaendert += 1
            else:
                neu += 1

        # Entfernte Loeschungen nachziehen (der entfernte Stand gewinnt).
        _fortschritt(peer_id, phase="cleanup")
        weg = 0
        for rel in entfernen:
            pfad = _sicheres_ziel(ziel, rel, anlegen=False)
            if pfad is None or not pfad.exists():
                continue
            try:
                from backend.tools.knowledge import purge_file_index
                purge_file_index(pfad)
            except Exception:  # noqa: BLE001
                pass
            try:
                pfad.unlink()
                weg += 1
            except OSError as e:
                fehler.append(f"{rel}: nicht entfernt ({e})")
        _leere_ordner_entfernen(ziel)

    # Manifest fortschreiben – nur die Dateien, die lokal wirklich liegen.
    neues_manifest = {rel: e for rel, e in fern.items() if (ziel / rel).is_file()}
    with _lock:
        for p in _laden()["peers"]:
            if p["id"] == peer_id:
                p["manifest"] = neues_manifest
                _speichern()
                break

    # Lokale Einbettung in die Wissensverwaltung: Ordner registrieren, Gruppe
    # zuordnen, Index nachziehen.
    _fortschritt(peer_id, phase="index")
    ordner_neu = _ordner_registrieren(ziel_rel)
    zugeordnet = _gruppen_zuordnen(ziel_rel, neues_manifest.keys(), peer.get("group_id", ""))
    indiziert = _index_nachziehen()

    return {
        "ok": True, "_start": start,
        "added": neu, "updated": geaendert, "removed": weg,
        "bytes": bytes_geladen,
        "file_count": len(neues_manifest),
        "total_bytes": sum(int(e.get("size", 0) or 0) for e in neues_manifest.values()),
        "skipped_remote": int(manifest.get("skipped", 0) or 0),
        "remote_site": manifest.get("site", ""),
        "remote_label": manifest.get("label", ""),
        "folder": ziel_rel, "folder_registered": ordner_neu,
        "groups_assigned": zugeordnet, "indexed": indiziert,
        "errors": fehler[:50], "error_count": len(fehler),
    }


def _lokale_dateien(ziel: Path) -> list[str]:
    """Relative Pfade der Dateien, die lokal im Spiegel liegen."""
    if not ziel.is_dir():
        return []
    aus = []
    for root, dirs, fs in os.walk(ziel, onerror=lambda e: None):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in fs:
            if name.startswith("."):
                continue
            p = Path(root) / name
            try:
                aus.append(p.relative_to(ziel).as_posix())
            except ValueError:
                continue
    return aus


def _sicheres_ziel(wurzel: Path, rel: str, anlegen: bool = True) -> Path | None:
    """Zielpfad im Spiegel – oder None, wenn er ausbrechen wuerde.

    Der Pfad kommt aus dem Manifest einer FREMDEN Instanz. Er wird deshalb
    behandelt wie jede andere fremde Eingabe: keine absoluten Pfade, kein
    ``..``, keine Laufwerksangabe, und das aufgeloeste Ergebnis muss unter der
    Wurzel liegen. Ein vorhandener Symlink im Zielordner wird verworfen, nicht
    beschrieben – sonst schreibt der Sync durch ihn hindurch.
    """
    rel = (rel or "").strip().replace("\\", "/").lstrip("/")
    if not rel or "\x00" in rel:
        return None
    teile = [t for t in rel.split("/") if t not in ("", ".")]
    if not teile or any(t == ".." for t in teile) or ":" in teile[0]:
        return None
    if any(t.startswith(".") for t in teile):
        return None
    ziel = wurzel.joinpath(*teile)
    try:
        aufgeloest = ziel.resolve()
        aufgeloest.relative_to(wurzel.resolve())
    except (ValueError, OSError):
        return None
    if ziel.is_symlink():
        return None
    if ziel.suffix.lower() not in _endungen():
        return None
    if anlegen:
        try:
            ziel.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
    return ziel


def _datei_holen(client, basis: str, rel: str, eintrag: dict, ziel: Path) -> int:
    """Eine Datei laden, pruefen, dann erst an ihren Platz legen.

    Geschrieben wird ueber eine Nebendatei und ``os.replace``: bricht die
    Uebertragung ab, bleibt die alte Fassung stehen statt einer halben Datei,
    die der Indexer als Wissen einliest.
    """
    from urllib.parse import quote
    erwartet = str(eintrag.get("sha256") or "")
    groesse = int(eintrag.get("size", 0) or 0)
    tmp = ziel.with_name(ziel.name + ".kbsync.tmp")
    h = hashlib.sha256()
    geschrieben = 0
    try:
        with client.stream("GET", basis + "/api/knowledge/pull/file?path=" + quote(rel, safe="")) as r:
            if r.status_code == 403:
                raise RuntimeError("Freigabe entzogen oder Token ungültig")
            if r.status_code == 404:
                raise RuntimeError("Datei am anderen Standort nicht mehr vorhanden")
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}")
            with open(tmp, "wb") as f:
                for block in r.iter_bytes(1024 * 256):
                    geschrieben += len(block)
                    if geschrieben > MAX_DATEI_BYTES:
                        raise RuntimeError("Datei größer als erlaubt")
                    h.update(block)
                    f.write(block)
        if erwartet and h.hexdigest() != erwartet:
            raise RuntimeError("Prüfsumme weicht ab – Datei verworfen")
        if groesse and geschrieben != groesse:
            raise RuntimeError(f"Größe weicht ab ({geschrieben} statt {groesse}) – Datei verworfen")
        os.replace(tmp, ziel)
        try:
            mtime = float(eintrag.get("mtime") or 0)
            if mtime > 0:
                # mtime uebernehmen: der inkrementelle Reindex vergleicht sie.
                os.utime(ziel, (mtime, mtime))
        except OSError:
            pass
        return geschrieben
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def _leere_ordner_entfernen(wurzel: Path) -> None:
    """Leere Unterordner nach einer Loeschrunde abraeumen (die Wurzel bleibt)."""
    try:
        for root, dirs, fs in os.walk(wurzel, topdown=False, onerror=lambda e: None):
            p = Path(root)
            if p == wurzel:
                continue
            try:
                if not any(p.iterdir()):
                    p.rmdir()
            except OSError:
                pass
    except Exception:  # noqa: BLE001
        pass


def _ordner_registrieren(rel_ziel: str) -> bool:
    """Zielordner in die Wissensordner-Liste aufnehmen (idempotent).

    Geschrieben wird ueber ``config.save_skill_state`` – denselben Weg, den
    ``skills.manager.update_skill_config`` und die Ordner-Endpunkte nehmen. Der
    SkillManager wird bewusst NICHT importiert: er haengt an main.py, und ein
    Gegenimport waere zirkulaer.
    """
    try:
        from backend.config import config
        states = config.get_skill_states()
        state = states.get("knowledge", {})
        cfg = dict(state.get("config", {}))
        roh = cfg.get("folders") or "data/knowledge"
        liste = [f.strip() for f in str(roh).split(",") if f.strip()]
        if rel_ziel in liste:
            return False
        liste.append(rel_ziel)
        cfg["folders"] = ",".join(liste)
        state["config"] = cfg
        state.setdefault("enabled", True)
        config.save_skill_state("knowledge", state)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[KB-Sync] Ordner {rel_ziel} nicht registriert: {e}", flush=True)
        return False


def _gruppen_zuordnen(rel_ziel: str, rel_dateien, group_id: str) -> int:
    """Alle gespiegelten Dateien der gewaehlten Wissensgruppe zuordnen.

    Die Gruppen-Zuordnung des Gebers wird NICHT uebernommen – sie gilt in seiner
    Installation und haette hier keine Entsprechung. Ohne Gruppe passiert
    nichts: die Dateien sind dann "ungruppiert" und trotzdem durchsuchbar.

    WICHTIG – der Spiegel wird bewusst NICHT als *Speicherordner* der Gruppe
    eingetragen (``kg.add_folder_to_groups``), nur die einzelnen Dateien werden
    getaggt. Das Feld ``folders`` einer Gruppe ist die Liste der ABLAGEZIELE:
    stuende der Spiegel darin, boete /wissen ihn als Upload-Ziel an und
    ``web_extractor._target_dir_for_groups`` legte freigegebene Extrakte dort ab –
    beides wuerde der naechste Lauf loeschen. Fuer den Gruppenfilter der Suche
    zaehlen ausschliesslich die Zuordnungen je Datei, die Liste braucht es dafuer
    nicht.
    """
    if not group_id:
        return 0
    try:
        from backend import knowledge_groups as kg
        bekannt = {g["id"] for g in kg.list_groups().get("groups", [])}
        if group_id not in bekannt:
            print(f"[KB-Sync] Wissensgruppe '{group_id}' fehlt – Zuordnung uebersprungen",
                  flush=True)
            return 0
        n = 0
        for rel in rel_dateien:
            kg.set_assignment(f"{rel_ziel}/{rel}", [group_id])
            n += 1
        return n
    except Exception as e:  # noqa: BLE001
        print(f"[KB-Sync] Gruppen-Zuordnung fehlgeschlagen: {e}", flush=True)
        return 0


def _index_nachziehen() -> bool:
    """Index inkrementell ergaenzen.

    ``incremental=True`` ist Pflicht: ein voller Neuaufbau bettet die GANZE
    Wissensdatenbank neu ein (Minuten bis Stunden) und laesst waehrenddessen
    jede Suche ins Leere laufen – fuer ein paar neue Dateien.
    """
    try:
        from backend.tools.knowledge import force_reindex, invalidate_files_cache
        invalidate_files_cache()
        force_reindex(incremental=True)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[KB-Sync] Reindex fehlgeschlagen: {e}", flush=True)
        return False


# ─── Automatik ──────────────────────────────────────────────────────────────

def faellige_standorte(jetzt: float | None = None) -> list[str]:
    """Standorte, deren naechster Lauf faellig ist."""
    t = jetzt if jetzt is not None else _jetzt()
    aus = []
    with _lock:
        for p in _laden()["peers"]:
            naechst = naechster_lauf(p)
            if naechst is not None and naechst <= t:
                aus.append(p["id"])
    return aus


def automatik_lauf() -> dict:
    """Ein Durchgang der Automatik – vom Startup-Hook getaktet.

    Es laeuft hoechstens EIN Standort je Durchgang: mehrere Spiegel gleichzeitig
    zu ziehen und danach mehrfach zu indizieren waere teurer als eine Runde
    Warten.
    """
    ok, grund = erlaubt()
    if not ok:
        return {"ok": False, "skipped": "license", "error": grund}
    faellig = faellige_standorte()
    if not faellig:
        return {"ok": True, "synced": []}
    peer_id = faellig[0]
    bericht = sync_peer(peer_id, ausloeser="automatisch")
    return {"ok": True, "synced": [peer_id], "report": bericht}
