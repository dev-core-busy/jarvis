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
from pathlib import Path
from typing import Optional


# Anzeige-/Verhaltens-Standardwerte. Jeder Schluessel ist zugleich das, was
# ``public_config`` an das Frontend gibt (ausser ``overrides`` – die bleiben
# serverseitig).
DEFAULTS: dict = {
    "graphic": "Clippy",          # s. available_graphics()
    "position": "bottom-right",   # bottom-right | bottom-left
    "title": "",                  # Kopfzeile des Widgets (leer = Assistentenname/Standard)
    "greeting": "",               # Begruessung beim Oeffnen (leer = i18n-Standard)
    "speak_on_voice": True,       # Mikrofon-Eingabe → Antwort zusaetzlich vorlesen (TTS)
    "auto_open": False,           # Widget beim Laden der Seite geoeffnet zeigen
    "overrides": "",              # mehrzeilig: "<Frage> ||| <Antwort>" je Zeile
    # ── Antwortquelle ───────────────────────────────────────────────
    "answer_mode": "agent",       # agent | sources
    "confluence_pages": "",       # je Zeile eine Confluence-URL oder Seiten-ID
    "include_subpages": True,     # Unterseiten der angegebenen Seiten mitlesen
    "use_rag": False,             # zusaetzlich die Wissensdatenbank als Quelle
    "no_answer_text": "",         # Antwort, wenn nichts passt (leer = Standard)
}

ANSWER_MODES = ["agent", "sources"]

# Standardtext, wenn weder FAQ noch Quellen die Frage abdecken. Bewusst ein
# klarer Hinweis statt einer geratenen Antwort.
DEFAULT_NO_ANSWER = ("Dazu steht nichts in den hinterlegten Unterlagen. "
                     "Bitte wende dich an den Support.")

# Wie viele Zeichen Quelltext hoechstens ins Prompt gehen. Das Kontextfenster
# ist endlich; ein Handbuch mit Unterseiten sprengt es sonst.
CONTEXT_BUDGET = 24000
# Seitentexte werden zwischengespeichert – ohne Cache kostet JEDE Frage
# mehrere Confluence-Aufrufe (Seite + Unterseiten).
PAGE_TTL_SEC = 600
_page_cache: dict = {}

# Eingebaute Figuren (ohne Sprite-Ordner):
#   placeholder – schlichte SVG-Figur, Vorlage fuer eigene Grafiken
#   branding    – das hochgeladene Firmenlogo als Figur (Branding-Skill)
BUILTIN_GRAPHICS = ["placeholder", "branding"]
POSITIONS = ["bottom-right", "bottom-left"]

# Basis-URL, unter der die selbst gehosteten clippy.js-Assets liegen
# (``frontend/`` ist unter ``/static`` gemountet, siehe main.py).
ASSETS_BASE = "/static/vendor/clippy"

# Verzeichnis mit den Sprite-Saetzen im clippy.js-Format
_AGENTS_DIR = Path(__file__).parent.parent / "frontend" / "vendor" / "clippy" / "agents"


def sprite_agents() -> list[str]:
    """Alle auf der Platte vorhandenen Sprite-Saetze.

    Ein gueltiger Satz ist ein Ordner unter ``frontend/vendor/clippy/agents``
    mit ``agent.js`` UND ``map.png``. Die Liste wird bei jedem Aufruf frisch
    gelesen: ein neuer Ordner soll OHNE Code-Aenderung und ohne Dienst-Neustart
    auswaehlbar sein – genau das war vorher nicht moeglich (die Auswahl stand
    hart in einer Konstante, und geladen wurde ohnehin immer "Clippy").
    """
    try:
        return sorted(
            d.name for d in _AGENTS_DIR.iterdir()
            if d.is_dir() and (d / "agent.js").is_file() and (d / "map.png").is_file()
        )
    except Exception:
        return []


def available_graphics() -> list[str]:
    """Auswaehlbare Werte fuer ``graphic`` (eingebaut + gefundene Sprite-Saetze)."""
    return BUILTIN_GRAPHICS + sprite_agents()


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
    # Altwert aus der ersten Fassung: "clippy" war ein fester Schluessel, heute
    # ist es der ORDNERNAME des Sprite-Satzes.
    if str(cfg["graphic"]).lower() == "clippy":
        cfg["graphic"] = "Clippy"
    avail = available_graphics()
    if cfg["graphic"] not in avail:
        # Unbekannt (z.B. Sprite-Ordner entfernt) -> sichtbare Figur behalten,
        # nicht stumm auf einen anderen Sprite-Satz raten.
        print(f"[avatar] Unbekannte Grafik {cfg['graphic']!r} – nutze 'placeholder'. "
              f"Verfuegbar: {', '.join(avail)}", flush=True)
        cfg["graphic"] = "placeholder"
    if cfg["position"] not in POSITIONS:
        cfg["position"] = "bottom-right"
    cfg["speak_on_voice"] = bool(cfg["speak_on_voice"])
    cfg["auto_open"] = bool(cfg["auto_open"])
    cfg["title"] = str(cfg.get("title") or "")
    cfg["greeting"] = str(cfg.get("greeting") or "")
    cfg["overrides"] = str(cfg.get("overrides") or "")
    if cfg["answer_mode"] not in ANSWER_MODES:
        cfg["answer_mode"] = "agent"
    cfg["confluence_pages"] = str(cfg.get("confluence_pages") or "")
    cfg["include_subpages"] = bool(cfg["include_subpages"])
    cfg["use_rag"] = bool(cfg["use_rag"])
    cfg["no_answer_text"] = str(cfg.get("no_answer_text") or "")
    return cfg


# ── Quellen (Confluence) ────────────────────────────────────────────

def parse_page_refs(text: str) -> list[str]:
    """Zieht Confluence-Seiten-IDs aus der Konfiguration.

    Akzeptiert je Zeile eine volle URL (``…/pages/315077818/Titel``) ODER eine
    blosse Seiten-ID. Beides, weil ein Admin die URL aus dem Browser kopiert,
    ein Skript aber eher die ID kennt. Unbrauchbare Zeilen werden verworfen –
    eine geratene Seiten-ID waere schlimmer als keine.
    """
    ids: list[str] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.search(r"/pages/(\d+)", line)
        if m:
            pid = m.group(1)
        elif line.isdigit():
            pid = line
        else:
            # ?pageId=12345 (aeltere Confluence-Links)
            m2 = re.search(r"[?&]pageId=(\d+)", line)
            if not m2:
                continue
            pid = m2.group(1)
        if pid not in ids:
            ids.append(pid)
    return ids


def load_sources(cfg: Optional[dict] = None) -> list[dict]:
    """Holt die konfigurierten Confluence-Seiten (optional inkl. Unterseiten).

    Rueckgabe je Seite: ``{"title", "url", "text"}``. Fehler einzelner Seiten
    werden uebersprungen und protokolliert – eine unlesbare Unterseite darf die
    Auskunft nicht komplett verhindern.
    """
    import time
    if cfg is None:
        cfg = load_config()
    refs = parse_page_refs(cfg.get("confluence_pages", ""))
    if not refs:
        return []
    from backend.confluence_client import ConfluenceClient, html_to_text, ConfluenceError
    c = ConfluenceClient()
    if not c.configured:
        print("[avatar] Confluence ist nicht konfiguriert – keine Quellen.", flush=True)
        return []

    seiten: list[str] = list(refs)
    if cfg.get("include_subpages"):
        for pid in refs:
            try:
                for kind in c.get_descendants(pid):
                    if kind["id"] not in seiten:
                        seiten.append(kind["id"])
            except Exception as e:
                print(f"[avatar] Unterseiten von {pid} nicht lesbar: {e}", flush=True)

    out: list[dict] = []
    now = time.time()
    for pid in seiten:
        hit = _page_cache.get(pid)
        if hit and (now - hit[0]) < PAGE_TTL_SEC:
            out.append(hit[1])
            continue
        try:
            d = c.get_page(page_id=pid)
            body = (((d.get("body") or {}).get("storage") or {}).get("value") or "")
            # Hohes Limit: die Kuerzung passiert spaeter gezielt ueber die
            # Abschnitts-Auswahl, nicht blind am Textende.
            eintrag = {
                "title": d.get("title", "") or pid,
                "url": (c.base + "/pages/viewpage.action?pageId=" + pid) if c.base else "",
                "text": html_to_text(body, limit=200000),
            }
            _page_cache[pid] = (now, eintrag)
            out.append(eintrag)
        except ConfluenceError as e:
            print(f"[avatar] Seite {pid} nicht lesbar: {e}", flush=True)
        except Exception as e:
            print(f"[avatar] Seite {pid} fehlgeschlagen: {e}", flush=True)
    return out


_STOP = set("der die das und oder ist sind ein eine einen dem den des mit fuer für von "
            "im in auf zu wie was wer wann wo warum bei aus als auch nicht kann man ich "
            "du wir ihr sie es am an the a of to and or is are how what when where why".split())


def _terms(s: str) -> set:
    return {w for w in re.split(r"[^0-9a-zA-ZäöüÄÖÜß]+", (s or "").lower())
            if len(w) > 2 and w not in _STOP}


def select_sections(sources: list[dict], question: str,
                    budget: int = CONTEXT_BUDGET) -> list[dict]:
    """Waehlt die zur Frage passenden Abschnitte aus den Quellen.

    Warum ueberhaupt auswaehlen: ein Handbuch mit Unterseiten ist deutlich
    groesser als das Kontextfenster. Blindes Abschneiden am Textende wuerde
    genau die Stelle verlieren, die die Antwort enthaelt.

    Geschnitten wird an den ``##``-Ueberschriften, die ``html_to_text`` setzt;
    bewertet wird nach Wortueberschneidung mit der Frage. Passt alles ins
    Budget, bleibt die Reihenfolge des Dokuments erhalten (Abschnitt 1, 2, 3 …)
    – sonst laese das Modell ein Handbuch in Relevanz-Reihenfolge.
    """
    q = _terms(question)
    kandidaten: list[dict] = []
    for si, src in enumerate(sources):
        teile = re.split(r"\n(?=## )", src.get("text", "") or "")
        for ti, teil in enumerate(teile):
            teil = teil.strip()
            if not teil:
                continue
            treffer = len(q & _terms(teil))
            kandidaten.append({"src": si, "pos": (si, ti), "text": teil,
                               "score": treffer, "title": src.get("title", ""),
                               "url": src.get("url", "")})
    if not kandidaten:
        return []
    gesamt = sum(len(k["text"]) for k in kandidaten)
    if gesamt <= budget:
        return kandidaten          # alles passt -> Dokumentreihenfolge behalten
    # Nach Relevanz auswaehlen, danach wieder in Dokumentreihenfolge bringen.
    kandidaten.sort(key=lambda k: (-k["score"], k["pos"]))
    gewaehlt, verbraucht = [], 0
    for k in kandidaten:
        if k["score"] == 0 and gewaehlt:
            break                  # ohne jeden Bezug nichts mehr dazunehmen
        if verbraucht + len(k["text"]) > budget:
            continue
        gewaehlt.append(k)
        verbraucht += len(k["text"])
    gewaehlt.sort(key=lambda k: k["pos"])
    return gewaehlt


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


_NO_ANSWER_MARK = "KEINE_ANTWORT"


async def answer_from_sources(question: str, cfg: Optional[dict] = None,
                              kb_groups=None, username: str = "") -> dict:
    """Beantwortet eine Frage AUSSCHLIESSLICH aus den hinterlegten Quellen.

    Bewusst KEIN Agentenlauf: der Provider wird direkt mit ``tools=[]``
    aufgerufen. Damit gibt es keine Werkzeuge, keine Shell, keine
    Wissensdatenbank ausser der ausdruecklich zugeschalteten – das Modell sieht
    nur den uebergebenen Text. Es bleibt „das Gehirn" (versteht die Frage,
    findet die Stelle, formuliert), erfindet aber keine Quellen dazu.

    Rueckgabe: ``{"answer", "found", "sources"}``. ``found=False`` heisst, dass
    die Quellen die Frage nicht abdecken – dann steht im ``answer`` der
    konfigurierte Hinweistext.
    """
    if cfg is None:
        cfg = load_config()
    fallback = cfg.get("no_answer_text") or DEFAULT_NO_ANSWER

    import asyncio
    try:
        quellen = await asyncio.to_thread(load_sources, cfg)
    except Exception as e:
        print(f"[avatar] Quellen laden fehlgeschlagen: {e}", flush=True)
        quellen = []

    teile = select_sections(quellen, question) if quellen else []
    blocks: list[str] = []
    benutzte: list[dict] = []
    for t in teile:
        blocks.append("### Quelle: %s\n%s" % (t["title"], t["text"]))
        if not any(b["title"] == t["title"] for b in benutzte):
            benutzte.append({"title": t["title"], "url": t["url"]})

    # Wissensdatenbank nur, wenn ausdruecklich eingeschaltet (eigene Checkbox).
    if cfg.get("use_rag"):
        try:
            from backend.tools.knowledge import rag_search
            from backend.sandbox import set_tool_user, reset_tool_user
            # Benutzerkontext setzen wie im Agenten-Dispatch, damit
            # benutzerbezogene Schranken auch auf diesem Weg greifen.
            _tok = set_tool_user(username or "")
            try:
                treffer = await rag_search(question, 6, groups=kb_groups or None)
            finally:
                reset_tool_user(_tok)
            for _score, pfad, chunk in treffer:
                blocks.append("### Quelle: Wissensdatenbank – %s\n%s" % (pfad, chunk))
            if treffer:
                benutzte.append({"title": "Wissensdatenbank", "url": ""})
        except Exception as e:
            print(f"[avatar] RAG-Suche fehlgeschlagen: {e}", flush=True)

    if not blocks:
        return {"answer": fallback, "found": False, "sources": []}

    sysp = (
        "Du bist ein Auskunfts-Assistent. Beantworte die Frage AUSSCHLIESSLICH "
        "anhand der unten stehenden Quellen. Nutze KEIN eigenes Vorwissen und "
        "erfinde nichts. Steht die Antwort nicht in den Quellen, antworte "
        "ausschliesslich mit dem Wort %s und sonst nichts. "
        "Antworte sonst kurz, freundlich und in der Sprache der Frage; "
        "keine Aufzaehlung von Quellen, kein JSON." % _NO_ANSWER_MARK
    )
    inhalt = "\n\n".join(blocks)[:CONTEXT_BUDGET + 8000]
    user_text = "Frage: %s\n\nQuellen:\n%s" % (question, inhalt)

    try:
        from backend.llm import get_provider
        from backend.config import config as _cfgmod
        from google.genai import types
        prof = _cfgmod.active_profile or {}
        provider = get_provider(
            prof.get("provider", "google"), prof.get("api_key", ""),
            prof.get("api_url", ""), auth_method=prof.get("auth_method", "api_key"),
            session_key=prof.get("session_key", ""), prompt_tool_calling=False)
        resp = await provider.generate_response(
            model=prof.get("model", ""), system_prompt=sysp,
            contents=[types.Content(role="user",
                                    parts=[types.Part.from_text(text=user_text)])],
            tools=[])
        text = "".join(p.text for p in (resp.parts or [])
                       if getattr(p, "text", None)).strip()
    except Exception as e:
        print(f"[avatar] Quellen-Antwort fehlgeschlagen: {e}", flush=True)
        return {"answer": fallback, "found": False, "sources": []}

    # Das Modell haelt sich nicht immer exakt an den Marker – deshalb auch
    # "enthaelt" pruefen und leere Antworten wie "nicht gefunden" behandeln.
    if not text or _NO_ANSWER_MARK in text.upper():
        return {"answer": fallback, "found": False, "sources": []}
    return {"answer": text, "found": True, "sources": benutzte[:5]}


def public_config() -> dict:
    """Anzeige-Konfiguration fuer ``GET /api/avatar/config``.

    Enthaelt bewusst KEINE Overrides – die Trigger/Antworten bleiben
    serverseitig (siehe Modul-Docstring).
    """
    cfg = load_config()
    return {
        "active": is_active(),
        "graphic": cfg["graphic"],
        # Damit das Widget weiss, WIE die gewaehlte Grafik zu rendern ist,
        # ohne die Ordnerliste selbst zu kennen.
        "is_sprite": cfg["graphic"] in sprite_agents(),
        "position": cfg["position"],
        "title": cfg["title"],
        "greeting": cfg["greeting"],
        "speak_on_voice": cfg["speak_on_voice"],
        "auto_open": cfg["auto_open"],
        "assets_base": ASSETS_BASE,
    }
