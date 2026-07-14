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


def _load() -> dict:
    try:
        if POLICY_FILE.exists():
            data = json.loads(POLICY_FILE.read_text())
            if isinstance(data, dict) and isinstance(data.get("ops"), dict):
                return data
    except Exception as e:  # noqa: BLE001
        print(f"[Broker-Policy] Ladefehler: {e}", flush=True)
    return {"version": 1, "ops": {}}


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
        data = _load()
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
          duration_ms=None, detail: str = "", context: str = "") -> None:
    """Audit-Eintrag anhaengen (JSON-Lines, root-eigene Datei).

    context: kurzer, rein informativer Ausloeser-Kontext (z.B. Agent-Task-Auszug),
    NUR fuers Protokoll – fliesst nie in Policy-Entscheidungen oder Befehle ein."""
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
    }
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
    """Letzte n Audit-Eintraege (neueste zuletzt)."""
    try:
        if not AUDIT_FILE.exists():
            return []
        lines = AUDIT_FILE.read_text().splitlines()[-max(1, min(n, 1000)):]
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except Exception:  # noqa: BLE001
                continue
        return out
    except Exception:  # noqa: BLE001
        return []
