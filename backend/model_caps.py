"""Faehigkeiten eines LLM-Profils ermitteln – Metadaten und echte Proben.

WOFUER
------
Im Profil-Formular (*Einstellungen → KI & System → LLM-Profile*) sagt ein
ⓘ-Knopf, was das eingestellte Modell kann: Text, Bilder verstehen (Vision),
Werkzeug-Aufrufe, Denkmodus, Bilder erzeugen, Einbettungen, Audio – dazu
Kontextfenster und Modellgroesse.

WIE GUT DAS GEHT, HAENGT AM ANBIETER (auf DEV gemessen, nicht geschaetzt):

| Quelle | liefert |
|---|---|
| Google ``/v1beta/models`` | ``supportedGenerationMethods`` (generateContent, embedContent, predict, bidiGenerateContent), ``inputTokenLimit``/``outputTokenLimit``, ``thinking``, Anzeigename, Beschreibung |
| Ollama ``/api/show`` | ``capabilities: [completion, vision, tools, thinking]`` – genau die Frage, plus ``details`` (Familie, 31.3B, Q4_K_M) und ``model_info`` (context_length 262144) |
| vLLM ``/v1/models`` | NUR ``max_model_len`` und ``owned_by`` – **keine** Faehigkeiten |
| OpenRouter ``/v1/models`` | ``architecture.input_modalities``/``output_modalities``, ``supported_parameters``, ``context_length`` |
| Anthropic ``/v1/models`` | nur ``id``/``display_name`` – keine Faehigkeiten |

DIE WICHTIGSTE REGEL: ``None`` heisst "nicht ermittelbar" und wird als solches
angezeigt – NIEMALS als "nein". Ein vLLM-Server verraet nichts ueber Vision;
daraus "kann keine Bilder lesen" zu machen waere eine Behauptung ueber etwas,
das gar nicht abgefragt wurde. Genau diese Sorte Anzeige hat in diesem Projekt
schon mehrfach Stunden gekostet (Trenner "Neue Sitzung", Audit-Filter,
leerer Profil-Umschalter).

Fuer die Faelle, in denen die Metadaten schweigen, gibt es die PROBE
(``proben()``): ein winziger echter Aufruf pro Frage. Das ist der einzige
Beweis, kostet aber Tokens – deshalb ein eigener Knopf und keine Automatik.

Was Jarvis von den Faehigkeiten TATSAECHLICH nutzt, sagt ``jarvis_hinweise()``.
Das ist nicht dasselbe: ein Modell kann laut Anbieter Audio ausgeben, Jarvis
benutzt dafuer aber die System-Sprachausgabe – und TTS/STT haengen hier
ueberhaupt nicht am LLM-Profil.
"""

from __future__ import annotations

import base64
import json

import httpx

from backend.llm import clean_api_key, scrub_secrets

# 1x1 PNG (weiss) – kleinste zulaessige Bildeingabe fuer die Vision-Probe.
_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==")

_TIMEOUT = httpx.Timeout(20.0, connect=6.0)

# Fragen, die die Oberflaeche anzeigt. Reihenfolge = Anzeigereihenfolge.
FRAGEN = ("text", "vision", "tools", "thinking", "bild", "embedding", "audio")


def _leer() -> dict:
    return {f: None for f in FRAGEN}


def _ist_bildmodell(name: str) -> bool:
    """Erzeugt das Modell Bilder? Am Namen erkennbar, nicht an der Methode.

    ``predict`` steht im Google-Konto auch bei Nicht-Bildmodellen (Embedding-
    Varianten). Umgekehrt kommt ``imagen-4.0-generate-001`` nur mit ``predict``.
    Dieselbe Namensregel benutzt ``llm.GeminiProvider.generate_image`` – wer sie
    hier aendert, muss sie dort mitaendern.
    """
    n = (name or "").lower()
    return ("imagen" in n or "-image" in n or "dall-e" in n or "flux" in n
            or "stable-diffusion" in n or "sdxl" in n)


async def ermitteln(provider: str, api_url: str = "", api_key: str = "",
                    model: str = "", auth_method: str = "api_key",
                    session_key: str = "") -> dict:
    """Metadaten-Abfrage. Kostet keine Tokens, veraendert nichts."""
    api_url = (api_url or "").strip().rstrip("/")
    api_key = clean_api_key(api_key)          # siehe llm.clean_api_key
    session_key = clean_api_key(session_key)
    key = session_key if (auth_method == "session" and session_key) else api_key
    model = (model or "").strip()

    erg = {
        "ok": True, "quelle": "", "modell": model, "anzeige_name": "",
        "beschreibung": "", "faehigkeiten": _leer(), "grenzen": {},
        "roh": [], "hinweise": [],
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            if provider == "google":
                await _aus_google(c, key, model, erg)
            elif provider == "openrouter":
                await _aus_openrouter(c, model, erg)
            elif provider in ("anthropic", "anthropic_session"):
                await _aus_anthropic(c, key, model, erg)
            elif provider == "openai_compatible":
                await _aus_openai_kompatibel(c, api_url, key, model, erg)
            else:
                erg["ok"] = False
                erg["hinweise"].append(f"Unbekannter Anbieter: {provider}")
    except httpx.ConnectError as e:
        erg["ok"] = False
        erg["hinweise"].append(f"Verbindung fehlgeschlagen: {scrub_secrets(str(e), key)}")
    except httpx.TimeoutException:
        erg["ok"] = False
        erg["hinweise"].append("Zeitüberschreitung beim Abruf der Modellliste")
    except Exception as e:  # noqa: BLE001
        erg["ok"] = False
        erg["hinweise"].append(scrub_secrets(f"{type(e).__name__}: {e}", key))

    erg["jarvis"] = jarvis_hinweise(erg["faehigkeiten"], provider, model)
    return erg


# ─── Google ──────────────────────────────────────────────────────────────────
async def _aus_google(c, key: str, model: str, erg: dict) -> None:
    if not key:
        erg["ok"] = False
        erg["hinweise"].append("API-Key fehlt")
        return
    r = await c.get("https://generativelanguage.googleapis.com/v1beta/models",
                    params={"key": key, "pageSize": 200})
    if r.status_code >= 400:
        erg["ok"] = False
        erg["hinweise"].append(f"Gemini HTTP {r.status_code}")
        return
    erg["quelle"] = "google-models"
    alle = r.json().get("models", [])
    kurz = (model or "").replace("models/", "")
    treffer = next((m for m in alle
                    if m.get("name", "").replace("models/", "") == kurz), None)
    if not treffer:
        erg["hinweise"].append(
            f"Das Modell '{kurz}' steht NICHT in der Liste des Kontos "
            f"({len(alle)} Modelle) – der Name ist vermutlich falsch oder "
            f"abgekündigt. Modelle abrufen (🔍) zeigt die verfügbaren.")
        return
    meth = treffer.get("supportedGenerationMethods", []) or []
    f = erg["faehigkeiten"]
    f["text"] = "generateContent" in meth
    f["embedding"] = "embedContent" in meth
    # Live-API (bidiGenerateContent) und die -tts-Modelle koennen Audio ausgeben.
    f["audio"] = ("bidiGenerateContent" in meth) or ("-tts" in kurz.lower())
    f["bild"] = _ist_bildmodell(kurz) and bool(
        {"predict", "predictLongRunning", "generateContent"} & set(meth))
    # `thinking` ist ein echtes Feld der API – kein Rateschluss.
    if "thinking" in treffer:
        f["thinking"] = bool(treffer.get("thinking"))
    # Vision gibt die Google-API NICHT her (alle gemini-* sind multimodal, aber
    # es steht nirgends). Bewusst None: die Probe kann es beantworten.
    erg["anzeige_name"] = treffer.get("displayName", "") or ""
    erg["beschreibung"] = treffer.get("description", "") or ""
    erg["grenzen"] = {
        "kontext_tokens": treffer.get("inputTokenLimit"),
        "ausgabe_tokens": treffer.get("outputTokenLimit"),
        "temperature_max": treffer.get("maxTemperature"),
    }
    erg["roh"] = sorted(meth)
    if f["text"] is False and f["embedding"]:
        erg["hinweise"].append(
            "Das ist ein EINBETTUNGS-Modell (embedContent) – es kann nicht "
            "chatten und ist als Chat-Profil nicht brauchbar.")


# ─── OpenRouter ──────────────────────────────────────────────────────────────
async def _aus_openrouter(c, model: str, erg: dict) -> None:
    r = await c.get("https://openrouter.ai/api/v1/models")
    if r.status_code >= 400:
        erg["ok"] = False
        erg["hinweise"].append(f"OpenRouter HTTP {r.status_code}")
        return
    erg["quelle"] = "openrouter-models"
    alle = r.json().get("data", [])
    treffer = next((m for m in alle if m.get("id") == model), None)
    if not treffer:
        erg["hinweise"].append(f"Das Modell '{model}' steht nicht in der "
                               f"OpenRouter-Liste ({len(alle)} Modelle).")
        return
    arch = treffer.get("architecture") or {}
    ein = [str(x).lower() for x in (arch.get("input_modalities") or [])]
    aus = [str(x).lower() for x in (arch.get("output_modalities") or [])]
    params = [str(x).lower() for x in (treffer.get("supported_parameters") or [])]
    f = erg["faehigkeiten"]
    f["text"] = "text" in aus or not aus
    f["vision"] = "image" in ein
    f["bild"] = "image" in aus
    f["audio"] = ("audio" in ein) or ("audio" in aus)
    if params:
        f["tools"] = "tools" in params or "tool_choice" in params
        f["thinking"] = "reasoning" in params or "include_reasoning" in params
    erg["anzeige_name"] = treffer.get("name", "") or ""
    erg["beschreibung"] = (treffer.get("description", "") or "")[:400]
    erg["grenzen"] = {"kontext_tokens": treffer.get("context_length")}
    erg["roh"] = sorted(set(ein + ["→"] + aus)) if (ein or aus) else []


# ─── Anthropic ───────────────────────────────────────────────────────────────
async def _aus_anthropic(c, key: str, model: str, erg: dict) -> None:
    erg["quelle"] = "anthropic-models"
    if key:
        r = await c.get("https://api.anthropic.com/v1/models",
                        headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
        if r.status_code < 400:
            treffer = next((m for m in r.json().get("data", [])
                            if m.get("id") == model), None)
            if treffer:
                erg["anzeige_name"] = treffer.get("display_name", "") or ""
            else:
                erg["hinweise"].append(
                    f"Das Modell '{model}' steht nicht in der Liste des Kontos.")
        else:
            erg["hinweise"].append(f"Anthropic HTTP {r.status_code}")
    # Die Anthropic-Modellliste nennt KEINE Faehigkeiten. Nur das, was das
    # Projekt selbst sicher weiss, wird gesetzt – der Rest bleibt None.
    erg["faehigkeiten"]["text"] = True
    erg["hinweise"].append(
        "Die Anthropic-Modellliste nennt keine Fähigkeiten (nur Id und "
        "Anzeigename). Für Vision, Werkzeuge und Denkmodus hilft die Probe.")


# ─── OpenAI-kompatibel: Ollama, vLLM, LM Studio, llama.cpp … ─────────────────
async def _aus_openai_kompatibel(c, api_url: str, key: str, model: str,
                                 erg: dict) -> None:
    kopf = {"Authorization": f"Bearer {key}"} if key else {}
    basis = api_url[:-3].rstrip("/") if api_url.endswith("/v1") else api_url

    # 1) Ollama zuerst: nur dort gibt es echte `capabilities`.
    try:
        r = await c.post(f"{basis}/api/show", json={"model": model}, headers=kopf)
        if r.status_code < 400:
            j = r.json()
            caps = [str(x).lower() for x in (j.get("capabilities") or [])]
            if caps:
                erg["quelle"] = "ollama-show"
                f = erg["faehigkeiten"]
                f["text"] = "completion" in caps
                f["vision"] = "vision" in caps
                f["tools"] = "tools" in caps
                f["thinking"] = "thinking" in caps
                f["embedding"] = "embedding" in caps
                # Bild-ERZEUGUNG kann Ollama nicht – das ist eine Aussage, keine
                # Luecke: die Capability-Liste ist vollstaendig.
                f["bild"] = False
                f["audio"] = False
                det = j.get("details") or {}
                mi = j.get("model_info") or {}
                ctx = next((v for k, v in mi.items()
                            if k.endswith(".context_length")), None)
                erg["grenzen"] = {
                    "kontext_tokens": ctx,
                    "parameter": det.get("parameter_size"),
                    "quantisierung": det.get("quantization_level"),
                    "familie": det.get("family"),
                }
                erg["roh"] = sorted(caps)
                return
    except Exception:  # noqa: BLE001
        pass  # kein Ollama – normal, weiter mit /v1/models

    # 2) /v1/models: vLLM liefert `max_model_len`, sonst fast nichts.
    r = await c.get(f"{api_url}/models", headers=kopf)
    if r.status_code >= 400:
        erg["ok"] = False
        erg["hinweise"].append(f"HTTP {r.status_code} von {api_url}/models")
        return
    daten = r.json().get("data", []) or []
    treffer = next((m for m in daten if m.get("id") == model), None)
    erg["quelle"] = "openai-models"
    if treffer is None:
        erg["hinweise"].append(
            f"Das Modell '{model}' steht nicht in der Liste des Servers "
            f"({len(daten)} Modell(e): "
            + ", ".join(str(m.get('id')) for m in daten[:5]) + ").")
        return
    # Der Server antwortet auf /v1/models und nennt das Modell – Chat geht.
    erg["faehigkeiten"]["text"] = True
    if treffer.get("max_model_len"):
        erg["grenzen"]["kontext_tokens"] = treffer.get("max_model_len")
    if treffer.get("owned_by"):
        erg["grenzen"]["server"] = treffer.get("owned_by")
    erg["hinweise"].append(
        "Dieser Server (OpenAI-kompatibel) nennt in der Modellliste KEINE "
        "Fähigkeiten – bei vLLM gibt es nur die Kontextlänge. Vision, "
        "Werkzeug-Aufrufe und Denkmodus lassen sich hier nur mit der Probe "
        "feststellen.")


# ─── Echte Proben: der einzige Beweis ────────────────────────────────────────
async def proben(provider: str, api_url: str = "", api_key: str = "",
                 model: str = "", auth_method: str = "api_key",
                 session_key: str = "", welche: tuple = ("vision", "tools")) -> dict:
    """Winzige echte Anfragen. Kostet Tokens – deshalb nur auf Knopfdruck.

    Bewusst NUR fuer `openai_compatible`, `google` und `anthropic` gebaut und
    bewusst nur fuer `vision` und `tools`: das sind die beiden Fragen, bei denen
    die Metadaten am haeufigsten schweigen UND die Antwort im Betrieb einen
    Unterschied macht (Bildanhang im Chat, Werkzeug-Aufrufe des Agenten).

    Ein Fehlschlag wird als `False` gewertet, ein Transportfehler als `None`:
    "Server nicht erreichbar" ist keine Aussage ueber das Modell.
    """
    api_url = (api_url or "").strip().rstrip("/")
    api_key = clean_api_key(api_key)
    session_key = clean_api_key(session_key)
    key = session_key if (auth_method == "session" and session_key) else api_key
    erg = {"ok": True, "faehigkeiten": {}, "hinweise": []}

    b64 = base64.b64encode(_PIXEL_PNG).decode()
    for frage in welche:
        try:
            if provider == "google":
                treffer = await _probe_google(key, model, frage, b64)
            elif provider in ("anthropic", "anthropic_session"):
                treffer = await _probe_anthropic(key, model, frage, b64)
            elif provider == "openai_compatible":
                treffer = await _probe_openai(api_url, key, model, frage, b64)
            else:
                treffer = None
                erg["hinweise"].append(f"Probe für '{provider}' nicht möglich.")
            erg["faehigkeiten"][frage] = treffer
        except httpx.HTTPError as e:
            erg["faehigkeiten"][frage] = None
            erg["hinweise"].append(
                f"{frage}: nicht prüfbar ({scrub_secrets(str(e), key)[:100]})")
        except Exception as e:  # noqa: BLE001
            erg["faehigkeiten"][frage] = None
            erg["hinweise"].append(f"{frage}: {type(e).__name__}")
    return erg


_TOOL = {
    "type": "function",
    "function": {
        "name": "jarvis_probe",
        "description": "Testwerkzeug",
        "parameters": {"type": "object",
                       "properties": {"x": {"type": "string"}},
                       "required": ["x"]},
    },
}


async def _probe_openai(api_url: str, key: str, model: str, frage: str, b64: str):
    kopf = {"Content-Type": "application/json"}
    if key:
        kopf["Authorization"] = f"Bearer {key}"
    if frage == "vision":
        payload = {"model": model, "max_tokens": 1, "messages": [{
            "role": "user", "content": [
                {"type": "text", "text": "."},
                {"type": "image_url",
                 "image_url": {"url": "data:image/png;base64," + b64}}]}]}
    elif frage == "tools":
        payload = {"model": model, "max_tokens": 1, "tools": [_TOOL],
                   "messages": [{"role": "user", "content": "."}]}
    else:
        return None
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.post(f"{api_url}/chat/completions", json=payload, headers=kopf)
    # 400/422 = der Server lehnt genau dieses Merkmal ab → kann er nicht.
    # 5xx/401/404 sagen nichts ueber das Merkmal.
    if r.status_code < 300:
        return True
    if r.status_code in (400, 422, 415):
        return False
    return None


async def _probe_google(key: str, model: str, frage: str, b64: str):
    if not key:
        return None
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent")
    if frage == "vision":
        body = {"contents": [{"parts": [
            {"text": "."},
            {"inline_data": {"mime_type": "image/png", "data": b64}}]}],
            "generationConfig": {"maxOutputTokens": 1}}
    elif frage == "tools":
        body = {"contents": [{"parts": [{"text": "."}]}],
                "tools": [{"function_declarations": [{
                    "name": "jarvis_probe", "description": "Testwerkzeug",
                    "parameters": {"type": "OBJECT",
                                   "properties": {"x": {"type": "STRING"}}}}]}],
                "generationConfig": {"maxOutputTokens": 1}}
    else:
        return None
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.post(url, params={"key": key}, json=body)
    if r.status_code < 300:
        return True
    if r.status_code in (400, 422):
        return False
    return None


async def _probe_anthropic(key: str, model: str, frage: str, b64: str):
    if not key:
        return None
    kopf = {"x-api-key": key, "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"}
    if frage == "vision":
        body = {"model": model, "max_tokens": 1, "messages": [{
            "role": "user", "content": [
                {"type": "text", "text": "."},
                {"type": "image", "source": {"type": "base64",
                                             "media_type": "image/png",
                                             "data": b64}}]}]}
    elif frage == "tools":
        body = {"model": model, "max_tokens": 1,
                "tools": [{"name": "jarvis_probe", "description": "Testwerkzeug",
                           "input_schema": {"type": "object",
                                            "properties": {"x": {"type": "string"}}}}],
                "messages": [{"role": "user", "content": "."}]}
    else:
        return None
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.post("https://api.anthropic.com/v1/messages",
                         json=body, headers=kopf)
    if r.status_code < 300:
        return True
    if r.status_code in (400, 422):
        return False
    return None


# ─── Was Jarvis davon tatsaechlich nutzt ─────────────────────────────────────
def jarvis_hinweise(f: dict, provider: str, model: str = "") -> list:
    """Uebersetzt Faehigkeiten in Aussagen ueber DIESES System.

    Notwendig, weil "das Modell kann X" und "Jarvis benutzt X" zwei verschiedene
    Dinge sind. Ohne diesen Teil wuerde die Anzeige Erwartungen wecken, die das
    System nicht erfuellt – dieselbe Fehlerklasse wie ein Prompt, der ein
    Werkzeug verspricht, das es nicht gibt.
    """
    h = []
    # Bildgenerierung laeuft in Jarvis NUR ueber den Google-Provider
    # (llm.GeminiProvider.generate_image); andere Provider haben keinen Weg.
    if provider != "google":
        h.append({"art": "info", "text":
                  "Bilder ERZEUGEN (generate_image) kann Jarvis derzeit nur mit "
                  "einem Google-Profil. Für Bildaufträge eine Rolle mit einem "
                  "Google-Bildmodell hinterlegen (Einstellungen → Orchestrator)."})
    elif f.get("bild"):
        h.append({"art": "ok", "text":
                  "Als Bildmodell nutzbar – z.B. als Profil einer Rolle "
                  "'image_builder' (Einstellungen → Orchestrator)."})
    if f.get("text") is False:
        h.append({"art": "warn", "text":
                  "Dieses Modell kann nicht chatten – als Chat-Profil unbrauchbar."})
    if f.get("tools") is False:
        h.append({"art": "warn", "text":
                  "Ohne Werkzeug-Aufrufe kann der Agent keine Tools nutzen. "
                  "Behelf: im Profil 'Prompt-basiertes Tool-Calling' einschalten."})
    if f.get("thinking"):
        h.append({"art": "info", "text":
                  "Denkmodus vorhanden – die Denktiefe steuert das Profilfeld "
                  "'reasoning_effort' (off/low/medium/high/max)."})
    if f.get("vision") is False:
        h.append({"art": "warn", "text":
                  "Bildanhänge im Chat kann dieses Modell nicht auswerten."})
    return h
