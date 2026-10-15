"""Broker-Policy: auditierbare Freigabeliste fuer Root-Operationen.

Jede Root-Operation wird beim ERSTEN Auftauchen als Eintrag registriert:
- Fest definierte System-Operationen (systemctl, VNC, Sandbox, ...) werden
  automatisch erlaubt (auto=True) – der Admin sieht sie in der Liste und kann
  sie jederzeit auf 'deny' setzen.
- Generische Root-Shell-Befehle (shell_root:<befehl>) starten als 'pending'
  und muessen von einem Admin explizit freigegeben werden.

Dateien (nur root beschreibbar – das Backend kann sie NICHT direkt aendern):
- /etc/jarvis/broker-policy.json     – Policy-Eintraege
- /var/log/jarvis-broker-audit.jsonl – Audit-Log (JSON-Lines)
"""

import json
import os
import threading
import time
from pathlib import Path

POLICY_FILE = Path(os.environ.get("JARVIS_BROKER_POLICY", "/etc/jarvis/broker-policy.json"))
AUDIT_FILE = Path(os.environ.get("JARVIS_BROKER_AUDIT", "/var/log/jarvis-broker-audit.jsonl"))

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


def _save(data: dict) -> None:
    """Atomar schreiben (temp + rename), Datei nur fuer root lesbar."""
    POLICY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = POLICY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    try:
        os.chmod(tmp, 0o600)
    except Exception:  # noqa: BLE001
        pass
    os.replace(tmp, POLICY_FILE)


def check(key: str, op: str, description: str, user: str,
          default_allow: bool) -> str:
    """Entscheidung fuer eine Operation abrufen; legt den Eintrag beim ersten
    Auftauchen an ('wenn sie auftauchen'). Rueckgabe: allow|deny|pending."""
    now = int(time.time())
    with _lock:
        try:
            data = _load()
        except PolicyUnlesbar as e:
            print("[Broker-Policy] " + MELDUNG_UNLESBAR % e, flush=True)
            return DENY
        entry = data["ops"].get(key)
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
                "count": 0,
                "last_used": 0,
            }
            data["ops"][key] = entry
        entry["count"] = int(entry.get("count", 0)) + 1
        entry["last_used"] = now
        if user and not entry.get("requested_by"):
            entry["requested_by"] = user
        _save(data)
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
        return dict(entry)


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
            return True
        return False


def list_ops() -> list[dict]:
    """Alle Eintraege, offene (pending) zuerst, dann nach letzter Nutzung."""
    with _lock:
        entries = list(_load()["ops"].values())
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
