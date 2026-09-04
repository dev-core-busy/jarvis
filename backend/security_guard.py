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

    # ── DEUTSCHE GEGENSTUECKE ───────────────────────────────────────────────
    # GEMESSEN AM 2026-08-18: die Liste war rein englisch. Auf einem
    # deutschsprachigen System blieb damit JEDER deutsche Versuch unsichtbar –
    # in ALLEN Kanaelen (Chat, WhatsApp, E-Mail-Regeln, Support, Short Tracks).
    # Nachgewiesen mit "IGNORIERE ALLE VORHERIGEN ANWEISUNGEN …": heuristic_match
    # gab None zurueck, das Vorfallsprotokoll blieb leer, obwohl der Angriff im
    # Ergebnistext des Modells ausdruecklich benannt wurde.
    #
    # Bewusst NUR die woertlichen Gegenstuecke der Muster oben – keine neuen
    # Musterklassen. Grund: im reinen Heuristik-Modus (ohne LLM-Bestaetigung)
    # sperrt ein Treffer Konten, und ein zu breites deutsches Muster wuerde
    # harmlose Saetze treffen ("ignoriere die Warnung im Log").
    (r"(?:ignorier|ignoriere|vergiss|missachte|verwerfe)\w*\s+(?:alle|jede|sämtliche|saemtliche|deine|die|alles)\s*"
     r"(?:vorherigen?|vorigen?|bisherigen?|obigen?|frühere[nr]?|fruehere[nr]?)?\s*"
     r"(?:anweisungen?|instruktionen?|regeln?|vorgaben?|richtlinien?)",
     "ignoriere-anweisungen"),
    (r"(?:neue|geänderte|geaenderte|aktualisierte|vorrangige|zusätzliche|zusaetzliche)\s+"
     r"(?:anweisung(?:en)?|regel(?:n)?|aufgabe(?:n)?|system-?prompt)\s*:",
     "anweisung-ueberschreiben"),
    (r"(?:zeige|nenne|gib|verrate|drucke|wiederhole)\w*\s+(?:mir\s+)?"
     r"(?:den|dem|die|das|deinen?|deine[nr]?)\s+"
     r"(?:system-?prompt|systemprompt|(?:ursprünglichen?|urspruenglichen?|internen?)\s+"
     r"(?:anweisungen|instruktionen|prompt))",
     "system-prompt-verraten"),
    (r"(?:du\s+bist\s+(?:jetzt|ab\s+jetzt|nun))\s+(?:ein[e]?\s+)?"
     r"(?:uneingeschränkte|uneingeschraenkte|ungefilterte|unzensierte|amoralische)",
     "unrestricted-persona-de"),
    (r"(?:umgehe|deaktiviere|schalte\s+ab|hebe\s+auf|übergehe|uebergehe)\s+"
     r"(?:alle\s+|deine\s+|die\s+)?(?:sicherheits\w*|schutz\w*|filter\w*|sperren?|beschränkungen?|beschraenkungen?)",
     "bypass-safety-de"),
    # BEWUSST NICHT ERGAENZT: ein deutsches Gegenstueck zu "without-restrictions"
    # ("ohne Regeln", "ohne Beschraenkungen"). Gemessen am 2026-08-18: es traf
    # "Wir arbeiten ohne Regeln der alten Fassung weiter" und "Der Vertrag gilt
    # ohne Beschraenkungen der Haftung" – im deutschen Geschaeftsalltag
    # alltaegliche Saetze. Im reinen Heuristik-Modus haette das Konten gesperrt,
    # und ein Fehlalarm mit Kontosperre ist schlimmer als eine Luecke in der
    # Sichtbarkeit (Lehre vom 2026-08-05, `2>/dev/null` sperrte vier Konten).
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


def norm_user(name: str) -> str:
    """Benutzername auf den blossen Kontonamen: ohne ``DOMAIN\\``, ohne
    ``@domain``, klein. Kanal-Kennungen (``wa:``/``tg:``/``api:``) bleiben ganz.

    WARUM DAS SICHERHEITSRELEVANT IST (Befund 2026-08-10): Sperren und der
    Verstoss-Zaehler lagen unter dem ROHEN Namen. Derselbe Mensch, der sich
    einmal als ``sven.sander`` und einmal als ``nexus\\sven.sander`` anmeldet,
    hatte damit ZWEI getrennte Zaehler – die Auto-Sperre (drei Verstoesse in
    600 s) war durch Wechseln der Tippform verzoegerbar, und eine bestehende
    Sperre griff nur fuer die Variante, unter der sie entstanden ist.
    Dieselbe Normalisierung nutzen `documents._norm` und `_norm_login` in
    main.py schon lange – hier fehlte sie.
    """
    s = (name or "").strip()
    if not s or ":" in s:
        return s.lower()
    return s.split("@")[0].split("\\")[-1].strip().lower()


def _finde_key(store: dict, user: str) -> str | None:
    """Vorhandenen Schluessel zu diesem Benutzer finden – exakt oder normalisiert.

    Der ALTBESTAND steht unter der damaligen Tippform; er wird nicht migriert
    (eine Sperre umzuschreiben ist eine Sicherheitsentscheidung), sondern beim
    Lesen mitgefunden.
    """
    if not user:
        return None
    if user in store:
        return user
    n = norm_user(user)
    if not n:
        return None
    for k in store:
        if norm_user(k) == n:
            return k
    return None


def is_blocked(user: str) -> bool:
    if not user:
        return False
    with _lock:
        return _finde_key(_load().get("blocked", {}), user) is not None


def get_block(user: str):
    """Sperr-Info eines Benutzers (inkl. Vorfaelle) oder None."""
    if not user:
        return None
    with _lock:
        blk = _load().get("blocked", {})
        k = _finde_key(blk, user)
        return blk.get(k) if k else None


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


def block(user: str, reason: str = "", by: str = "") -> bool:
    """Sperrt einen Account VON HAND (Administrator).

    Bis 2026-07-31 entstanden Sperren ausschliesslich automatisch aus einem
    erkannten Verstoss (``_record``); ein Administrator konnte nur ENTsperren.
    Der Eintrag hat bewusst dieselbe Form wie eine automatische Sperre, damit
    die vorhandene Anzeige unter *Sicherheit → Angriffspraevention* ihn ohne
    Sonderfall darstellt – erkennbar ist er an ``method="manuell"``.

    Gibt False zurueck, wenn der Account bereits gesperrt war.
    """
    if not user:
        return False
    now = int(time.time())
    with _lock:
        state = _load()
        blk = state.setdefault("blocked", {})
        if _finde_key(blk, user) is not None:
            return False
        # NEUE Sperren unter dem normalisierten Namen – dann greift sie
        # unabhaengig davon, wie sich der Betroffene das naechste Mal anmeldet.
        blk[norm_user(user) or user] = {
            "reason": (reason or "Von einem Administrator gesperrt")[:200],
            "method": "manuell",
            "channel": "admin",
            "at": now,
            "by": by or "",
            "incidents": [{
                "ts": now,
                "channel": "admin",
                "method": "manuell",
                "pattern": (reason or "manuelle Sperre")[:200],
                "snippet": f"Gesperrt durch '{by}'." if by else "Manuell gesperrt.",
            }],
        }
        _save(state)
    print(f"[SecurityGuard] Account MANUELL gesperrt durch '{by}': {user}", flush=True)
    return True


def unblock(user: str) -> bool:
    """Hebt die Sperre auf. True, wenn der Benutzer gesperrt war."""
    with _lock:
        state = _load()
        blk = state.get("blocked", {})
        k = _finde_key(blk, user)
        if k is not None:
            blk.pop(k, None)
            _save(state)
            print(f"[SecurityGuard] Account freigeschaltet: {k}", flush=True)
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
        _k = _finde_key(blk, user)
        if _k is not None:
            blk[_k].setdefault("incidents", []).append(incident)
        else:
            blk[norm_user(user) or user] = {
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


# ── Richtlinien-Verstoesse (Sandbox-/Autorisierungs-Deny) + Auto-Sperre ──────
# Anders als 'inspect' (Jailbreak-Persona) erfassen diese die im Tool-Dispatch
# ERZWUNGENEN Zugriffsverweigerungen (Secrets/Root/Base64). Ab einer Schwelle
# innerhalb eines Zeitfensters wird der Domain-Account automatisch gesperrt.
def _autoblock_cfg() -> dict:
    def _int(v, d):
        try:
            return int(v)
        except Exception:
            return d
    return {
        "enabled": _as_bool(config.get_setting("security_autoblock_enabled", None), True),
        "count": _int(config.get_setting("security_autoblock_count", 3), 3),
        "window": _int(config.get_setting("security_autoblock_window", 600), 600),
    }


# Aufbewahrte Textlaenge je Vorfall. Der frueher hier stehende 200/300-Schnitt war
# der Grund, warum sich mehrere Sperren im Nachhinein nicht mehr beurteilen liessen
# (Befehl mitten im Redirect-Ziel abgeschnitten). Die Datei bleibt klein, weil je
# Konto nur die letzten 100 Vorfaelle gehalten werden.
_DETAIL_MAX = 2000
_TASK_MAX = 1000


def record_violation(user: str, channel: str, kind: str, detail: str = "",
                     snippet: str = "", exempt: bool = False,
                     tool: str = "", task: str = "", ip: str = "",
                     client_type: str = "", escalate: bool = True,
                     marke: str = "") -> dict:
    """Protokolliert einen Richtlinien-Verstoss und sperrt den Account ab Schwelle.
    exempt=True (lokale/Admin-Konten) -> nur protokollieren, nie sperren.
    Fuer aussagekraeftiges Logging werden zusaetzlich Tool, ausloesende Anfrage
    (task/Prompt), IP und Client-Typ festgehalten.

    ``escalate=False`` = **weiche** Ablehnung: wird protokolliert und bleibt in der
    Oberflaeche sichtbar, sperrt aber nicht und **zaehlt auch spaeter nicht mit**
    (Feld ``soft``). Gedacht fuer Sandbox-Grenzen, die ein Benutzer normal nicht
    kennen kann – ein abgewiesener Werkzeug-Aufruf ist kein Angriffsindiz.
    Anlass: am 2026-08-05 sperrte sich auf ECHT ein Benutzer mit drei harmlosen
    ``grep … 2>/dev/null`` selbst aus (Grund ``policy:shell-write``).
    **Der Filter unten prueft das Feld, nicht den Parameter** – damit zaehlen auch
    bereits gespeicherte weiche Einträge nicht mehr als Futter fuer eine spaetere
    Sperre.

    ``marke`` benennt die getroffene SCHRANKE (nicht den Befehl), z.B.
    ``pfad:/root`` oder ``verb:systemctl``. **Gleiche Marke im Zeitfenster zaehlt
    EINMAL.**

    ⚠ WARUM (Vorfall ECHT, 2026-09-04, 17:11): ein Benutzer wurde von drei
    Lesesuchen in der Wissensdatenbank gesperrt – dreimal derselbe falsche Pfad
    ``/root/jarvis/data/knowledge`` (er stand in einem alten Merksatz im
    Gedaechtnis des Agenten), abgewiesen in DREI SEKUNDEN. Der Befehlstext war
    jedes Mal ein anderer (``find`` / ``grep`` / ``find | xargs``), die Schranke
    aber dieselbe. **Dreimal an dieselbe Tuer zu fassen ist ein Irrtum, drei
    verschiedene Tueren sind ein Muster** – und nur das Muster ist ein
    Angriffsindiz. Dieselbe Ueberlegung wie bei ``escalate=False`` fuer
    ``blocked-tool``: was das MODELL waehlt, kann der Benutzer nicht vermeiden.

    Die Schwelle bleibt unveraendert scharf, wo sie gemeint ist: wer drei
    verschiedene Secret-Ziele abklopft, hat drei Marken. Eintraege OHNE Marke
    zaehlen einzeln wie bisher (fail-closed – ein neuer Deny-Zweig verhaelt sich
    ohne Zutun wie vorher).
    Rueckgabe: {'blocked': bool, 'count': int}."""
    ts = int(time.time())
    entry = {"ts": ts, "channel": channel, "method": "policy", "pattern": kind,
             "detail": (detail or "")[:_DETAIL_MAX], "snippet": (snippet or "")[:_DETAIL_MAX],
             "tool": tool or "", "task": (task or "")[:_TASK_MAX],
             "ip": ip or "", "client_type": client_type or ""}
    if marke:
        entry["marke"] = str(marke)[:120]
    if not escalate:
        entry["soft"] = True
    blocked_now = False
    with _lock:
        state = _load()
        allv = state.setdefault("violations", {})
        # EIN Zaehler je Mensch, unabhaengig von der Tippform des Anmeldefelds.
        # Vorher konnte derselbe Benutzer zwei Toepfe fuellen und die Schwelle
        # damit umgehen; ein vorhandener Alt-Eintrag wird weiterverwendet.
        key = _finde_key(allv, user) or (norm_user(user) or user or "?")
        lst = allv.setdefault(key, [])
        lst.append(entry)
        allv[key] = lst[-100:]
        cfg = _autoblock_cfg()
        if (escalate and not exempt and user and cfg["enabled"]
                and _finde_key(state.get("blocked", {}), user) is None):
            recent = [e for e in allv[key]
                      if ts - e["ts"] <= cfg["window"] and not e.get("soft")]
            # Gezaehlt werden VERSCHIEDENE Schranken. Ohne Marke zaehlt der
            # Eintrag fuer sich (Position im Fenster als Ersatzmarke) – damit
            # bleibt das Verhalten fuer jeden Zweig, der keine setzt, exakt wie
            # bisher.
            marken = {e.get("marke") or ("#%d" % i) for i, e in enumerate(recent)}
            if len(marken) >= cfg["count"]:
                blk = state.setdefault("blocked", {})
                blk[norm_user(user) or user] = {
                    "reason": f"policy:{kind}",
                    "method": "auto-block (policy)",
                    "channel": channel,
                    "at": ts,
                    "incidents": recent[-max(cfg["count"], 10):],
                }
                blocked_now = True
        _save(state)
    tag = "AUTO-BLOCK" if blocked_now else ("GRENZE" if not escalate else "VERSTOSS")
    print(f"[SecurityGuard] {tag} ({kind}) [{channel}/{user}] {(detail or '')[:80]}", flush=True)
    return {"blocked": blocked_now, "count": len(allv.get(key, []))}


def list_recent_violations(limit: int = 100, mit_logonly: bool = True) -> list:
    """Letzte Richtlinien-Verstoesse (benutzeruebergreifend, neueste zuerst).

    ``mit_logonly`` nimmt die NUR PROTOKOLLIERTEN Vorfaelle mit auf – die von
    ``inspect(..., block=False)`` erzeugten Eintraege aus Kanaelen, in denen der
    Text von einem Fremden stammt (E-Mail-Regeln, Short Tracks). Sie zaehlen
    NICHT zur Auto-Sperre (sie liegen in einem eigenen Zweig der Zustandsdatei
    und werden hier nur zur Anzeige zusammengefuehrt), tragen aber ``soft: True``
    – dieselbe Kennzeichnung wie weiche Richtlinien-Verstoesse.

    WARUM DAS NOETIG WAR: bis 2026-08-18 gab dieser Aufruf ausschliesslich
    ``violations`` heraus. Der ``block=False``-Zweig von ``inspect`` verspricht
    im Docstring aber ausdruecklich, dass "der Eintrag in der Oberflaeche
    sichtbar bleibt" – und genau das war er nicht. Gemessen an den
    Injektionsproben von Short Tracks: zwei Vorfaelle in ``logonly``, null in der
    Admin-Liste. Eine Zusage, die der Code nicht haelt, ist im Zweifel
    gefaehrlicher als eine fehlende Funktion: niemand sieht, dass ein Postfach
    oder eine Ablage beschossen wird.
    """
    with _lock:
        state = _load()
        allv = state.get("violations", {})
        logonly = list(state.get("logonly") or []) if mit_logonly else []
    flat = []
    for user, entries in allv.items():
        for e in entries:
            flat.append({"user": user, **e})
    for e in logonly:
        # In dieselbe Form bringen, die die Oberflaeche rendert (ts/user/channel/
        # pattern/detail). `snippet` ist der beanstandete Fremdtext.
        flat.append({
            "user": e.get("user") or "?", "ts": e.get("ts", 0),
            "channel": e.get("channel") or "", "kind": "injektion-erkannt",
            "pattern": e.get("pattern") or e.get("method") or "",
            "detail": (e.get("snippet") or "")[:_DETAIL_MAX],
            "soft": True, "soft_reason": "nur protokolliert – der Text stammt von "
                                         "einem Fremden, dieser Eintrag sperrt nichts",
        })
    flat.sort(key=lambda x: x.get("ts", 0), reverse=True)
    return flat[:limit]


# ── Verschleierte (base64-kodierte) Payloads erkennen ────────────────────────
import base64 as _b64

# Mindestlaenge 11 Zeichen (= 8 Byte Klartext): faengt auch kurze Secret-/
# Shell-Befehle wie 'cat .env' / 'rm -rf /' (je 11 Zeichen Base64) oder
# 'cat /etc/shadow' (20). Fehlalarme sind unwahrscheinlich, weil ein Treffer
# zusaetzlich verlangt, dass der DEKODIERTE Text ein Gefahr-/Jailbreak-Muster
# trifft (heuristic_match / _DECODED_DANGER) – zufaellige Tokens dekodieren zu
# Binaermuell und passen dort nicht.
_B64_RUN = re.compile(r'[A-Za-z0-9+/]{11,}={0,2}')
_DECODED_DANGER = re.compile(
    r'\b(?:rm|chmod|chown|curl|wget|bash|sh|zsh|python\d?|perl|eval|exec|base64|xxd|'
    r'systemctl|useradd|passwd|nc|ncat)\b'
    r'|/etc/(?:shadow|passwd|sudoers)|\.env\b|settings\.json|id_rsa|(?:^|/)root\b',
    re.IGNORECASE)


def decode_and_scan(text: str):
    """Sucht base64-Bloecke, dekodiert sie und prueft den Klartext auf
    Jailbreak-Muster bzw. Shell-/Secret-Indikatoren. Gibt einen Marker
    zurueck (Grund) oder None. Verhindert die Base64-Umgehung des Guards."""
    if not text:
        return None
    for m in _B64_RUN.finditer(text):
        blob = m.group(0)
        try:
            dec = _b64.b64decode(blob + "=" * (-len(blob) % 4), validate=False)
        except Exception:
            continue
        s = dec.decode("utf-8", errors="ignore").strip()
        if len(s) < 4:
            continue
        hit = heuristic_match(s)
        if hit or _DECODED_DANGER.search(s):
            return "base64:" + (hit or "shell/secret")
    return None
