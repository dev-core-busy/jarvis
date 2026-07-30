"""Avatar-Skill – Backend.

Der Avatar (eine clippy.js-Figur bzw. ein SVG-Platzhalter) ist im Kern ein
Frontend-Widget (``frontend/js/avatar.js``). Dieses Modul liefert dazu:

  * die Anzeige-Konfiguration fuer das Widget (``public_config``),
  * den SERVERSEITIGEN Abgleich benutzerdefinierter Antworten
    (``match_override``) – „angepasste Antworten auf spezielle Fragen".

Analog zu ``branding`` liegen alle Einstellungen in der Skill-Config
(``settings.json`` → ``skills.avatar.config``); der aktivierte Zustand des
Skills schaltet das Widget an/aus.

Warum die Overrides bewusst im Backend liegen (Nutzer-Entscheidung 2026-07-30):
Ein reiner Frontend-Abgleich waere umgehbar und die Trigger-Fragen laegen offen
im Auslieferungscode. Serverseitig entscheidet ``/api/avatar/ask`` VOR dem
LLM-Lauf – ein Treffer spart zugleich einen teuren Agentenlauf.
"""

from __future__ import annotations

import re
from typing import Optional


# Anzeige-/Verhaltens-Standardwerte. Jeder Schluessel ist zugleich das, was
# ``public_config`` an das Frontend gibt (ausser ``overrides`` – die bleiben
# serverseitig).
DEFAULTS: dict = {
    "graphic": "clippy",          # clippy | placeholder (erweiterbar, s. skill.json)
    "position": "bottom-right",   # bottom-right | bottom-left
    "title": "",                  # Kopfzeile des Widgets (leer = Assistentenname/Standard)
    "greeting": "",               # Begruessung beim Oeffnen (leer = i18n-Standard)
    "speak_on_voice": True,       # Mikrofon-Eingabe → Antwort zusaetzlich vorlesen (TTS)
    "auto_open": False,           # Widget beim Laden der Seite geoeffnet zeigen
    "overrides": "",              # mehrzeilig: "<Frage> ||| <Antwort>" je Zeile
}

GRAPHICS = ["clippy", "placeholder"]
POSITIONS = ["bottom-right", "bottom-left"]

# Basis-URL, unter der die selbst gehosteten clippy.js-Assets liegen
# (``frontend/`` ist unter ``/static`` gemountet, siehe main.py).
ASSETS_BASE = "/static/vendor/clippy"


def _states() -> dict:
    from backend.config import config
    return config.get_skill_states()


def is_active() -> bool:
    """True, wenn der Avatar-Skill installiert UND aktiviert ist."""
    try:
        return bool(_states().get("avatar", {}).get("enabled"))
    except Exception:
        return False


def load_config() -> dict:
    """Vollstaendige, normalisierte Konfiguration inkl. der Overrides."""
    cfg = dict(DEFAULTS)
    try:
        raw = _states().get("avatar", {}).get("config", {}) or {}
        for k in DEFAULTS:
            if k in raw and raw[k] is not None:
                cfg[k] = raw[k]
    except Exception:
        pass
    if cfg["graphic"] not in GRAPHICS:
        cfg["graphic"] = "clippy"
    if cfg["position"] not in POSITIONS:
        cfg["position"] = "bottom-right"
    cfg["speak_on_voice"] = bool(cfg["speak_on_voice"])
    cfg["auto_open"] = bool(cfg["auto_open"])
    cfg["title"] = str(cfg.get("title") or "")
    cfg["greeting"] = str(cfg.get("greeting") or "")
    cfg["overrides"] = str(cfg.get("overrides") or "")
    return cfg


def parse_overrides(text: str) -> list[dict]:
    """Zerlegt den mehrzeiligen Overrides-Text in Frage/Antwort-Paare.

    Format je Zeile::

        Wie ist das Wetter? ||| Dafuer bin ich leider nicht zustaendig.
        oeffnungszeiten | wann habt ihr auf ||| Mo–Fr 8–17 Uhr.

    * Trenner zwischen Frage und Antwort ist ``|||``.
    * In der Frage-Spalte trennt ``|`` mehrere Trigger fuer DIESELBE Antwort.
    * Leere Zeilen und ``#``-Kommentarzeilen werden ignoriert.
    * Zeilen ohne jeden Trenner oder mit leerer Antwort werden verworfen.

    **Nachsicht bei einfachem ``|``:** Enthaelt eine Zeile KEIN ``|||``, aber ein
    ``|``, wird am ERSTEN ``|`` getrennt (links Frage, rechts Antwort). Grund:
    „Frage | Antwort" ist die naheliegende Schreibweise, und die strenge Fassung
    hat solche Zeilen still verworfen – der Eintrag stand sichtbar in den
    Einstellungen und tat nichts (auf DEV genau so passiert). Der Preis ist eine
    Fehldeutung, wenn jemand eine Trigger-Liste OHNE Antwort schreibt; das ist
    aber eine Zeile ohne Nutzen, waehrend „Frage | Antwort" echte Eingabe ist.
    """
    pairs: list[dict] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "|||" in line:
            q_raw, a_raw = line.split("|||", 1)
        elif "|" in line:
            q_raw, a_raw = line.split("|", 1)
        else:
            continue
        answer = a_raw.strip()
        if not answer:
            continue
        triggers = [t.strip() for t in q_raw.split("|") if t.strip()]
        if not triggers:
            continue
        pairs.append({"triggers": triggers, "answer": answer})
    return pairs


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def match_override(question: str, cfg: Optional[dict] = None) -> Optional[str]:
    """Sucht eine benutzerdefinierte Antwort fuer ``question``.

    Ein Treffer liegt vor, wenn die normalisierte Nutzerfrage einem Trigger
    exakt entspricht ODER der Trigger als eigenstaendiges Wortstueck in der
    Frage vorkommt (Wortgrenzen, damit „auto" nicht in „automatisch" trifft).
    Der erste Treffer in Reihenfolge der Zeilen gewinnt.
    """
    if cfg is None:
        cfg = load_config()
    q = _norm(question)
    if not q:
        return None
    for pair in parse_overrides(cfg.get("overrides", "")):
        for trig in pair["triggers"]:
            c = _norm(trig)
            if not c:
                continue
            if q == c:
                return pair["answer"]
            if re.search(r"(?<!\w)" + re.escape(c) + r"(?!\w)", q):
                return pair["answer"]
    return None


def public_config() -> dict:
    """Anzeige-Konfiguration fuer ``GET /api/avatar/config``.

    Enthaelt bewusst KEINE Overrides – die Trigger/Antworten bleiben
    serverseitig (siehe Modul-Docstring).
    """
    cfg = load_config()
    return {
        "active": is_active(),
        "graphic": cfg["graphic"],
        "position": cfg["position"],
        "title": cfg["title"],
        "greeting": cfg["greeting"],
        "speak_on_voice": cfg["speak_on_voice"],
        "auto_open": cfg["auto_open"],
        "assets_base": ASSETS_BASE,
    }
