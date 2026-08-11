#!/usr/bin/env python3
"""Modell-Faehigkeiten im Profil-Formular (ⓘ-Knopf, 2026-08-10).

FRAGE DES NUTZERS: "gibt es eine Moeglichkeit unter Einstellungen → KI & System
→ LLM-Profil ueber ein Info-Symbol eine Abfrage zu starten, die anzeigt, welche
Eigenschaften ein LLM hat? Bildgenerierung, TTS/STT usw?"

WAS DIE ANBIETER HERGEBEN (auf DEV gemessen, nicht geschaetzt):
  Google /v1beta/models  → supportedGenerationMethods, inputTokenLimit,
                           outputTokenLimit, `thinking`, Anzeigename
  Ollama /api/show       → capabilities [completion, vision, tools, thinking],
                           parameter_size, quantization_level, context_length
  vLLM   /v1/models      → NUR max_model_len – keine Faehigkeiten
  Anthropic /v1/models   → nur id/display_name

DIE KERNREGEL, die dieser Test schuetzt: ``None`` heisst "nicht ermittelbar" und
wird als "?" angezeigt – NIE als "nein". Bei vLLM ist ueber Vision nichts
bekannt; ein "nein" waere eine Behauptung ueber etwas, das nie abgefragt wurde.

    python3 tests/test_model_caps.py
"""

import ast
import asyncio
import json
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# backend.config nicht echt importieren (schreibt die Live-settings.json).
if "backend.config" not in sys.modules:
    _stub = types.ModuleType("backend.config")
    _stub.config = types.SimpleNamespace(get_setting=lambda *a, **k: "",
                                         ALLOWED_USERS=["jarvis"], profiles=[])
    sys.modules["backend.config"] = _stub

_ok = 0
_fail = 0


def pruefe(b, t, d=""):
    global _ok, _fail
    if b:
        _ok += 1
        print(f"  ✓ {t}")
    else:
        _fail += 1
        print(f"  ✗ {t}" + (f" – {d}" if d else ""))


def abschnitt(t):
    print(f"\n=== {t} ===")


try:
    from backend import model_caps as mc
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: backend.model_caps nicht importierbar: {e}")
    sys.exit(2)

MAIN_SRC = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
MC_SRC = (ROOT / "backend" / "model_caps.py").read_text(encoding="utf-8")
JS = (ROOT / "frontend" / "js" / "model_caps.js").read_text(encoding="utf-8")
I18N = (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")
HTML = (ROOT / "frontend" / "settings.html").read_text(encoding="utf-8")
CSS = (ROOT / "frontend" / "css" / "style.css").read_text(encoding="utf-8")


# ─── Fake-httpx-Client: liefert vorgegebene Antworten ────────────────────────
class _Antwort:
    def __init__(self, status=200, daten=None, text=""):
        self.status_code = status
        self._d = daten if daten is not None else {}
        self.text = text or json.dumps(self._d)

    def json(self):
        return self._d


class _Client:
    """Nur die Methoden, die model_caps benutzt. `plan` bildet URL-Teil → Antwort."""

    def __init__(self, plan):
        self.plan = plan
        self.aufrufe = []

    async def get(self, url, **kw):
        self.aufrufe.append(("GET", url))
        for teil, a in self.plan.items():
            if teil in url:
                return a
        return _Antwort(404, {})

    async def post(self, url, **kw):
        self.aufrufe.append(("POST", url))
        for teil, a in self.plan.items():
            if teil in url:
                return a
        return _Antwort(404, {})


def lauf(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ═════════════════════════════════════════════════════════════════════════════
abschnitt("1. Google: Methoden -> Faehigkeiten")

GEMINI = {"models": [{
    "name": "models/gemini-3.5-flash", "displayName": "Gemini 3.5 Flash",
    "description": "Gemini 3.5 Flash", "inputTokenLimit": 1048576,
    "outputTokenLimit": 65536, "maxTemperature": 2, "thinking": True,
    "supportedGenerationMethods": ["generateContent", "countTokens",
                                   "createCachedContent", "batchGenerateContent"],
}, {
    "name": "models/imagen-4.0-generate-001", "displayName": "Imagen 4",
    "supportedGenerationMethods": ["predict"],
}, {
    "name": "models/text-embedding-005", "displayName": "Embedding",
    "supportedGenerationMethods": ["embedContent"],
}]}

erg = {"faehigkeiten": mc._leer(), "grenzen": {}, "roh": [], "hinweise": [],
       "quelle": "", "anzeige_name": "", "beschreibung": "", "ok": True}
lauf(mc._aus_google(_Client({"/models": _Antwort(200, GEMINI)}), "k",
                    "gemini-3.5-flash", erg))
f = erg["faehigkeiten"]
pruefe(f["text"] is True, "generateContent -> Text ja")
pruefe(f["thinking"] is True, "das echte Feld `thinking` wird uebernommen")
pruefe(f["bild"] is False, "gemini-3.5-flash erzeugt keine Bilder")
pruefe(f["embedding"] is False, "kein embedContent -> Einbettungen nein")
pruefe(f["audio"] is False, "kein bidiGenerateContent -> Audio nein")
pruefe(f["vision"] is None,
       "VISION bleibt UNBEKANNT – die Google-Liste sagt dazu nichts")
pruefe(erg["grenzen"]["kontext_tokens"] == 1048576, "Kontextfenster uebernommen")
pruefe(erg["anzeige_name"] == "Gemini 3.5 Flash", "Anzeigename uebernommen")
pruefe(erg["quelle"] == "google-models", "Quelle benannt")

erg2 = {"faehigkeiten": mc._leer(), "grenzen": {}, "roh": [], "hinweise": [],
        "quelle": "", "anzeige_name": "", "beschreibung": "", "ok": True}
lauf(mc._aus_google(_Client({"/models": _Antwort(200, GEMINI)}), "k",
                    "imagen-4.0-generate-001", erg2))
pruefe(erg2["faehigkeiten"]["bild"] is True, "imagen-4.0 -> Bilder erzeugen ja")

erg3 = {"faehigkeiten": mc._leer(), "grenzen": {}, "roh": [], "hinweise": [],
        "quelle": "", "anzeige_name": "", "beschreibung": "", "ok": True}
lauf(mc._aus_google(_Client({"/models": _Antwort(200, GEMINI)}), "k",
                    "text-embedding-005", erg3))
pruefe(erg3["faehigkeiten"]["embedding"] is True, "Embedding-Modell erkannt")
pruefe(any("EINBETTUNGS-Modell" in h for h in erg3["hinweise"]),
       "Warnung: als Chat-Profil unbrauchbar")

# Unbekannter Modellname: Hinweis statt stiller Leere
erg4 = {"faehigkeiten": mc._leer(), "grenzen": {}, "roh": [], "hinweise": [],
        "quelle": "", "anzeige_name": "", "beschreibung": "", "ok": True}
lauf(mc._aus_google(_Client({"/models": _Antwort(200, GEMINI)}), "k",
                    "gemini-1.0-tot", erg4))
pruefe(any("steht NICHT in der Liste" in h for h in erg4["hinweise"]),
       "abgekuendigter Modellname wird benannt")
pruefe(all(v is None for v in erg4["faehigkeiten"].values()),
       "kein Treffer -> ALLE Werte unbekannt (nichts geraten)")


# ═════════════════════════════════════════════════════════════════════════════
abschnitt("2. Ollama: echte capabilities")

OLLAMA = {"capabilities": ["completion", "vision", "tools", "thinking"],
          "details": {"family": "gemma4", "parameter_size": "31.3B",
                      "quantization_level": "Q4_K_M"},
          "model_info": {"gemma4.context_length": 262144,
                         "gemma4.embedding_length": 5376}}

erg = {"faehigkeiten": mc._leer(), "grenzen": {}, "roh": [], "hinweise": [],
       "quelle": "", "anzeige_name": "", "beschreibung": "", "ok": True}
lauf(mc._aus_openai_kompatibel(_Client({"/api/show": _Antwort(200, OLLAMA)}),
                               "http://x:11434/v1", "", "gemma4:31b", erg))
f = erg["faehigkeiten"]
pruefe(erg["quelle"] == "ollama-show", "Ollama-Quelle erkannt")
pruefe(f["vision"] is True and f["tools"] is True and f["thinking"] is True,
       "vision/tools/thinking aus capabilities")
pruefe(f["bild"] is False and f["audio"] is False,
       "Bilderzeugung/Audio = NEIN (die capability-Liste ist vollstaendig)")
pruefe(erg["grenzen"]["kontext_tokens"] == 262144, "context_length gefunden")
pruefe(erg["grenzen"]["parameter"] == "31.3B", "Modellgroesse")
pruefe(erg["grenzen"]["quantisierung"] == "Q4_K_M", "Quantisierung")
pruefe(erg["roh"] == sorted(OLLAMA["capabilities"]), "Rohliste durchgereicht")


# ═════════════════════════════════════════════════════════════════════════════
abschnitt("3. vLLM: schweigt – und das muss man SEHEN")

VLLM = {"data": [{"id": "Qwen/Qwen3.6-35B-A3B-FP8", "max_model_len": 1010000,
                  "owned_by": "vllm"}]}
erg = {"faehigkeiten": mc._leer(), "grenzen": {}, "roh": [], "hinweise": [],
       "quelle": "", "anzeige_name": "", "beschreibung": "", "ok": True}
lauf(mc._aus_openai_kompatibel(
    _Client({"/api/show": _Antwort(404, {}), "/models": _Antwort(200, VLLM)}),
    "http://x:9081/v1", "", "Qwen/Qwen3.6-35B-A3B-FP8", erg))
f = erg["faehigkeiten"]
pruefe(f["text"] is True, "der Server nennt das Modell -> Chat geht")
pruefe(f["vision"] is None and f["tools"] is None and f["thinking"] is None,
       "vision/tools/thinking bleiben UNBEKANNT (nicht 'nein')")
pruefe(erg["grenzen"]["kontext_tokens"] == 1010000, "max_model_len -> Kontext")
pruefe(erg["grenzen"].get("server") == "vllm", "Server-Kennung")
pruefe(any("KEINE" in h and "Probe" in h for h in erg["hinweise"]),
       "Hinweis nennt die Luecke UND den Ausweg (Probe)")

# Modell nicht auf dem Server
erg = {"faehigkeiten": mc._leer(), "grenzen": {}, "roh": [], "hinweise": [],
       "quelle": "", "anzeige_name": "", "beschreibung": "", "ok": True}
lauf(mc._aus_openai_kompatibel(
    _Client({"/api/show": _Antwort(404, {}), "/models": _Antwort(200, VLLM)}),
    "http://x:9081/v1", "", "falscher-name", erg))
pruefe(erg["faehigkeiten"]["text"] is None,
       "unbekanntes Modell -> Text bleibt unbekannt, nicht True")
pruefe(any("nicht in der Liste" in h for h in erg["hinweise"]),
       "die vorhandenen Modellnamen werden genannt")

# Ollama mit LEERER capability-Liste darf nicht als Ollama gelten
erg = {"faehigkeiten": mc._leer(), "grenzen": {}, "roh": [], "hinweise": [],
       "quelle": "", "anzeige_name": "", "beschreibung": "", "ok": True}
lauf(mc._aus_openai_kompatibel(
    _Client({"/api/show": _Antwort(200, {"capabilities": []}),
             "/models": _Antwort(200, VLLM)}),
    "http://x/v1", "", "Qwen/Qwen3.6-35B-A3B-FP8", erg))
pruefe(erg["quelle"] == "openai-models",
       "leere capabilities -> Rueckfall auf /v1/models statt falscher 'nein'")


# ═════════════════════════════════════════════════════════════════════════════
abschnitt("4. OpenRouter und Anthropic")

OR = {"data": [{"id": "x/y", "name": "X Y", "context_length": 200000,
                "architecture": {"input_modalities": ["text", "image"],
                                 "output_modalities": ["text"]},
                "supported_parameters": ["tools", "reasoning", "temperature"]}]}
erg = {"faehigkeiten": mc._leer(), "grenzen": {}, "roh": [], "hinweise": [],
       "quelle": "", "anzeige_name": "", "beschreibung": "", "ok": True}
lauf(mc._aus_openrouter(_Client({"/models": _Antwort(200, OR)}), "x/y", erg))
f = erg["faehigkeiten"]
pruefe(f["vision"] is True, "input_modalities image -> Vision ja")
pruefe(f["bild"] is False, "output_modalities ohne image -> Bilderzeugung nein")
pruefe(f["tools"] is True and f["thinking"] is True,
       "supported_parameters -> tools/reasoning")
pruefe(erg["grenzen"]["kontext_tokens"] == 200000, "context_length")

erg = {"faehigkeiten": mc._leer(), "grenzen": {}, "roh": [], "hinweise": [],
       "quelle": "", "anzeige_name": "", "beschreibung": "", "ok": True}
lauf(mc._aus_anthropic(_Client({"/models": _Antwort(
    200, {"data": [{"id": "claude-opus-5", "display_name": "Claude Opus 5"}]})}),
    "k", "claude-opus-5", erg))
pruefe(erg["anzeige_name"] == "Claude Opus 5", "Anzeigename von Anthropic")
pruefe(erg["faehigkeiten"]["vision"] is None,
       "Anthropic nennt keine Faehigkeiten -> unbekannt")
pruefe(any("keine Fähigkeiten" in h for h in erg["hinweise"]),
       "der Grund wird gesagt (mit richtigen Umlauten)")


# ═════════════════════════════════════════════════════════════════════════════
abschnitt("5. Probe: Statuscode -> Aussage")

# 400/422 = der Anbieter lehnt GENAU dieses Merkmal ab -> kann er nicht.
# 401/404/5xx sagen nichts ueber das Merkmal -> None.
import backend.model_caps as _m


class _Ein:
    def __init__(self, a):
        self.a = a
        self.gesendet = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kw):
        self.gesendet.append(kw.get("json"))
        return self.a


def probe_mit(status):
    ein = _Ein(_Antwort(status, {}))
    alt = _m.httpx.AsyncClient
    _m.httpx.AsyncClient = lambda **kw: ein
    try:
        return lauf(_m._probe_openai("http://x/v1", "", "m", "vision", "AA")), ein
    finally:
        _m.httpx.AsyncClient = alt


pruefe(probe_mit(200)[0] is True, "HTTP 200 -> Merkmal vorhanden")
for s in (400, 422, 415):
    pruefe(probe_mit(s)[0] is False, f"HTTP {s} -> Merkmal fehlt")
for s in (401, 404, 500, 503):
    pruefe(probe_mit(s)[0] is None,
           f"HTTP {s} -> UNBEKANNT (sagt nichts ueber das Modell)")

_, ein = probe_mit(200)
pruefe(ein.gesendet and ein.gesendet[0].get("max_tokens") == 1,
       "die Probe fordert max_tokens=1 (Kosten minimal)")
pruefe("image_url" in json.dumps(ein.gesendet[0]),
       "die Vision-Probe schickt wirklich ein Bild")

# Transportfehler darf nicht durchschlagen
alt = _m.httpx.AsyncClient


class _Kaputt:
    async def __aenter__(self):
        raise _m.httpx.ConnectError("weg")

    async def __aexit__(self, *a):
        return False


_m.httpx.AsyncClient = lambda **kw: _Kaputt()
try:
    r = lauf(mc.proben("openai_compatible", "http://x/v1", "", "m",
                       welche=("vision",)))
finally:
    _m.httpx.AsyncClient = alt
pruefe(r["faehigkeiten"]["vision"] is None,
       "Verbindungsfehler -> unbekannt, keine Ausnahme")
pruefe(r["hinweise"] and "nicht prüfbar" in r["hinweise"][0],
       "der Grund steht im Hinweis")


# ═════════════════════════════════════════════════════════════════════════════
abschnitt("6. Jarvis-Bezug: was das System davon nutzt")

h = mc.jarvis_hinweise({"text": True, "bild": True}, "openai_compatible")
txt = " ".join(x["text"] for x in h)
pruefe("nur mit einem Google-Profil" in txt,
       "Nicht-Google-Profil: Bildgenerierung geht in Jarvis nicht")
h = mc.jarvis_hinweise({"text": True, "bild": True}, "google")
txt = " ".join(x["text"] for x in h)
pruefe("image_builder" in txt, "Google-Bildmodell: Verweis auf die Rolle")
h = mc.jarvis_hinweise({"tools": False}, "google")
txt = " ".join(x["text"] for x in h)
pruefe("Prompt-basiertes Tool-Calling" in txt,
       "ohne Werkzeuge: Verweis auf den Behelf im Profil")
# Der TTS/STT-Hinweis ist RAUS (Vorgabe des Nutzers 2026-08-11): er stand in
# JEDER Box mit identischem Wortlaut und verdraengte die Aussagen, die sich
# wirklich unterscheiden. Ein Hinweis, der nie variiert, ist Rauschen.
for prov in ("google", "openai_compatible", "anthropic"):
    t = " ".join(x["text"] for x in mc.jarvis_hinweise({"text": True}, prov))
    pruefe("TTS" not in t and "faster-whisper" not in t,
           f"{prov}: kein immergleicher TTS/STT-Hinweis mehr")
pruefe(mc.jarvis_hinweise({"text": True, "tools": True}, "google") == [],
       "ein unauffaelliges Google-Profil erzeugt GAR KEINEN Hinweis")


# ═════════════════════════════════════════════════════════════════════════════
abschnitt("7. Endpunkte, Rechte, Schluessel")

for pfad in ("/api/profiles/capabilities", "/api/profiles/capabilities/probe"):
    m = re.search(r'@app\.post\("' + re.escape(pfad) + r'"\)\s*\nasync def (\w+)'
                  r'\([^)]*\)', MAIN_SRC)
    pruefe(m is not None, f"{pfad} ist registriert")
    if m:
        pruefe("require_local_auth" in m.group(0),
               f"{pfad} ist Admin-only (SSRF-Werkzeug wie /test und /models)")

# Reihenfolge: FastAPI prueft in Registrierungsfolge, aber nur innerhalb DERSELBEN
# Methode. Kritisch waere allein ein `@app.post("/api/profiles/{...}")` VOR
# `/capabilities` – PUT/DELETE auf {profile_id} koennen einen POST nicht
# abfangen. (Der Fallstrick selbst ist echt: bei /api/conv_log hat genau das die
# Filter-Routen verschluckt.)
_posts = [(m.start(), m.group(1)) for m in
          re.finditer(r'@app\.post\("(/api/profiles[^"]*)"\)', MAIN_SRC)]
i_caps = next(p for p, n in _posts if n == "/api/profiles/capabilities")
_vorher_dyn = [n for p, n in _posts if p < i_caps and "{" in n]
pruefe(not _vorher_dyn,
       "keine POST-Route mit Platzhalter steht vor /capabilities",
       ", ".join(_vorher_dyn))

pruefe("_caps_key" in MAIN_SRC and 'if pid and (not key or "*" in key)' in MAIN_SRC,
       "maskierter/leerer Key wird durch den echten aus dem Profil ersetzt")
# Der Schluessel darf NICHT in der ANTWORT landen. `api_key=_caps_key(body)` ist
# ein Eingabe-Parameter – geprueft wird deshalb das Antwort-Objekt des Moduls,
# nicht der Aufruf. (Erste Testfassung schlug genau daran falsch an.)
erg_keys = set(lauf(mc.ermitteln("unbekannt")).keys())
pruefe(not (erg_keys & {"api_key", "session_key", "key"}),
       "die Antwortstruktur enthaelt kein Schluesselfeld", str(sorted(erg_keys)))
pruefe("scrub_secrets" in MC_SRC,
       "Fehlermeldungen werden von Schluesseln befreit (llm.scrub_secrets)")


# ═════════════════════════════════════════════════════════════════════════════
abschnitt("8. Oberflaeche: drei Zustaende, Markup, i18n, CSS")

# Der Knopf sitzt seit dem 2026-08-11 in der PROFILZEILE, nicht im Formular
# (Wunsch des Nutzers: "links von 'Nutzung erlauben fuer'").
APP = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
pruefe('id="btn-model-caps"' not in HTML,
       "kein ⓘ mehr im Bearbeiten-Formular (verschoben)")
pruefe("btn-caps-profile" in APP, "der ⓘ-Knopf wird in der Profilzeile erzeugt")
# Reihenfolge im Markup: ⓘ VOR dem Schloss-Knopf (= links davon)
i_caps = APP.index("btn-caps-profile")
i_perm = APP.index("btn-perms-profile")
pruefe(i_caps < i_perm, "ⓘ steht links vom Berechtigungs-Knopf (perm_label)")
pruefe("e.stopPropagation()" in APP[APP.index("const capsBtn"):
                                   APP.index("const capsBtn") + 400],
       "stopPropagation: ein Klick auf die Karte aktiviert sonst das Profil")
pruefe("window.ModelCaps.fuerProfil(p, card)" in APP,
       "der Handler uebergibt Profil UND Karte")
# Heimholen VOR dem Neuaufbau der Liste – sonst raeumt innerHTML='' das Panel ab
i_render = APP.index("function renderProfileList()")
fenster_r = APP[i_render:i_render + 700]
# Auf den AUFRUF pruefen, nicht auf das Wort: der Kommentar daneben nennt
# `innerHTML = ''` selbst (gleiche Falle wie beim Waechter in
# test_display_names.py, der am eigenen Warnsatz anschlug).
pruefe("ModelCaps.heim" in fenster_r
       and fenster_r.index("ModelCaps.heim")
           < fenster_r.index("profilesContainer.innerHTML = ''"),
       "renderProfileList holt das Panel heim, BEVOR es die Liste leert")

pruefe('id="model-caps-box"' in HTML, "das Panel existiert im Markup")
i_box = HTML.index('id="model-caps-box"')
i_cont = HTML.index('id="profiles-container"')
# Strukturell: zwischen der Oeffnung des Containers und dem Panel muss sein
# `</div>` liegen. (Erste Fassung suchte den STRING "profiles-container" – der
# steht auch im Kommentar am Panel und liess den Test falsch anschlagen.)
_zwischen = HTML[HTML.index(">", i_cont):i_box]
pruefe(i_box > i_cont and "</div>" in _zwischen,
       "Heimatplatz liegt AUSSERHALB von #profiles-container")
pruefe("display: none" in HTML[i_box:i_box + 120], "das Panel startet geschlossen")

# Das Panel wird KIND der angeklickten Profilkarte.
pruefe("karte.appendChild(box)" in JS,
       "das Panel haengt IM Container des jeweiligen Profils")
pruefe("classList.add('is-caps')" in JS, "die Karte wird markiert")
# Die 340-px-Begrenzung der Liste MUSS dafuer aufgehoben werden, sonst waere das
# Panel in einem Guckloch (der gemeldete Zustand).
# d) Die Profilliste hat KEINE Hoehenbegrenzung und keinen eigenen Scrollbalken
# mehr (Vorgabe des Nutzers, 28 Profile): alle Container sind sichtbar.
# Auf die DEKLARATION pruefen, nicht auf das Wort: der Kommentar daneben nennt
# `max-height: 340px` als das, was entfernt wurde (dieselbe Falle wie zuvor beim
# scrollTo-Waechter).
_pl = CSS[CSS.index(".profiles-list {"):CSS.index(".profiles-list::-webkit")]
_pl_code = re.sub(r"/\*.*?\*/", "", _pl, flags=re.S)
pruefe("max-height:" not in _pl_code and "overflow-y:" not in _pl_code,
       "die Profilliste scrollt nicht mehr selbst",
       _pl_code.replace("\n", " ")[:120])
pruefe("has-caps" not in CSS and "has-caps" not in JS,
       "der Behelf gegen das alte max-height ist restlos entfernt")
pruefe("if (!_home) _home =" in JS,
       "Heimatplatz wird NUR beim ersten Verschieben gemerkt")
pruefe("_offenFuer === p.id" in JS,
       "zweiter Klick auf dasselbe Profil schliesst (Umschalter)")
pruefe("is-caps" in JS and "is-caps" in CSS,
       "die offene Karte wird abgesetzt (Zuordnung erkennbar)")
pruefe("flex-wrap: wrap" in CSS and ".profile-card > .model-caps-box" in CSS,
       ".profile-card ist Flex – das Panel braucht eine eigene Zeile")

pruefe('model_caps.js?v=' in HTML, "Skript eingebunden")
pruefe(HTML.index('model_caps.js?v=') < HTML.index('js/app.js?v='),
       "model_caps.js VOR app.js")

# ── Das Scrollen beim Oeffnen (gemeldet 2026-08-11) ─────────────────────────
pruefe("function sichtbarMachen" in JS and "function scrollElternteil" in JS,
       "Scroll-Logik vorhanden")
pruefe("overflowY" in JS and "scrollHeight > p.clientHeight" in JS,
       "der Scroll-Container wird GESUCHT (Vollbild-Modus scrollt das Fenster)")
# Der Kommentar BESCHREIBT den alten Fehler (`scrollTo(0, scrollHeight)`) – ein
# Muster ueber die Rohdatei trifft ihn. Deshalb ohne Kommentare pruefen.
JS_CODE = re.sub(r"/\*.*?\*/", "", JS, flags=re.S)
JS_CODE = re.sub(r"^\s*//.*$", "", JS_CODE, flags=re.M)
pruefe("scrollTo(0" not in JS_CODE and "document.body.scrollHeight" not in JS_CODE,
       "KEIN Sprung ans Seitenende (der Fehler der /wissen-Vorschau)")
pruefe("Math.min(noetig, spielraum)" in JS and "bezug.top - oben" in JS,
       "gedeckelt an der OBERKANTE DER KARTE (sonst fehlt der Bezug)")
pruefe("if (noetig <= 0) return" in JS,
       "schon sichtbar -> kein Scrollen")
pruefe(JS_CODE.count("        sichtbarMachen(box);") == 2,
       "nachgescrollt wird ZWEIMAL: Ladehinweis und fertiges Panel",
       str(JS_CODE.count("        sichtbarMachen(box);")))
# Waechter gegen die eigene Regression: beim Block-Ersatz stand `meldung` zweimal
# im Modul (die zweite ueberschrieb die erste – toter Code, den nur das Zaehlen
# findet). Merkregel wie bei `record_task_image`: nach einem Umbau ZAEHLEN.
for _f in ("meldung", "rendern", "platziere", "fuerProfil", "probe", "heim", "zu"):
    pruefe(len(re.findall(r"\n    (?:async )?function " + _f + r"\(", JS)) == 1,
           f"{_f}() ist genau einmal definiert")
pruefe("requestAnimationFrame" in JS,
       "gemessen wird im naechsten Frame (vorher steht die neue Hoehe nicht)")
pruefe("behavior: 'smooth'" in JS,
       "sanftes Scrollen – die Bewegung IST die Rueckmeldung")

keys = ["caps.btn_title", "caps.no_model_profile", "caps.legend_probed", "caps.text", "caps.vision", "caps.tools",
        "caps.thinking", "caps.image", "caps.embedding", "caps.audio",
        "caps.unknown_hint", "caps.probing",
        "caps.by_probe", "caps.loading", "caps.no_model", "caps.failed",
        "caps.context", "caps.output", "caps.tokens", "caps.params",
        "caps.quant", "caps.family", "caps.server", "caps.raw", "caps.source"]
fehlend = [k for k in keys if I18N.count("'" + k + "'") != 2]
pruefe(not fehlend, f"alle {len(keys)} i18n-Schluessel in DE UND EN",
       ", ".join(fehlend))

# CSS: keine harten Farben, Zeichen UND Farbe tragen die Aussage
blk = CSS[CSS.index("/* ── Modell-Fähigkeiten"):]
pruefe("var(--success" in blk and "var(--danger" in blk,
       "Farben aus Theme-Variablen")
pruefe(".mc-probe-btn" not in CSS and ".mc-probing" in blk,
       "kein Knopf-Stil mehr; stattdessen der Status der automatischen Probe")
pruefe("grid-template-columns" in blk, "zweispaltige Anzeige der sieben Zeilen")

# XSS: Fremdtext (Modellname/Beschreibung vom Anbieter) wird escaped
pruefe(JS.count("esc(") >= 8 and "innerHTML" in JS,
       "alle Fremdtexte laufen durch esc()")
pruefe("esc(d.anzeige_name" in JS and "esc(d.beschreibung)" in JS,
       "Anzeigename und Beschreibung werden escaped")


print(f"\n{'=' * 70}\nErgebnis: {_ok} ok, {_fail} fehlgeschlagen")
sys.exit(1 if _fail else 0)
