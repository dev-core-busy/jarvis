"""Sicherheitsschicht – Erkennung von Jailbreak-/Prompt-Injection-Versuchen.

Bei Erkennung wird der betroffene Account SOFORT gesperrt. Gesperrte Accounts
duerfen sich noch anmelden (um den Hinweis + das Protokoll der verdaechtigen
Aktivitaeten zu sehen), sonst nichts. NUR ein lokaler Benutzer (ALLOWED_USERS)
kann wieder freischalten.

Konfiguration (settings.json via config.save_setting / get_setting):
  security_guard_enabled    – Master-Schalter (Default True)
  security_guard_heuristic  – Muster-Erkennung aktiv (Default True)
  security_guard_llm        – LLM-Klassifikator aktiv (Default True)

Hybrid-Logik:
  beide an  : Heuristik markiert einen Verdacht -> LLM bestaetigt -> Sperre
  nur Heur. : Heuristik-Treffer -> Sperre
  nur LLM   : LLM klassifiziert jede Eingabe -> Sperre bei Verdikt "jailbreak"
  beide aus : keine Erkennung (auch bei aktivem Master-Schalter)

Der LLM-Klassifikator wird per ``set_classifier()`` injiziert (vermeidet einen
Import-Zyklus mit main.py / llm.py). Faellt er aus, wird NICHT gesperrt
(fail-open) – ein Ausfall des Klassifikators darf keine Nutzer aussperren.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from backend.config import config

_STATE_FILE = Path(__file__).parent.parent / "data" / "security_state.json"
_lock = threading.RLock()

# ── Muster bekannter Jailbreak-/Prompt-Injection-Versuche ───────────────────
# Bewusst eher breit gefasst: im Hybrid-Default bestaetigt der LLM jeden Treffer,
# d.h. Fehlalarme der Heuristik werden abgefangen. Im reinen Heuristik-Modus
# greifen sie direkt.
_PATTERN_DEFS = [
    (r"ignore\s+(?:all|any|the|your|previous|prior|above|earlier)\s+(?:of\s+)?(?:previous\s+|prior\s+|above\s+)?(?:instructions?|prompts?|rules?|directives?|guidelines?)",
     "ignore-instructions"),
    (r"disregard\s+(?:all|any|the|your|previous|prior|above|everything).{0,40}?(?:instructions?|prompt|rules?|guidelines?)",
     "disregard-instructions"),
    (r"forget\s+(?:everything|all|your|the)\s+(?:previous\s+)?(?:instructions?|rules?|you were told)",
     "forget-instructions"),
    (r"\bD\.?A\.?N\.?\b.{0,25}(?:mode|jailbreak|prompt)|do\s+anything\s+now",
     "dan"),
    (r"(?:developer|dev)\s+mode\s+(?:enabled|on|activated)|enable\s+developer\s+mode",
     "developer-mode"),
    (r"(?:reveal|show|print|repeat|leak|expose|tell\s+me|give\s+me|what\s+(?:is|are))\b.{0,40}?(?:system\s*prompt|your\s+(?:initial\s+)?(?:prompt|instructions)|the\s+(?:prompt|instructions)\s+above|your\s+rules)",
     "reveal-system-prompt"),
    (r"you\s+are\s+(?:now\s+)?(?:an?\s+)?(?:unrestricted|unfiltered|uncensored|amoral|unethical|jailbroken)",
     "unrestricted-persona"),
    (r"pretend\s+(?:you\s+are|to\s+be|that\s+you).{0,50}?(?:no\s+(?:rules?|restrictions?|filters?|limits?)|unrestricted|uncensored|evil)",
     "pretend-unrestricted"),
    (r"act\s+as\s+(?:if\s+)?(?:an?\s+)?(?:unrestricted|uncensored|amoral|evil|jailbroken|dan)\b",
     "act-as-unrestricted"),
    (r"(?:bypass|disable|turn\s+off|switch\s+off|ignore|circumvent|override|remove)\b.{0,30}?(?:safety|guardrails?|filters?|content\s+(?:policy|policies|filter)|restrictions?|moderation|safeguards?)",
     "bypass-safety"),
    (r"\bjailbreak(?:ing|s|ed)?\b",
     "jailbreak-keyword"),
    (r"without\s+(?:any\s+)?(?:rules?|restrictions?|filters?|censorship|moral|ethics|limitations?)",
     "without-restrictions"),
    (r"(?:new|updated|revised)\s+(?:instructions?|rules?|system\s+prompt)\s*:\s*",
     "prompt-injection-override"),
    (r"\bSTOP\b.{0,15}\b(?:you\s+are|your\s+new|now\s+you)\b|^\s*system\s*[:>]\s*",
     "role-injection"),
]
_PATTERNS = [(re.compile(rx, re.IGNORECASE | re.DOTALL), name) for rx, name in _PATTERN_DEFS]

# Injizierter LLM-Klassifikator: async def fn(text:str) -> bool
_classifier = None


def set_classifier(fn):
    """Registriert die async LLM-Klassifikator-Funktion (aus main.py)."""
    global _classifier
    _classifier = fn


# ── Konfiguration ───────────────────────────────────────────────────────────
def _as_bool(v, default: bool) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def get_config() -> dict:
    return {
        "enabled": _as_bool(config.get_setting("security_guard_enabled", None), True),
        "heuristic": _as_bool(config.get_setting("security_guard_heuristic", None), True),
        "llm": _as_bool(config.get_setting("security_guard_llm", None), True),
    }


def set_config(enabled=None, heuristic=None, llm=None) -> dict:
    if enabled is not None:
        config.save_setting("security_guard_enabled", bool(enabled))
    if heuristic is not None:
        config.save_setting("security_guard_heuristic", bool(heuristic))
    if llm is not None:
        config.save_setting("security_guard_llm", bool(llm))
    return get_config()


# ── Zustands-Persistenz (gesperrte Accounts + Vorfaelle) ─────────────────────
def _load() -> dict:
    try:
        if _STATE_FILE.exists():
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"blocked": {}}


def _save(state: dict):
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                               encoding="utf-8")
    except Exception as e:
        print(f"[SecurityGuard] State speichern fehlgeschlagen: {e}", flush=True)


def is_blocked(user: str) -> bool:
    if not user:
        return False
    with _lock:
        return user in _load().get("blocked", {})


def get_block(user: str):
    """Sperr-Info eines Benutzers (inkl. Vorfaelle) oder None."""
    if not user:
        return None
    with _lock:
        return _load().get("blocked", {}).get(user)


def list_blocked() -> list:
    """Alle gesperrten Accounts (ohne die vollstaendige Vorfallsliste)."""
    with _lock:
        blocked = _load().get("blocked", {})
    out = []
    for user, info in blocked.items():
        out.append({
            "user": user,
            "reason": info.get("reason", ""),
            "method": info.get("method", ""),
            "channel": info.get("channel", ""),
            "at": info.get("at", 0),
            "incident_count": len(info.get("incidents", [])),
        })
    out.sort(key=lambda x: x.get("at", 0), reverse=True)
    return out


def get_incidents(user: str) -> list:
    info = get_block(user)
    return list(info.get("incidents", [])) if info else []


def unblock(user: str) -> bool:
    """Hebt die Sperre auf. True, wenn der Benutzer gesperrt war."""
    with _lock:
        state = _load()
        if user in state.get("blocked", {}):
            state["blocked"].pop(user, None)
            _save(state)
            print(f"[SecurityGuard] Account freigeschaltet: {user}", flush=True)
            return True
    return False


def _record(user: str, channel: str, method: str, pattern: str, text: str) -> dict:
    """Protokolliert einen Vorfall und sperrt den Account (falls nicht schon)."""
    incident = {
        "ts": int(time.time()),
        "channel": channel,
        "method": method,
        "pattern": pattern,
        "snippet": (text or "")[:500],
    }
    with _lock:
        state = _load()
        blk = state.setdefault("blocked", {})
        if user in blk:
            blk[user].setdefault("incidents", []).append(incident)
        else:
            blk[user] = {
                "reason": pattern,
                "method": method,
                "channel": channel,
                "at": incident["ts"],
                "incidents": [incident],
            }
        _save(state)
    print(f"[SecurityGuard] VORFALL ({method}/{pattern}) – Account gesperrt: "
          f"{user} [{channel}]", flush=True)
    return incident


# ── Erkennung ───────────────────────────────────────────────────────────────
def heuristic_match(text: str):
    """Gibt den Namen des ersten passenden Musters zurueck, sonst None."""
    t = text or ""
    for rx, name in _PATTERNS:
        if rx.search(t):
            return name
    return None


async def _llm_says_jailbreak(text: str) -> bool:
    if _classifier is None:
        return False
    try:
        return bool(await _classifier(text))
    except Exception as e:
        # fail-open: Klassifikator-Ausfall darf niemanden sperren
        print(f"[SecurityGuard] LLM-Klassifikator-Fehler (fail-open): {e}", flush=True)
        return False


async def inspect(text: str, user: str, channel: str,
                  block: bool = True) -> tuple[bool, dict | None]:
    """Prueft eine Eingabe. Bei Erkennung wird ein Vorfall protokolliert und
    – wenn ``block`` True ist – der Account gesperrt.

    Rueckgabe: (erkannt, incident|None). ``block=False`` (z.B. WhatsApp ohne
    Account) protokolliert dennoch, sperrt aber nicht.
    """
    cfg = get_config()
    if not cfg["enabled"] or not (text or "").strip():
        return (False, None)

    method = None
    pattern = None
    heur = heuristic_match(text) if cfg["heuristic"] else None

    if cfg["heuristic"] and cfg["llm"]:
        # Hybrid: Heuristik ist das Gate, LLM bestaetigt den Verdacht.
        if not heur:
            return (False, None)
        if not await _llm_says_jailbreak(text):
            return (False, None)
        method, pattern = "hybrid", heur
    elif cfg["heuristic"]:
        if not heur:
            return (False, None)
        method, pattern = "heuristic", heur
    elif cfg["llm"]:
        if not await _llm_says_jailbreak(text):
            return (False, None)
        method, pattern = "llm", "llm-classifier"
    else:
        return (False, None)

    if not block:
        # Nur protokollieren (kein Account vorhanden, z.B. WhatsApp-Absender):
        # in einem separaten "log-only"-Pseudo-Eintrag festhalten.
        incident = {
            "ts": int(time.time()), "channel": channel, "method": method,
            "pattern": pattern, "snippet": (text or "")[:500],
        }
        with _lock:
            state = _load()
            log = state.setdefault("logonly", [])
            log.append({"user": user, **incident})
            state["logonly"] = log[-200:]
            _save(state)
        print(f"[SecurityGuard] VORFALL ({method}/{pattern}) – log-only "
              f"[{channel}/{user}]", flush=True)
        return (True, incident)

    incident = _record(user, channel, method, pattern, text)
    return (True, incident)
