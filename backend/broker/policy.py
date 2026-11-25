"""Broker-Policy: auditierbare Freigabeliste fuer Root-Operationen.

Jede Root-Operation wird beim ERSTEN Auftauchen als Eintrag registriert:
- Fest definierte System-Operationen (systemctl, VNC, Sandbox, ...) werden
  automatisch erlaubt (auto=True) – der Admin sieht sie in der Liste und kann
  sie jederzeit auf 'deny' setzen.
- Generische Root-Shell-Befehle (shell_root:<befehl>) starten als 'pending'
  und muessen von einem Admin explizit freigegeben werden.

Dateien (nur root beschreibbar – das Backend kann sie NICHT direkt aendern):
- /etc/jarvis/broker-policy.json          – Policy-Eintraege (NUR Entscheidungen)
- /var/lib/jarvis-broker/zaehler.json     – Nutzungszaehler (count, last_used)
- /var/log/jarvis-broker-audit.jsonl      – Audit-Log (JSON-Lines)

Warum zwei Dateien (Haertung B7, 18.11.2026): solange count/last_used in der
Policy-Datei standen, wurde sie im Betrieb alle ZAEHLER_FLUSH_S Sekunden neu
geschrieben. AIDE meldete die Freigabeliste deshalb bei JEDER Pruefung als
geaendert – ein deny->allow von Hand waere im Dauerrauschen untergegangen.
Jetzt aendert sich die Policy-Datei nur noch, wenn ein Eintrag entsteht, eine
Entscheidung faellt oder ein Eintrag entfernt wird.
"""

import json
import os
import threading
import time
from pathlib import Path

try:
    from backend import eigene_dateien
except ImportError:  # pragma: no cover - Waechter laden das Modul einzeln
    eigene_dateien = None

POLICY_FILE = Path(os.environ.get("JARVIS_BROKER_POLICY", "/etc/jarvis/broker-policy.json"))
AUDIT_FILE = Path(os.environ.get("JARVIS_BROKER_AUDIT", "/var/log/jarvis-broker-audit.jsonl"))
# Zaehlerdatei: ausdruecklich gesetzt, sonst NEBEN einer umgelenkten Policy-Datei
# (Tests setzen nur JARVIS_BROKER_POLICY und duerfen nie nach /var/lib schreiben),
# sonst im root-eigenen Broker-Verzeichnis (0700, existiert seit der Installation).
ZAEHLER_FILE = Path(
    os.environ.get("JARVIS_BROKER_ZAEHLER")
    or (str(POLICY_FILE.with_name("broker-zaehler.json")) if os.environ.get("JARVIS_BROKER_POLICY")
        else "/var/lib/jarvis-broker/zaehler.json"))
# Felder, die in die Zaehlerdatei gehoeren und in der Policy-Datei nichts verloren haben
ZAEHLER_FELDER = ("count", "last_used")

# Entscheidungen
ALLOW = "allow"
DENY = "deny"
PENDING = "pending"

_lock = threading.Lock()


class PolicyUnlesbar(Exception):
    """Die Policy-Datei existiert, ist aber nicht lesbar oder kaputt."""


MELDUNG_UNLESBAR = ("Broker-Policy unlesbar (%s) – alle Root-Operationen werden "
                    "abgewiesen, bis die Datei repariert ist")


def _load() -> dict:
    """Policy laden. FAIL-CLOSED (Code-Review 2026-10-07): bis dahin galt eine
    kaputte Datei als LEER – das naechste ``check()`` legte sie neu an, und
    jedes Admin-``deny`` auf einer automatischen Op wurde wieder ``allow``.
    Jetzt wirft eine vorhandene, aber unlesbare Datei; geschrieben wird dann
    nichts, die Datei bleibt fuer die Reparatur stehen."""
    if not POLICY_FILE.exists():
        return {"version": 1, "ops": {}}
    try:
        data = json.loads(POLICY_FILE.read_text())
    except Exception as e:  # noqa: BLE001
        raise PolicyUnlesbar(str(e)[:200]) from e
    if not (isinstance(data, dict) and isinstance(data.get("ops"), dict)):
        raise PolicyUnlesbar("kein gueltiger Aufbau")
    return data


def _atomar_schreiben(pfad: Path, data: dict) -> None:
    """Atomar schreiben (temp + rename), Datei von Anfang an nur fuer root (0600).

    Der Uebergang wird fuer den AIDE-Abgleich vermerkt (backend/eigene_dateien.py):
    eine vom Broker geschriebene Policy ist sonst jede Nacht "nicht erklaert"."""
    if eigene_dateien is None:
        _atomar_schreiben_roh(pfad, data)
        return
    with eigene_dateien.schreibt(pfad):
        _atomar_schreiben_roh(pfad, data)


def _atomar_schreiben_roh(pfad: Path, data: dict) -> None:
    pfad.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = pfad.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)      # eine liegengebliebene .tmp mit anderen Rechten
        with os.fdopen(fd, "w") as f:
            fd = -1
            f.write(json.dumps(data, indent=2, ensure_ascii=False))
    finally:
        if fd >= 0:
            os.close(fd)
    os.replace(tmp, pfad)


def _save(data: dict) -> None:
    """Policy-Datei schreiben. Stehen darin noch Zaehler aus der Zeit vor der
    Trennung (Altbestand), wandern sie ZUERST in die Zaehlerdatei und werden erst
    dann aus der Policy entfernt – gelingt das nicht, bleiben sie stehen (kein
    Verlust). Das ist die einzige Stelle, an der der Altbestand bereinigt wird:
    nur fuer die Migration wird die Policy-Datei NIE geschrieben."""
    if any(f in e for e in data["ops"].values() for f in ZAEHLER_FELDER):
        if _zaehler_flushen(data):
            for e in data["ops"].values():
                for f in ZAEHLER_FELDER:
                    e.pop(f, None)
    _atomar_schreiben(POLICY_FILE, data)
    _cache_setzen(data)


# ── Zaehler gebuendelt schreiben (Code-Review 2026-10-18) ──────────────────
# Bis dahin las und schrieb check() bei JEDER Op die ganze Datei in /etc neu
# (nur um count/last_used zu erhoehen) – je Shell-Befehl ein Voll-Rewrite unter
# globalem Lock, O(Eintraege). Jetzt: Lesen ueber einen Zwischenspeicher, der
# an mtime+Groesse haengt (eine Aenderung von Hand wird gesehen); Zaehler
# sammeln sich im Speicher und gehen hoechstens alle ZAEHLER_FLUSH_S Sekunden
# auf die Platte – seit 18.11.2026 in die eigene ZAEHLER_FILE, nicht mehr in
# die Policy-Datei. Ein NEUER Eintrag und jede Entscheidung werden sofort
# geschrieben – nur die Statistik darf hinterherhinken.
ZAEHLER_FLUSH_S = 30
# Deckel fuer OFFENE Eintraege: eine Prompt-Injection-Schleife konnte sonst
# tausende 'pending'-Eintraege erzeugen und die Freigabeliste unbrauchbar
# machen. Ueber dem Deckel wird nichts mehr angelegt – die Op laeuft nicht
# (Ergebnis pending), und die Ablehnung steht im Journal.
PENDING_MAX = 500
_cache: dict = {"stempel": None, "daten": None}
_offen: dict = {}            # key -> [anzahl, letzter_zeitpunkt]
_letzter_flush = 0.0


def _stempel():
    try:
        st = POLICY_FILE.stat()
        return (st.st_mtime_ns, st.st_size, st.st_ino)
    except FileNotFoundError:
        return None


def _cache_setzen(data: dict) -> None:
    _cache["daten"] = data
    _cache["stempel"] = _stempel()


def _load_cached() -> dict:
    """Wie ``_load``, aber ohne Neulesen, solange sich die Datei nicht geaendert hat."""
    stempel = _stempel()
    if _cache["daten"] is not None and stempel is not None and stempel == _cache["stempel"]:
        return _cache["daten"]
    data = _load()
    _cache["daten"], _cache["stempel"] = data, stempel
    return data


def _zahl(wert) -> int:
    try:
        return int(wert or 0)
    except (TypeError, ValueError):
        return 0


def _zaehler_lesen() -> dict:
    """Zaehlerdatei lesen: key -> {"count", "last_used"}. Bewusst OHNE
    Zwischenspeicher – sie ist klein, wird hoechstens alle ZAEHLER_FLUSH_S
    Sekunden gelesen, und ``jarvis-broker-admin`` (eigener Prozess) schreibt sie
    beim Entfernen mit. Fehlt oder ist sie kaputt, gilt sie als LEER: Zaehler sind
    Statistik, keine Entscheidung – anders als bei der Policy wird hier nichts
    abgewiesen (der Altbestand in der Policy-Datei springt dann als Basis ein)."""
    try:
        roh = json.loads(ZAEHLER_FILE.read_text())
    except FileNotFoundError:
        return {}
    except Exception as e:  # noqa: BLE001
        print(f"[Broker-Policy] Zaehlerdatei unlesbar ({str(e)[:120]}) – zaehle neu", flush=True)
        return {}
    ops = roh.get("ops") if isinstance(roh, dict) else None
    if not isinstance(ops, dict):
        return {}
    return {k: {"count": _zahl(v.get("count")), "last_used": _zahl(v.get("last_used"))}
            for k, v in ops.items() if isinstance(v, dict)}


def _zaehler_von(key: str, entry: dict, bestand: dict) -> dict:
    """Wirksame Zaehler eines Eintrags: Zaehlerdatei, sonst der Altbestand aus der
    Policy-Datei (MIGRATION BEIM LESEN), dazu das noch nicht Geschriebene."""
    basis = bestand.get(key)
    if basis is None:
        basis = {"count": _zahl(entry.get("count")), "last_used": _zahl(entry.get("last_used"))}
    anzahl, zuletzt = _offen.get(key, (0, 0))
    return {"count": basis["count"] + anzahl, "last_used": max(basis["last_used"], zuletzt)}


def _mit_zaehler(key: str, entry: dict, bestand: dict) -> dict:
    """Kopie eines Eintrags mit count/last_used – so sehen ALLE Leser (Admin-
    Konsole, Oberflaeche ueber broker.policy_list) dieselbe Form wie frueher."""
    return {**entry, **_zaehler_von(key, entry, bestand)}


def _zaehler_flushen(data: dict) -> bool:
    """Zaehlerdatei neu schreiben (nur Eintraege, die es in der Policy gibt).
    Fehlschlag (Platte, Rechte) wird gemeldet und laesst ``_offen`` stehen –
    eine Op wird daran nie abgewiesen. Rueckgabe: geschrieben?"""
    bestand = _zaehler_lesen()
    neu = {k: _zaehler_von(k, e, bestand) for k, e in data["ops"].items()}
    try:
        _atomar_schreiben(ZAEHLER_FILE, {"version": 1, "ops": neu})
    except Exception as e:  # noqa: BLE001
        print(f"[Broker-Policy] Zaehler nicht geschrieben: {str(e)[:160]}", flush=True)
        return False
    _offen.clear()
    return True


def flush() -> None:
    """Gesammelte Zaehler schreiben (Broker-Ende, Tests)."""
    global _letzter_flush
    with _lock:
        if not _offen:
            return
        try:
            data = _load()
        except PolicyUnlesbar:
            return
        _zaehler_flushen(data)
        _letzter_flush = time.monotonic()


def check(key: str, op: str, description: str, user: str,
          default_allow: bool) -> str:
    """Entscheidung fuer eine Operation abrufen; legt den Eintrag beim ersten
    Auftauchen an ('wenn sie auftauchen'). Rueckgabe: allow|deny|pending."""
    global _letzter_flush
    now = int(time.time())
    with _lock:
        try:
            data = _load_cached()
        except PolicyUnlesbar as e:
            print("[Broker-Policy] " + MELDUNG_UNLESBAR % e, flush=True)
            return DENY
        entry = data["ops"].get(key)
        if entry is not None:
            z = _offen.setdefault(key, [0, 0])
            z[0] += 1
            z[1] = now
            if user and not entry.get("requested_by"):
                # Einmal je Eintrag (ein System-Eintrag ohne Anforderer bekommt
                # seinen ersten) – gehoert zum Anlegen, kein Dauerschreiber.
                entry["requested_by"] = user
                _save(data)
            elif time.monotonic() - _letzter_flush >= ZAEHLER_FLUSH_S:
                _zaehler_flushen(data)
                _letzter_flush = time.monotonic()
            return entry.get("decision", PENDING)
        if not default_allow:
            offen = sum(1 for e in data["ops"].values() if e.get("decision") == PENDING)
            if offen >= PENDING_MAX:
                print(f"[Broker-Policy] {offen} offene Freigaben – neuer Eintrag NICHT angelegt "
                      f"(Deckel {PENDING_MAX}): {key[:120]}", flush=True)
                return PENDING
        if entry is None:
            entry = {
                "key": key,
                "op": op,
                "description": (description or "")[:500],
                "decision": ALLOW if default_allow else PENDING,
                "auto": bool(default_allow),
                "first_seen": now,
                "requested_by": user or "",
                "decided_by": "auto" if default_allow else "",
                "decided_at": now if default_allow else 0,
            }
            data["ops"][key] = entry
        _offen[key] = [1, now]
        _save(data)
        _zaehler_flushen(data)
        _letzter_flush = time.monotonic()
        return entry.get("decision", PENDING)


def decide(key: str, decision: str, by: str) -> dict | None:
    """Admin-Entscheidung setzen (allow/deny/pending). None wenn Key unbekannt."""
    if decision not in (ALLOW, DENY, PENDING):
        return None
    with _lock:
        data = _load()
        entry = data["ops"].get(key)
        if entry is None:
            return None
        entry["decision"] = decision
        entry["auto"] = False
        entry["decided_by"] = by or ""
        entry["decided_at"] = int(time.time())
        _save(data)
        return _mit_zaehler(key, entry, _zaehler_lesen())


def herabstufen(ops_ohne_automatik: set[str]) -> list[str]:
    """Automatisch erlaubte Eintraege dieser Ops auf 'pending' zuruecksetzen.

    Noetig, sobald eine Op ihr ``default_allow`` verliert (K2, 2026-09-29:
    ``broker_teardown``): ``check()`` legt einen Eintrag nur beim ERSTEN
    Auftauchen an. Ein bestehender "auto/allow"-Eintrag bliebe sonst fuer immer
    erlaubt, und die Aenderung an der Registry waere auf jedem Bestandssystem
    wirkungslos. Eine bewusste Admin-Entscheidung (auto=False) bleibt stehen.
    """
    geaendert = []
    with _lock:
        try:
            data = _load()
        except PolicyUnlesbar as e:
            # Beim Broker-Start: nicht abstuerzen, nichts schreiben – check()
            # weist ohnehin alles ab, solange die Datei kaputt ist.
            print("[Broker-Policy] " + MELDUNG_UNLESBAR % e, flush=True)
            return []
        for key, entry in data["ops"].items():
            if entry.get("op") in ops_ohne_automatik and entry.get("auto") \
                    and entry.get("decision") == ALLOW:
                entry["decision"] = PENDING
                entry["auto"] = False
                entry["decided_by"] = "Herabstufung (Freigabe erforderlich)"
                entry["decided_at"] = int(time.time())
                geaendert.append(key)
        if geaendert:
            _save(data)
    return geaendert


def remove(key: str) -> bool:
    """Eintrag loeschen (taucht beim naechsten Aufruf ggf. neu auf)."""
    with _lock:
        data = _load()
        if key in data["ops"]:
            del data["ops"][key]
            _save(data)
            _offen.pop(key, None)
            _zaehler_flushen(data)   # sonst erbte ein neu auftauchender Eintrag den alten Stand
            return True
        return False


def list_ops() -> list[dict]:
    """Alle Eintraege, offene (pending) zuerst, dann nach letzter Nutzung."""
    with _lock:
        data = _load()
        bestand = _zaehler_lesen()
        entries = [_mit_zaehler(k, e, bestand) for k, e in data["ops"].items()]
    order = {PENDING: 0, DENY: 1, ALLOW: 2}
    entries.sort(key=lambda e: (order.get(e.get("decision"), 3),
                                -int(e.get("last_used", 0))))
    return entries


def audit(user: str, op: str, key: str, decision: str, rc=None,
          duration_ms=None, detail: str = "", context: str = "",
          info: str = "", peer: str = "") -> None:
    """Audit-Eintrag anhaengen (JSON-Lines, root-eigene Datei).

    context: kurzer, rein informativer Ausloeser-Kontext (z.B. Agent-Task-Auszug),
    NUR fuers Protokoll – fliesst nie in Policy-Entscheidungen oder Befehle ein.
    info: konkrete (maskierte) Argumente der Ausfuehrung in Klartext – macht
    die 'Beispiele' in der Admin-UI aussagekraeftig."""
    rec = {
        "ts": int(time.time()),
        "user": user or "",
        "op": op,
        "key": key,
        "decision": decision,
        "rc": rc,
        "duration_ms": duration_ms,
        "detail": (detail or "")[:300],
        "context": (context or "")[:300],
        "info": (info or "")[:300],
    }
    if peer:
        # Vom KERNEL festgestellter Aufrufer (SO_PEERCRED) – im Gegensatz zu
        # `user`, das der Aufrufer selbst angibt.
        rec["peer"] = str(peer)[:80]
    try:
        AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_FILE, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        try:
            os.chmod(AUDIT_FILE, 0o600)
        except Exception:  # noqa: BLE001
            pass
    except Exception as e:  # noqa: BLE001
        print(f"[Broker-Audit] Schreibfehler: {e}", flush=True)


def audit_tail(n: int = 100) -> list[dict]:
    """Letzte n Audit-Eintraege (neueste zuletzt).

    Seit der woechentlichen Rotation (BSI M2, logrotate mit delaycompress) steht
    der Anfang der Woche in ``<datei>.1`` – ist die aktuelle Datei kuerzer als
    n, wird von dort aufgefuellt. Sonst zeigte die Oberflaeche montags frueh
    ein fast leeres Audit, obwohl nichts geloescht ist.
    """
    try:
        n = max(1, min(n, 1000))
        lines = AUDIT_FILE.read_text().splitlines() if AUDIT_FILE.exists() else []
        vorher = AUDIT_FILE.with_name(AUDIT_FILE.name + ".1")
        if len(lines) < n and vorher.exists():
            lines = vorher.read_text().splitlines() + lines
        lines = lines[-n:]
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except Exception:  # noqa: BLE001
                continue
        return out
    except Exception:  # noqa: BLE001
        return []
