"""Eigentuemer-Registry und Aufbewahrungsfrist fuer erzeugte Dokumente.

Dateien unter ``data/documents/`` werden ueber ``GET /api/documents/<cap>``
ausgeliefert. Der Capability-Name (``<32-Hex>__<Basis>.<ext>``) ist ein
uuid4-Geheimnis mit 122 Bit Entropie und damit nicht erratbar – aber bis
2026-07-28 war er der EINZIGE Schutz: keine Anmeldung, kein Bezug zum Ersteller,
kein Verfall, kein Aufraeumen. Wer den Link kannte (Browser-Verlauf, Proxy-Log,
weitergeleiteter Screenshot), kam dauerhaft an die Datei – und auf dem
Echt-System liegen dort Jira-Exporte mit Kundendaten.

Dieses Modul liefert die zwei fehlenden Stuecke:
  * ``register()`` / ``may_access()`` binden jede Datei an ihren Ersteller,
  * ``cleanup_old()`` begrenzt die Lebensdauer.
Die Anmeldepflicht selbst haengt am Endpunkt in ``main.py``
(``require_auth_or_query`` – Bearer-Header ODER ``?token=`` fuer ``<a download>``
und ``<img>``, die keine Header setzen koennen).

Bewusste Entscheidungen:
  * **Fail-closed:** ohne Registry-Eintrag ist eine Datei nur fuer Admins
    erreichbar. Betrifft Altbestand aus der Zeit ohne Registry – dessen
    Eigentuemer ist nicht rekonstruierbar, und Raten waere schlechter als
    Verweigern. Die Aufbewahrungsfrist raeumt ihn ohnehin ab.
  * **Erster Schreiber gewinnt:** ``register()`` ueberschreibt einen bestehenden
    Eintrag NICHT. Sonst koennte ein Nutzer eine fremde Capability-URL in seine
    Antwort schreiben (oder ein Prompt-Injection-Text das tun) und die Datei so
    auf sich umschreiben.
  * **Nur Capability-Dateien** werden abgeraeumt. Roh-Dateien im selben Ordner
    (Skill-Exporte, hochgeladene Anhaenge) sind ueber den Endpunkt gar nicht
    erreichbar und werden von Tools ueber ihren Namen weiterbenutzt – ein
    Loeschen wuerde laufende Arbeitsabläufe brechen.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent.parent / "data" / "documents"
_REGISTRY = DOCS_DIR / ".owners.json"

# Capability-Schema – identisch zur Pruefung im Endpunkt. Der Punkt fuehrt kein
# Pfadtrenner-Risiko ein: geprueft wird immer mit fullmatch gegen den reinen Namen.
_CAP_RE = re.compile(r"[0-9a-f]{32}__[A-Za-z0-9_\-]+\.[A-Za-z0-9]{1,8}")

_lock = threading.Lock()


def retention_days() -> int:
    """Vorhaltezeit in Tagen aus der Konfiguration; 0 = dauerhaft behalten.

    Bewusst eine FUNKTION und keine Modulkonstante: der Wert ist unter
    *Einstellungen → KI & System → Tuning* aenderbar und muss ohne Neustart
    greifen. Eine beim Import gelesene Konstante haette die Einstellung bis zum
    naechsten Dienststart wirkungslos gemacht.
    """
    try:
        from backend.config import config
        return max(0, int(config.DOCS_RETENTION_DAYS))
    except Exception:
        return 30


def _log(msg: str) -> None:
    print(f"[documents] {msg}", flush=True)


def _norm(username: str) -> str:
    """Normalisiert einen Benutzernamen fuer den Vergleich.

    Gleiche Regel wie ``JarvisAgent._run_key``: ``nexus\\andreas.bender`` und
    ``andreas.bender@nexus-ag.de`` muessen denselben Schluessel ergeben, sonst
    haengt der Zugriff daran, wie sich der Nutzer angemeldet hat.
    """
    return (username or "").split("@")[0].split("\\")[-1].strip().lower()


def is_capability(name: str) -> bool:
    return bool(_CAP_RE.fullmatch(name or ""))


def _load() -> dict:
    try:
        with open(_REGISTRY, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        # Kaputte Registry darf den Betrieb nicht anhalten – sie wirkt dann wie
        # eine leere: alles ist admin-only, bis wieder registriert wird.
        _log(f"Registry nicht lesbar ({e}) – behandle als leer")
        return {}


def _save(data: dict) -> bool:
    try:
        DOCS_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _REGISTRY.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, _REGISTRY)   # atomar – nie eine halb geschriebene Registry
        try:
            os.chmod(_REGISTRY, 0o600)
        except Exception:
            pass
        return True
    except Exception as e:
        _log(f"Registry nicht schreibbar: {e}")
        return False


def register(fname: str, username: str) -> bool:
    """Vermerkt den Ersteller einer Capability-Datei. Bestehende Eintraege
    bleiben unangetastet (siehe Modul-Docstring: erster Schreiber gewinnt)."""
    fname = os.path.basename(fname or "")
    if not is_capability(fname):
        return False
    user = _norm(username)
    if not user:
        # Ohne Benutzer kein Eintrag -> Datei bleibt admin-only. Besser als ein
        # Eintrag auf einen Platzhalter, den dann jeder Anonyme traefe.
        _log(f"kein Benutzer zum Registrieren von {fname} – bleibt admin-only")
        return False
    with _lock:
        data = _load()
        if fname in data:
            return True
        data[fname] = {"user": user, "ts": int(time.time())}
        return _save(data)


def register_upload(fname: str, username: str) -> bool:
    """Vermerkt den Eigentuemer einer ROH-Datei (hochgeladener Chat-Anhang).

    Getrennt von ``register()``, weil dort der Capability-Name die Schranke IST:
    ``register()`` wird mit Namen aufgerufen, die aus LLM-Text stammen, und darf
    deshalb nur unerratbare Capability-Namen annehmen. Diese Funktion wird
    ausschliesslich aus Server-Code mit einem echten Dateinamen aufgerufen.

    Ohne diesen Eintrag waere der eigene Anhang nach der Eigentuemer-Schranke
    (2026-07-28) fuer den Hochladenden selbst unsichtbar – die Werkzeuge
    sprechen Anhaenge ueber ihren Namen an.
    """
    fname = os.path.basename(fname or "")
    if not fname or fname.startswith("."):
        return False
    user = _norm(username)
    if not user:
        _log(f"kein Benutzer zum Registrieren von {fname} – bleibt admin-only")
        return False
    with _lock:
        data = _load()
        if fname in data:
            return True
        data[fname] = {"user": user, "ts": int(time.time()), "kind": "upload"}
        return _save(data)


def owner_of(fname: str) -> str | None:
    entry = _load().get(os.path.basename(fname or ""))
    if isinstance(entry, dict):
        return entry.get("user") or None
    return entry if isinstance(entry, str) else None   # tolerant fuer Altformat


def may_access(fname: str, username: str, is_admin: bool = False) -> bool:
    """Darf ``username`` diese Datei laden? Admins immer, sonst nur der Ersteller."""
    if is_admin:
        return True
    owner = owner_of(fname)
    if not owner:
        return False
    return owner == _norm(username)


def cleanup_old(days: int | None = None) -> tuple[int, int]:
    """Loescht Capability-Dateien, die aelter als die Aufbewahrungsfrist sind.

    Gibt ``(Anzahl, Bytes)`` zurueck. Raeumt zugleich Registry-Eintraege ohne
    Datei ab, damit die Registry nicht unbegrenzt waechst.
    """
    days = retention_days() if days is None else days
    removed, freed = 0, 0
    if not DOCS_DIR.is_dir():
        return 0, 0
    cutoff = time.time() - days * 86400 if days > 0 else None
    with _lock:
        data = _load()
        changed = False
        for p in list(DOCS_DIR.iterdir()):
            try:
                if not p.is_file() or not is_capability(p.name):
                    continue
                if cutoff is None or p.stat().st_mtime >= cutoff:
                    continue
                size = p.stat().st_size
                p.unlink()
                removed += 1
                freed += size
                if data.pop(p.name, None) is not None:
                    changed = True
            except Exception as e:
                _log(f"Loeschen fehlgeschlagen fuer {p.name}: {e}")
        for fname in [k for k in data if not (DOCS_DIR / k).is_file()]:
            data.pop(fname, None)
            changed = True
        if changed:
            _save(data)
    if removed:
        _log(f"Aufbewahrungsfrist {days} Tage: {removed} Datei(en) entfernt, "
             f"{freed / 1024 / 1024:.1f} MB frei")
    return removed, freed


def stats() -> dict:
    """Kennzahlen fuer Diagnose/Anzeige."""
    total = owned = 0
    if DOCS_DIR.is_dir():
        data = _load()
        for p in DOCS_DIR.iterdir():
            try:
                if p.is_file() and is_capability(p.name):
                    total += 1
                    if p.name in data:
                        owned += 1
            except Exception:
                continue
    return {"capability_files": total, "with_owner": owned,
            "orphaned": total - owned, "retention_days": retention_days()}
