"""Jarvis LLM Provider Abstraktionsschicht."""

import asyncio
import json
import re
import httpx
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Optional, List, Any
from google import genai
from google.genai import types


@dataclass
class LLMPart:
    text: Optional[str] = None
    function_call: Optional[Any] = None


@dataclass
class LLMResponse:
    parts: List[LLMPart]
    raw: Any
    usage: dict = None  # {"input_tokens": N, "output_tokens": M}


class MockFC:
    """Einheitliches Function-Call Objekt (für alle Non-Gemini-Provider)."""
    def __init__(self, name, args):
        self.name = name
        self.args = args


class ImageGenNotSupported(Exception):
    """Wird geworfen, wenn das aktive Profil keine Bildgenerierung beherrscht."""
    def __init__(self, label: str = "Das aktive LLM-Profil"):
        self.label = label
        super().__init__(f"{label} kann keine Bilder generieren")


class LLMProvider(ABC):
    # Label fuer Fehlermeldungen (z.B. "Das aktive Google-Profil")
    image_label: str = "Das aktive LLM-Profil"

    @abstractmethod
    async def generate_response(self, model: str, system_prompt: str, contents: list,
                                tools: list = None, reasoning_effort: str | None = None,
                                temperature=None) -> LLMResponse:
        """reasoning_effort: Stufe aus REASONING_LEVELS oder None (Provider-Standard).
        temperature: Zahl, "auto" (= Feld weglassen) oder None (= Standard 0.2).

        Provider, die einen der Werte nicht kennen, nehmen ihn an und ignorieren ihn –
        so bleibt der Aufruf im Agent-Loop fuer alle Provider identisch.
        """
        pass

    async def generate_image(self, model: str, prompt: str) -> bytes:
        """Generiert ein Bild (PNG-Bytes) aus einem Text-Prompt.

        Default: NICHT unterstuetzt – der jeweilige Provider muss dies ueberschreiben,
        wenn er Bildgenerierung kann. Es wird NIEMALS auf ein anderes Profil gewechselt.
        """
        raise ImageGenNotSupported(self.image_label)


def _parse_sse_to_completion(sse_text: str) -> dict:
    """Konvertiert einen SSE (Server-Sent Events)-Stream in ein synthetisches non-stream JSON-Objekt.
    Open WebUI antwortet manchmal als Stream auch wenn stream:false gesetzt ist."""
    content = ""
    tool_calls: dict = {}
    finish_reason = "stop"
    for line in sse_text.splitlines():
        if not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        if raw == "[DONE]":
            break
        try:
            chunk = json.loads(raw)
        except Exception:
            continue
        choice = (chunk.get("choices") or [{}])[0]
        delta = choice.get("delta", {})
        if delta.get("content"):
            content += delta["content"]
        finish_reason = choice.get("finish_reason") or finish_reason
        # Tool-Call-Deltas zusammensetzen
        for tc in delta.get("tool_calls") or []:
            idx = tc.get("index", 0)
            if idx not in tool_calls:
                tool_calls[idx] = {"id": tc.get("id", ""), "type": "function",
                                   "function": {"name": "", "arguments": ""}}
            if tc.get("id"):
                tool_calls[idx]["id"] = tc["id"]
            fn = tc.get("function", {})
            if fn.get("name"):
                tool_calls[idx]["function"]["name"] += fn["name"]
            if fn.get("arguments"):
                tool_calls[idx]["function"]["arguments"] += fn["arguments"]
    message: dict = {"role": "assistant", "content": content or None}
    if tool_calls:
        message["tool_calls"] = list(tool_calls.values())
    return {"choices": [{"message": message, "finish_reason": finish_reason}]}


# Shared httpx.AsyncClient mit Connection-Pooling (vermeidet neue Verbindung pro Request)
_shared_client: httpx.AsyncClient | None = None
_client_lock = asyncio.Lock()


def _llm_timeout() -> "httpx.Timeout":
    """Read/Total-Timeout fuer LLM-Anfragen aus der (zur Laufzeit aenderbaren)
    Konfiguration. connect/write bleiben fest; nur die eigentliche Antwortzeit
    (read/total) ist ueber Einstellungen -> LLM anpassbar."""
    try:
        from backend.config import config
        total = max(10, min(int(getattr(config, "LLM_TIMEOUT", 180) or 180), 1800))
    except Exception:
        total = 180
    return httpx.Timeout(float(total), connect=10.0, read=float(total), write=30.0)


def _llm_max_tokens() -> int:
    """Obergrenze fuer die Antwortlaenge (max_tokens) OpenAI-kompatibler Aufrufe.

    Wichtig bei Reasoning-Modellen (z.B. Qwen3): ohne Cap kann der Server einen
    sehr langen Gedankengang generieren und dabei den Read-Timeout reissen. Der
    Wert ist ueber Einstellungen -> LLM (config.LLM_MAX_TOKENS) anpassbar; der
    Default begrenzt die Generierung auf ein Mass, das i.d.R. unter dem Timeout
    bleibt. Das Feld existiert seit 2026-07-27 wirklich in config.py – vorher
    griff hier immer der getattr-Default 8192."""
    try:
        from backend.config import config
        return max(256, min(int(getattr(config, "LLM_MAX_TOKENS", 8192) or 8192), 131072))
    except Exception:
        return 8192


# Profil-Sonderwert UND Standard: Parameter gar nicht senden, der Anbieter
# entscheidet. Bis 2026-07-27 war stattdessen 0.2 an vier Stellen hart codiert;
# seither ist "auto" der Standard, damit aktuelle Claude-Modelle nicht in den
# 400-Fallback laufen (sie lehnen Sampling-Parameter ab).
TEMPERATURE_AUTO = "auto"
# Nur noch als benannte Konstante fuer Aufrufer, die bewusst den alten Wert
# wollen – NICHT mehr der Fallback fuer leere Angaben.
LEGACY_TEMPERATURE = 0.2
# Interner Default der Provider-Hilfsmethoden: None = Feld weglassen.
DEFAULT_TEMPERATURE = None


def clean_api_key(key) -> str:
    """Normalisiert einen API-Key/Session-Key fuer die Verwendung in einem HTTP-Header.

    Entfernt Rand-Leerzeichen (auch Zeilenumbrueche, wie sie beim Kopieren aus
    einer Mail oder einem Terminal mitkommen), verwirft danach Steuerzeichen und
    Nicht-ASCII.

    **Warum das noetig ist:** Ein Header-Wert darf laut RFC 9110 kein
    fuehrendes/abschliessendes Leerzeichen tragen. httpx/h11 pruefen das und
    werfen ``LocalProtocolError: Illegal header value b'Bearer sk-… '`` – ein
    einziges mitkopiertes Leerzeichen im Key laesst so JEDE Anfrage des Profils
    scheitern, mit einer Meldung, die nach einem Serverfehler klingt. Ein
    Zeilenumbruch MITTEN im Wert waere sogar eine Header-Injection, deshalb
    werden Steuerzeichen entfernt und nicht nur die Raender getrimmt.

    Muss an JEDER Stelle angewandt werden, die einen Key in einen Header
    schreibt: Provider-Header, Verbindungstest UND Modell-Abruf – nicht nur beim
    Speichern, sonst bleiben bereits gespeicherte Keys kaputt.
    """
    if not key or not isinstance(key, str):
        return ""
    return "".join(c for c in key.strip() if 32 <= ord(c) < 127)


def scrub_secrets(text, *secrets) -> str:
    """Ersetzt Geheimnisse in einem Fehlertext durch ``***``.

    Fehlermeldungen der HTTP-Schicht zitieren den beanstandeten Header-Wert
    WOERTLICH (``Illegal header value b'Bearer sk-…'``) und landen ueber
    ``str(e)`` in der Oberflaeche und im Journal – der API-Key waere damit
    sichtbar. Beide Formen werden ersetzt: der Rohwert und die um Rand-/
    Steuerzeichen bereinigte Fassung.
    """
    out = str(text)
    seen = set()
    for s in secrets:
        if not s or not isinstance(s, str):
            continue
        for variant in (s, s.strip(), clean_api_key(s)):
            if len(variant) >= 8 and variant not in seen:
                seen.add(variant)
                out = out.replace(variant, "***")
    return out


def _resolve_temperature(value) -> float | None:
    """Bringt eine Temperature-Angabe auf den Wert, der an den Provider geht.

    Rueckgabe None bedeutet ausdruecklich "Feld weglassen" – nicht 0. Das ist
    seit 2026-07-27 der Standard fuer leere/fehlende Angaben und der Weg fuer
    aktuelle Claude-Modelle (Opus 5/4.8/4.7, Sonnet 5, Fable 5), die
    Sampling-Parameter mit HTTP 400 ablehnen.

    ACHTUNG Nebenwirkung: ohne Feld gilt der Anbieter-Default, und der liegt bei
    vielen OpenAI-kompatiblen Servern und bei Gemini deutlich ueber 0.2. Wer
    verlaessliche Tool-Aufrufe braucht, traegt im Profil eine Zahl ein.
    """
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip().lower()
        if not s or s == TEMPERATURE_AUTO:
            return None
        try:
            value = float(s.replace(",", "."))
        except ValueError:
            return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:                     # NaN
        return None
    return max(0.0, min(f, 2.0))


# ═══════════════════════════════════════════════════════════════════
#  Reasoning-Steuerung (pro Anfrage)
# ═══════════════════════════════════════════════════════════════════
#
# Jeder Provider nennt die Denktiefe anders (Anthropic: thinking + effort,
# OpenAI: reasoning_effort, OpenRouter: reasoning.effort, Gemini:
# thinking_budget in Token). Nach aussen – WebSocket-Feld `reasoning_effort`,
# Profil-Feld, globale Einstellung – gilt deshalb EINE providerunabhaengige
# Stufenleiter; die Uebersetzung passiert je Provider unten.

REASONING_LEVELS = ("off", "low", "medium", "high", "max")

# Schreibweisen, die von aussen akzeptiert werden. Absichtlich tolerant (DE/EN,
# Synonyme), damit API-Aufrufer die Stufen nicht raten muessen.
_EFFORT_ALIASES = {
    "off": "off", "none": "off", "disabled": "off", "aus": "off", "0": "off",
    "minimal": "low", "min": "low", "low": "low", "niedrig": "low",
    "medium": "medium", "mid": "medium", "normal": "medium", "mittel": "medium",
    "high": "high", "hoch": "high",
    # xhigh liegt bei Anthropic zwischen high und max; hier auf max abgebildet,
    # damit die Stufenleiter providerunabhaengig bleibt.
    "xhigh": "max", "x_high": "max", "very_high": "max", "max": "max", "maximum": "max",
}

# Gemini rechnet in Denk-Token statt in Stufen.
_GEMINI_THINKING_BUDGET = {"off": 0, "low": 1024, "medium": 4096, "high": 12288, "max": 24576}

# OpenAI-kompatible Server kennen nur minimal|low|medium|high.
_OPENAI_EFFORT = {"off": "minimal", "low": "low", "medium": "medium", "high": "high", "max": "high"}

# Anthropic: output_config.effort. "max" existiert dort wirklich.
_ANTHROPIC_EFFORT = {"low": "low", "medium": "medium", "high": "high", "max": "max"}

# Ab dieser Stufe braucht Anthropic Platz zum Denken – max_tokens deckelt
# Denk- UND Antworttoken gemeinsam, ein zu kleiner Wert schneidet die Antwort ab.
_ANTHROPIC_THINKING_MIN_TOKENS = 16000


def normalize_effort(value) -> str | None:
    """Bringt eine Reasoning-Angabe auf eine kanonische Stufe aus REASONING_LEVELS.

    Rueckgabe None = keine Angabe, es gilt der Provider-Standard. Unbekannte
    Werte ergeben ebenfalls None: ein Tippfehler im API-Aufruf darf die Anfrage
    nicht mit einem Provider-400 abbrechen.
    """
    if value is None:
        return None
    s = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    if not s:
        return None
    return _EFFORT_ALIASES.get(s)


def _default_effort() -> str | None:
    """Globaler Standard aus den Einstellungen (leer = Provider-Standard)."""
    try:
        from backend.config import config
        return normalize_effort(getattr(config, "LLM_REASONING_EFFORT", "") or None)
    except Exception:
        return None


def _resolve_effort(value) -> str | None:
    """Pro-Anfrage-Wert, sonst globaler Standard."""
    return normalize_effort(value) or _default_effort()


# Fehlertext-Marker, die auf einen vom Modell/Server NICHT unterstuetzten
# Reasoning- oder Sampling-Parameter hindeuten.
_UNSUPPORTED_PARAM_MARKERS = (
    "thinking", "reasoning", "output_config", "effort", "budget_tokens",
    "temperature", "top_p", "unexpected keyword", "unknown field",
    "unrecognized", "not supported", "unsupported parameter",
    "extra inputs are not permitted", "additional properties",
)


def _is_unsupported_param_error(exc_or_text) -> bool:
    """Erkennt, ob ein Provider einen der gesetzten Zusatzparameter ablehnt.

    Aeltere Modelle kennen `thinking`/`output_config` nicht, neuere Claude-Modelle
    lehnen umgekehrt `temperature` ab (400). Statt die Anfrage scheitern zu
    lassen, wird sie einmal ohne diese Parameter wiederholt – der Nutzer bekommt
    eine Antwort ohne Feinsteuerung statt einer Fehlermeldung.
    """
    txt = str(exc_or_text).lower()
    if not ("400" in txt or "invalid" in txt or "bad request" in txt):
        return False
    return any(m in txt for m in _UNSUPPORTED_PARAM_MARKERS)


async def _get_shared_client() -> httpx.AsyncClient:
    """Gibt den shared AsyncClient zurueck (lazy init, thread-safe).

    Der Default-Timeout des Clients wird pro Anfrage ohnehin durch
    ``_get_timeout()`` ueberschrieben; hier nur als Fallback gesetzt."""
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        async with _client_lock:
            if _shared_client is None or _shared_client.is_closed:
                _shared_client = httpx.AsyncClient(
                    timeout=_llm_timeout(),
                    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                    follow_redirects=True,
                )
    return _shared_client


async def _retry_with_backoff(coro_fn, max_retries: int = 3, base_delay: float = 1.0):
    """Fuehrt eine Coroutine mit exponentiellem Backoff bei Retry-faehigen Fehlern aus."""
    for attempt in range(max_retries + 1):
        try:
            return await coro_fn()
        except Exception as e:
            # Nur bei 429/503/502 und ConnectError erneut versuchen
            # ReadTimeout NICHT retrien – bei langsamen lokalen Modellen würde das die Wartezeit vervielfachen
            retryable = False
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code in (429, 503, 502):
                retryable = True
            elif isinstance(e, httpx.ConnectError):
                retryable = True
            else:
                # Gemini SDK wirft google.genai.errors.ServerError (kein httpx) – per String prüfen
                msg = str(e)
                if any(code in msg for code in ("503", "429", "502", "UNAVAILABLE", "RESOURCE_EXHAUSTED")):
                    retryable = True

            if not retryable or attempt >= max_retries:
                raise
            delay = base_delay * (2 ** attempt)
            print(f"[LLM] Retry {attempt + 1}/{max_retries} nach {delay}s ({type(e).__name__}): {e}", flush=True)
            await asyncio.sleep(delay)
    raise RuntimeError("Retry-Limit erreicht")


def _normalize_schema(schema: dict) -> dict:
    """Konvertiert Gemini-Style Typen (OBJECT, STRING) zu JSON-Schema (object, string)."""
    if not isinstance(schema, dict):
        return schema

    result = {}
    for key, value in schema.items():
        if key == "type" and isinstance(value, str):
            result[key] = value.lower()
        elif key == "properties" and isinstance(value, dict):
            result[key] = {k: _normalize_schema(v) for k, v in value.items()}
        elif key == "items" and isinstance(value, dict):
            result[key] = _normalize_schema(value)
        else:
            result[key] = value
    return result


# ═══════════════════════════════════════════════════════════════════
#  Google Gemini (offiziell)
# ═══════════════════════════════════════════════════════════════════

class GeminiProvider(LLMProvider):
    image_label = "Das aktive Google-Profil"

    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)

    async def generate_image(self, model: str, prompt: str) -> bytes:
        """Bildgenerierung via Google Imagen – gleicher API-Key, KEIN Profilwechsel.

        Das aktive Text-Modell (z.B. gemini-2.5-flash) generiert selbst keine Bilder;
        der Google-Provider nutzt dafuer sein Bildmodell (Imagen). Schlaegt der Zugriff
        fehl (Key ohne Imagen-Freigabe), wird der Fehler nach oben gereicht.
        """
        img_models = ["imagen-3.0-generate-002", "imagen-3.0-generate-001"]

        def _call(m):
            resp = self.client.models.generate_images(
                model=m,
                prompt=prompt,
                config=types.GenerateImagesConfig(number_of_images=1),
            )
            imgs = getattr(resp, "generated_images", None) or []
            if not imgs:
                raise RuntimeError("Keine Bilddaten vom Modell erhalten")
            return imgs[0].image.image_bytes

        last_err = None
        for m in img_models:
            try:
                return await asyncio.to_thread(_call, m)
            except Exception as e:
                last_err = e
        raise RuntimeError(f"Bildgenerierung fehlgeschlagen: {last_err}")

    def _thinking_config(self, effort: str | None):
        """Uebersetzt eine Reasoning-Stufe in Geminis Token-Budget.

        Rueckgabe None = Feld weglassen (Modell entscheidet selbst).

        WICHTIG – breites except: die ThinkingConfig alter google-genai-Versionen
        kennt `thinking_budget` nicht (1.5.0 hat nur `include_thoughts`). Weil
        ThinkingConfig ein pydantic-Modell ist, kommt dann ein ValidationError und
        NICHT TypeError/AttributeError. Ein zu enges except wuerde jeden
        Gemini-Chat mit Reasoning-Vorgabe abbrechen statt die Vorgabe zu ignorieren.
        """
        if not effort:
            return None
        budget = _GEMINI_THINKING_BUDGET.get(effort)
        if budget is None:
            return None
        try:
            return types.ThinkingConfig(thinking_budget=budget)
        except Exception as exc:  # noqa: BLE001 – siehe Docstring
            print(f"[LLM] Gemini: ThinkingConfig(thinking_budget) nicht unterstuetzt "
                  f"({type(exc).__name__}) – Reasoning-Vorgabe wird ignoriert. "
                  f"Abhilfe: google-genai aktualisieren.", flush=True)
            return None

    async def generate_response(self, model: str, system_prompt: str, contents: list,
                                tools: list = None, reasoning_effort: str | None = None,
                                temperature=None) -> LLMResponse:
        gemini_tools = [types.Tool(function_declarations=tools)] if tools else None
        thinking = self._thinking_config(_resolve_effort(reasoning_effort))
        _temp = _resolve_temperature(temperature)

        # Harte Zeitgrenze: das Gemini-SDK laeuft in einem Thread OHNE eigenen
        # Timeout – ein stehengebliebener Upstream-Call wuerde den Chat sonst
        # unbegrenzt haengen lassen. wait_for wirft nach Ablauf TimeoutError
        # (nicht retry-faehig -> wird als Fehler gemeldet, Nutzer kann wiederholen).
        # config wird lokal importiert (llm.py hat keinen Modul-Import davon) –
        # ohne diese Zeile scheiterte JEDER Gemini-Aufruf mit NameError.
        from backend.config import config
        _to = max(10, min(int(getattr(config, "LLM_TIMEOUT", 180) or 180), 1800))

        def _build_config(with_thinking):
            kwargs = {
                "system_instruction": system_prompt,
                "tools": gemini_tools,
            }
            if _temp is not None:      # None = Feld weglassen (Profil "auto")
                kwargs["temperature"] = _temp
            if with_thinking is None:
                return types.GenerateContentConfig(**kwargs)
            kwargs["thinking_config"] = with_thinking
            try:
                return types.GenerateContentConfig(**kwargs)
            except Exception as exc:  # noqa: BLE001
                # Aeltere SDKs kennen das Feld thinking_config nicht (pydantic
                # ValidationError). Dann ohne Vorgabe bauen statt zu scheitern.
                print(f"[LLM] Gemini: thinking_config vom SDK nicht akzeptiert "
                      f"({type(exc).__name__}) – Vorgabe ignoriert", flush=True)
                kwargs.pop("thinking_config", None)
                return types.GenerateContentConfig(**kwargs)

        async def _call():
            try:
                resp = await asyncio.wait_for(asyncio.to_thread(
                    self.client.models.generate_content,
                    model=model,
                    contents=contents,
                    config=_build_config(thinking),
                ), timeout=_to)
            except asyncio.TimeoutError:
                raise
            except Exception as exc:
                # Nicht jedes Gemini-Modell laesst sich die Denktiefe vorgeben
                # (2.5 Pro kann Thinking z.B. nicht auf 0 setzen). Dann einmal
                # ohne thinking_config wiederholen statt den Chat abzubrechen.
                if thinking is None or not _is_unsupported_param_error(exc):
                    raise
                print(f"[LLM] Gemini {model}: thinking_config abgelehnt ({exc}) "
                      f"→ Wiederholung ohne Reasoning-Vorgabe", flush=True)
                resp = await asyncio.wait_for(asyncio.to_thread(
                    self.client.models.generate_content,
                    model=model,
                    contents=contents,
                    config=_build_config(None),
                ), timeout=_to)
            parts = []
            if resp.candidates and resp.candidates[0].content and resp.candidates[0].content.parts:
                for p in resp.candidates[0].content.parts:
                    parts.append(LLMPart(text=p.text, function_call=p.function_call))
            usage = None
            try:
                um = resp.usage_metadata
                usage = {
                    "input_tokens": getattr(um, "prompt_token_count", 0) or 0,
                    "output_tokens": getattr(um, "candidates_token_count", 0) or 0,
                }
            except Exception:
                pass
            return LLMResponse(parts=parts, raw=resp, usage=usage)

        return await _retry_with_backoff(_call)


# ═══════════════════════════════════════════════════════════════════
#  OpenAI-Kompatibel (Basis für OpenRouter + lokale LLMs)
# ═══════════════════════════════════════════════════════════════════

class OpenAICompatibleProvider(LLMProvider):
    """Basis-Provider für OpenAI-kompatible APIs (Ollama, LM Studio, vLLM etc.).

    prompt_tool_calling=True: Tools werden in den System-Prompt eingebettet und
    die Antwort per Regex auf <tool_call>…</tool_call>-Blöcke geparst.
    Nützlich für Modelle die keine native Function-Calling-API unterstützen.
    """

    def __init__(self, api_key: str = "", base_url: str = "http://localhost:11434/v1/chat/completions",
                 prompt_tool_calling: bool = False):
        self.api_key = api_key
        self.prompt_tool_calling = prompt_tool_calling
        # Automatisch /chat/completions anhängen falls noch nicht vorhanden
        url = base_url.rstrip("/")
        if not url.endswith("/chat/completions"):
            url = url + "/chat/completions"
        self.base_url = url

    def _build_headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        clean_key = clean_api_key(self.api_key)
        if clean_key:
            headers["Authorization"] = f"Bearer {clean_key}"
        return headers

    def _get_timeout(self) -> httpx.Timeout:
        # Lokale Modelle brauchen mehr Zeit als Cloud-APIs – Timeout konfigurierbar
        # (Einstellungen -> LLM -> Timeout).
        return _llm_timeout()

    def _apply_reasoning(self, payload: dict, effort: str | None):
        """Setzt die Reasoning-Stufe im Payload (OpenAI-Konvention).

        `off` wird zu "minimal" – die breit unterstuetzte Stufenliste kennt nur
        minimal|low|medium|high. Das ist bewusst eine Annaeherung: "minimal"
        denkt noch etwas. Ein echtes Abschalten (neueres "none") wuerde von
        vielen lokalen Servern mit 400 abgelehnt, und der 400-Fallback laesst den
        Parameter dann ganz weg – das Ergebnis waere die VOLLE Denktiefe, also
        das Gegenteil des Gewuenschten.

        OpenRouter ueberschreibt das, weil es ein eigenes `reasoning`-Objekt nutzt.
        """
        if not effort:
            return
        mapped = _OPENAI_EFFORT.get(effort)
        if mapped:
            payload["reasoning_effort"] = mapped

    def _reasoning_keys(self) -> tuple[str, ...]:
        """Payload-Felder, die beim Fallback entfernt werden muessen."""
        return ("reasoning_effort",)

    async def generate_response(self, model: str, system_prompt: str, contents: list,
                                tools: list = None, reasoning_effort: str | None = None,
                                temperature=None) -> LLMResponse:
        """Wählt zwischen nativem und Prompt-basiertem Tool-Calling (mit Retry bei 429/503)."""
        effort = _resolve_effort(reasoning_effort)
        temp = _resolve_temperature(temperature)

        async def _call():
            if self.prompt_tool_calling:
                return await self._generate_prompt_mode(model, system_prompt, contents, tools or [], effort, temp)
            return await self._generate_native(model, system_prompt, contents, tools, effort, temp)
        return await _retry_with_backoff(_call)

    # ── Nativer Modus (OpenAI tool_calls API) ────────────────────────

    async def _generate_native(self, model: str, system_prompt: str, contents: list,
                               tools: list = None, reasoning_effort: str | None = None,
                               temperature: float | None = DEFAULT_TEMPERATURE) -> LLMResponse:
        """temperature ist hier ein BEREITS aufgeloester Wert (Zahl oder None =
        weglassen) – nicht der Rohwert aus dem Profil."""
        messages = [{"role": "system", "content": system_prompt}]

        # KRITISCH: Tool-Call-IDs muessen zwischen assistant-Message (tool_calls[i].id)
        # und tool-Message (tool_call_id) konsistent sein. Wir generieren pro Tool-Name
        # eine FIFO-Queue von IDs (genau wie AnthropicProvider) und vergeben sie strikt
        # in der Reihenfolge wie sie auftreten. Ohne diese Verkettung sieht der LLM
        # ein verwaistes Tool-Ergebnis und ruft das Tool erneut auf (Endlosschleife!).
        from collections import deque, defaultdict
        tool_id_queues: dict[str, deque] = defaultdict(deque)
        _step_counter = 0

        for content in contents:
            _step_counter += 1
            role = "assistant" if content.role == "model" else "user"
            text_parts = []
            fn_calls = []
            fn_responses = []
            image_blocks = []

            for part in content.parts:
                if getattr(part, "text", None):
                    text_parts.append(part.text)
                fc = getattr(part, "function_call", None)
                if fc and getattr(fc, "name", None):
                    fn_calls.append(fc)
                fr = getattr(part, "function_response", None)
                if fr and getattr(fr, "name", None):
                    fn_responses.append(fr)
                _id_obj = getattr(part, "inline_data", None)
                if _id_obj:
                    _mime = getattr(_id_obj, "mime_type", "")
                    _data = getattr(_id_obj, "data", b"")
                    if _mime and _data and _mime.startswith("image/"):
                        import base64 as _b64m
                        image_blocks.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:{_mime};base64,{_b64m.b64encode(_data).decode()}"}
                        })

            # ── 1) Tool-Result (role=tool): muss EINE eigene Message pro Result sein ──
            if fn_responses:
                for fr in fn_responses:
                    ids = tool_id_queues.get(fr.name)
                    if ids:
                        tc_id = ids.popleft()
                    else:
                        # Orphan-Result (z.B. nach History-Kompression) – stabile ID,
                        # damit der LLM die Verkettung wenigstens lokal erkennt.
                        tc_id = f"call_{fr.name}_orphan_{_step_counter}"
                    resp_data = fr.response if isinstance(fr.response, dict) else {"result": str(fr.response)}
                    result_str = resp_data.get("result", json.dumps(resp_data, ensure_ascii=False))
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": str(result_str),
                    })
                continue

            # ── 2) Assistant mit Tool-Call(s) ────────────────────────────────
            if fn_calls:
                tool_calls_block = []
                for fc in fn_calls:
                    tc_id = f"call_{fc.name}_{_step_counter}_{len(tool_calls_block)}"
                    tool_id_queues[fc.name].append(tc_id)
                    args = dict(fc.args) if fc.args else {}
                    tool_calls_block.append({
                        "id": tc_id,
                        "type": "function",
                        "function": {
                            "name": fc.name,
                            "arguments": json.dumps(args, ensure_ascii=False),
                        },
                    })
                asst_msg = {
                    "role": "assistant",
                    # OpenAI-Spec: content darf bei tool_calls null sein – aber manche
                    # OpenAI-kompatiblen Server (Ollama) brauchen leeren String.
                    "content": "\n".join(text_parts) if text_parts else "",
                    "tool_calls": tool_calls_block,
                }
                messages.append(asst_msg)
                continue

            # ── 3) Normaler Text (ggf. mit Bild) ─────────────────────────────
            content_str = "\n".join(text_parts)
            if image_blocks:
                _content_list = []
                if content_str:
                    _content_list.append({"type": "text", "text": content_str})
                _content_list.extend(image_blocks)
                messages.append({"role": role, "content": _content_list})
            elif content_str:
                messages.append({"role": role, "content": content_str})

        payload = {
            "model": model,
            "messages": messages,
            "stream": False,   # Kein Streaming – wir lesen die komplette JSON-Antwort
            # Cap gegen endlose Reasoning-Laeufe (sonst Read-Timeout bei Qwen3 & Co.)
            "max_tokens": _llm_max_tokens(),
        }
        if temperature is not None:    # None = Feld weglassen (Profil "auto")
            payload["temperature"] = temperature
        self._apply_reasoning(payload, reasoning_effort)

        if tools:
            openai_tools = []
            for t in tools:
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters_schema() if hasattr(t, "parameters_schema") else t.parameters,
                    },
                })
            payload["tools"] = openai_tools

        payload["stream"] = False
        client = await _get_shared_client()
        resp = await client.post(self.base_url, headers=self._build_headers(), json=payload, timeout=self._get_timeout())
        if not resp.is_success:
            try:
                err_body = resp.json()
                _err = err_body.get("error")
                if isinstance(_err, dict):  # OpenAI-Stil: {"error": {"message": ...}}
                    _err = _err.get("message") or _err.get("type") or str(_err)
                err_detail = err_body.get("detail") or err_body.get("message") or _err or resp.text[:300]
            except Exception:
                err_detail = resp.text[:300]
            # vLLM/llama.cpp ohne --enable-auto-tool-choice / --tool-call-parser lehnen
            # tools-Requests mit 400 ab (z.B. Gemma-Server). In dem Fall transparent auf
            # Prompt-basiertes Tool-Calling zurueckfallen – der Agent behaelt so volle
            # Tool-Faehigkeit ueber das XML-Protokoll, ohne Server-Neustart noetig.
            _d = str(err_detail).lower()
            # Server ohne Reasoning-Unterstuetzung (aeltere vLLM/llama.cpp-Builds
            # validieren streng und lehnen unbekannte Felder mit 400 ab): einmal
            # ohne die Stufen-Vorgabe wiederholen, statt den Chat abzubrechen.
            if resp.status_code == 400 and reasoning_effort and _is_unsupported_param_error(err_detail):
                print(f"[LLM] {self.base_url}: Reasoning-Parameter abgelehnt "
                      f"({err_detail}) → Wiederholung ohne Vorgabe", flush=True)
                return await self._generate_native(model, system_prompt, contents, tools, None, temperature)
            if resp.status_code == 400 and tools and (
                "tool choice" in _d or "tool_choice" in _d
                or "auto-tool-choice" in _d or "tool-call-parser" in _d
                or "does not support tool" in _d or "tool calling" in _d
            ):
                print(f"[LLM] {self.base_url}: 400 bei nativem Tool-Calling "
                      f"({err_detail}) → Fallback auf Prompt-Modus", flush=True)
                return await self._generate_prompt_mode(model, system_prompt, contents, tools, reasoning_effort, temperature)
            if "context length" in _d or "maximum context" in _d or "input_tokens" in _d or "max_model_len" in _d:
                raise ValueError(
                    "Das gewählte Modell hat ein zu kleines Kontextfenster für den "
                    "Jarvis-Agenten (System-Prompt + Tools passen nicht hinein). "
                    f"Server-Meldung: {err_detail}. "
                    "Abhilfe: vLLM-Server mit größerem --max-model-len starten oder ein "
                    "Modell/Profil mit mehr Kontext verwenden."
                )
            raise ValueError(f"HTTP {resp.status_code} von {self.base_url}: {err_detail}")

        try:
            data = resp.json()
        except Exception:
            data = {}

        # Modell unterstützt keine Tool-Calls → Fallback ohne Tools + Hinweis
        if not isinstance(data, dict) and "tools" in payload:
            payload_no_tools = {k: v for k, v in payload.items() if k != "tools"}
            resp2 = await client.post(self.base_url, headers=self._build_headers(), json=payload_no_tools, timeout=self._get_timeout())
            resp2.raise_for_status()
            try:
                data = resp2.json()
            except Exception:
                data = {}
            if isinstance(data, dict):
                warn = (f"⚠️ Modell '{model}' unterstützt keine nativen Tool-Calls. "
                        "Aktiviere 'Prompt-basiertes Tool-Calling' im Profil oder wähle ein "
                        "anderes Modell (llama3.1, qwen2.5, mistral-nemo).")
                choices = data.get("choices") or []
                if choices:
                    choices[0].setdefault("message", {})
                    existing = choices[0]["message"].get("content") or ""
                    choices[0]["message"]["content"] = warn + "\n\n" + existing
                else:
                    data["choices"] = [{"message": {"content": warn}}]

        if not isinstance(data, dict):
            raise ValueError(
                f"LLM-Antwort ist kein JSON-Objekt ('{resp.text[:100]}'). "
                "Prüfe ob das Modell geladen ist – oder aktiviere 'Prompt-basiertes Tool-Calling'."
            )

        if "error" in data:
            err = data["error"]
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            raise ValueError(f"LLM-Fehler: {msg}")

        parts = []
        if "choices" in data and len(data["choices"]) > 0:
            choice = data["choices"][0]
            message = choice.get("message", {})

            if message.get("content"):
                parts.append(LLMPart(text=message["content"]))
            elif not message.get("tool_calls"):
                # content=null OHNE Tool-Call → je nach finish_reason unterscheiden.
                _finish = (choice.get("finish_reason") or "").lower()
                _reasoning = message.get("reasoning") or message.get("reasoning_content")
                if _finish == "length":
                    # Generierung mitten im Reasoning abgeschnitten (max_tokens
                    # erreicht – bei Reasoning-Modellen wie Qwen3 oft eine
                    # Denk-Schleife). NIEMALS das rohe Reasoning an den Nutzer
                    # dumpen; stattdessen klare Kurzmeldung.
                    parts.append(LLMPart(text=(
                        "⚠️ Das Modell konnte die Antwort nicht abschließen "
                        "(max_tokens erreicht – vermutlich eine Reasoning-Schleife, "
                        "weil die nötigen Daten/Tools nicht verfügbar waren). "
                        "Bitte die Anfrage konkretisieren oder ein anderes Modell/Profil wählen."
                    )))
                elif _reasoning:
                    # Sauber beendet (stop), aber Text nur im 'reasoning'-Feld –
                    # dann ist das die eigentliche Antwort. Als Fallback nutzen,
                    # damit der Agent nicht mit 0 Parts (leerer Antwort) endet.
                    parts.append(LLMPart(text=_reasoning))

            if message.get("tool_calls"):
                for tc in message["tool_calls"]:
                    fn = tc.get("function", {})
                    try:
                        args = json.loads(fn.get("arguments", "{}"))
                    except Exception:
                        args = {}
                    parts.append(LLMPart(function_call=MockFC(fn.get("name"), args)))

        usage = None
        try:
            u = data.get("usage", {})
            if u:
                usage = {
                    "input_tokens": u.get("prompt_tokens", 0) or 0,
                    "output_tokens": u.get("completion_tokens", 0) or 0,
                }
        except Exception:
            pass
        return LLMResponse(parts=parts, raw=data, usage=usage)

    # ── Prompt-Modus (Tools im System-Prompt, XML-Tag-Parsing) ───────

    async def _generate_prompt_mode(self, model: str, system_prompt: str, contents: list, tools: list,
                                    reasoning_effort: str | None = None,
                                    temperature: float | None = DEFAULT_TEMPERATURE) -> LLMResponse:
        """Prompt-basiertes Tool-Calling: keine tools-API, stattdessen XML-Tags im Text.

        temperature ist ein BEREITS aufgeloester Wert (Zahl oder None = weglassen)."""
        # Tools in System-Prompt einbetten
        if tools:
            tools_section = (
                "\n\n## Tool-Nutzung\n"
                "Du hast Zugriff auf folgende Tools. Um ein Tool aufzurufen, antworte "
                "AUSSCHLIESSLICH mit einem <tool_call>-Block – kein anderer Text davor oder danach:\n\n"
                "<tool_call>\n"
                "{\"name\": \"TOOL_NAME\", \"arguments\": {\"param\": \"wert\"}}\n"
                "</tool_call>\n\n"
                "Wenn du kein Tool benötigst, antworte normal auf Deutsch.\n\n"
                "### Verfügbare Tools:\n"
            )
            for t in tools:
                schema = t.parameters_schema() if hasattr(t, "parameters_schema") else {}
                props   = schema.get("properties", {})
                req     = set(schema.get("required", []))
                params  = ", ".join(
                    f"{k}{'*' if k in req else ''} ({v.get('type','any')}): {v.get('description','')}"
                    for k, v in props.items()
                )
                tools_section += f"\n**{t.name}**: {t.description}\n  Parameter: {params or 'keine'}\n"
            full_system = system_prompt + tools_section
        else:
            full_system = system_prompt

        # Nachrichten aufbauen – Tool-Aufrufe/-Ergebnisse als Klartext
        messages = [{"role": "system", "content": full_system}]
        for content in contents:
            parts_text = []
            tool_result_msgs = []

            for part in content.parts:
                if part.text:
                    parts_text.append(part.text)
                elif hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    args_str = json.dumps(dict(fc.args) if fc.args else {}, ensure_ascii=False)
                    parts_text.append(f'<tool_call>\n{{"name": "{fc.name}", "arguments": {args_str}}}\n</tool_call>')
                elif hasattr(part, "function_response") and part.function_response:
                    fr = part.function_response
                    result = (
                        fr.response.get("result", str(fr.response))
                        if isinstance(fr.response, dict) else str(fr.response)
                    )
                    tool_result_msgs.append({
                        "role": "user",
                        "content": f"Tool-Ergebnis für '{fr.name}':\n{result[:3000]}"
                    })

            if parts_text:
                role = "assistant" if content.role == "model" else "user"
                messages.append({"role": role, "content": "\n".join(parts_text)})
            messages.extend(tool_result_msgs)

        payload = {"model": model, "messages": messages, "stream": False}
        if temperature is not None:    # None = Feld weglassen (Profil "auto")
            payload["temperature"] = temperature
        self._apply_reasoning(payload, reasoning_effort)

        client = await _get_shared_client()
        resp = await client.post(self.base_url, headers=self._build_headers(), json=payload, timeout=self._get_timeout())
        if not resp.is_success:
            try:
                err_body = resp.json()
                _err = err_body.get("error")
                if isinstance(_err, dict):  # OpenAI-Stil: {"error": {"message": ...}}
                    _err = _err.get("message") or _err.get("type") or str(_err)
                err_detail = err_body.get("detail") or err_body.get("message") or _err or resp.text[:300]
            except Exception:
                err_detail = resp.text[:300]
            _d = str(err_detail).lower()
            # Server ohne Reasoning-Unterstuetzung: einmal ohne Stufen-Vorgabe wiederholen.
            if resp.status_code == 400 and reasoning_effort and _is_unsupported_param_error(err_detail):
                print(f"[LLM] {self.base_url}: Reasoning-Parameter abgelehnt "
                      f"({err_detail}) → Wiederholung ohne Vorgabe", flush=True)
                return await self._generate_prompt_mode(model, system_prompt, contents, tools, None, temperature)
            # Kontextfenster zu klein (z.B. vLLM --max-model-len 8192): klare, handlungs-
            # bezogene Meldung statt rohem httpx-Fehler.
            if "context length" in _d or "maximum context" in _d or "input_tokens" in _d or "max_model_len" in _d:
                raise ValueError(
                    "Das gewählte Modell hat ein zu kleines Kontextfenster für den "
                    "Jarvis-Agenten (System-Prompt + Tools passen nicht hinein). "
                    f"Server-Meldung: {err_detail}. "
                    "Abhilfe: vLLM-Server mit größerem --max-model-len starten oder ein "
                    "Modell/Profil mit mehr Kontext verwenden."
                )
            raise ValueError(f"HTTP {resp.status_code} von {self.base_url}: {err_detail}")
        try:
            data = resp.json()
        except Exception:
            data = {}

        if not isinstance(data, dict):
            raise ValueError(f"LLM-Antwort ist kein JSON-Objekt: {resp.text[:200]}")
        if "error" in data:
            err = data["error"]
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            raise ValueError(f"LLM-Fehler: {msg}")

        parts = []
        if "choices" in data and len(data["choices"]) > 0:
            text = (data["choices"][0].get("message") or {}).get("content") or ""

            # <tool_call>…</tool_call> extrahieren (erstes Match)
            match = re.search(r"<tool_call>\s*(.*?)\s*</tool_call>", text, re.DOTALL)
            if match:
                pre_text = text[:match.start()].strip()
                if pre_text:
                    parts.append(LLMPart(text=pre_text))
                try:
                    call_data = json.loads(match.group(1))
                    name = call_data.get("name", "")
                    args = call_data.get("arguments", {})
                    if isinstance(args, str):
                        args = json.loads(args)
                    parts.append(LLMPart(function_call=MockFC(name, args)))
                except Exception:
                    # JSON-Parsing fehlgeschlagen → als Text zurückgeben
                    parts.append(LLMPart(text=text))
            elif text.strip():
                parts.append(LLMPart(text=text))

        usage = None
        try:
            u = data.get("usage", {})
            if u:
                usage = {
                    "input_tokens": u.get("prompt_tokens", 0) or 0,
                    "output_tokens": u.get("completion_tokens", 0) or 0,
                }
        except Exception:
            pass
        return LLMResponse(parts=parts, raw=data, usage=usage)


# ═══════════════════════════════════════════════════════════════════
#  OpenRouter (erbt von OpenAI-Kompatibel)
# ═══════════════════════════════════════════════════════════════════

class OpenRouterProvider(OpenAICompatibleProvider):
    """OpenRouter-Provider mit zusätzlichen Headern."""

    def __init__(self, api_key: str, base_url: str = "https://openrouter.ai/api/v1/chat/completions"):
        super().__init__(api_key, base_url)

    def _build_headers(self) -> dict:
        headers = super()._build_headers()
        headers["HTTP-Referer"] = "https://github.com/google-deepmind/antigravity"
        headers["X-Title"] = "Jarvis Agent"
        return headers

    def _get_timeout(self) -> httpx.Timeout:
        return _llm_timeout()

    def _apply_reasoning(self, payload: dict, effort: str | None):
        """OpenRouter nutzt ein eigenes `reasoning`-Objekt statt reasoning_effort.

        `off` wird zu `{"enabled": false}` – die Stufen-Variante kennt kein "aus".
        """
        if not effort:
            return
        if effort == "off":
            payload["reasoning"] = {"enabled": False}
        else:
            payload["reasoning"] = {"effort": _OPENAI_EFFORT[effort]}

    def _reasoning_keys(self) -> tuple[str, ...]:
        return ("reasoning",)


# ═══════════════════════════════════════════════════════════════════
#  Anthropic Claude – API Key (offiziell)
# ═══════════════════════════════════════════════════════════════════

class AnthropicProvider(LLMProvider):
    """Direkter Anthropic Claude API Provider (mit API Key)."""

    def __init__(self, api_key: str):
        import anthropic
        self.client = anthropic.AsyncAnthropic(api_key=api_key)

    async def generate_response(self, model: str, system_prompt: str, contents: list,
                                tools: list = None, reasoning_effort: str | None = None,
                                temperature=None) -> LLMResponse:
        messages = []
        tool_id_queues: dict[str, deque] = defaultdict(deque)
        step = 0

        for content in contents:
            step += 1
            role = "assistant" if content.role == "model" else "user"

            text_parts = []
            fn_calls = []
            fn_responses = []

            inline_data_blocks = []  # Für Bild-Anhänge (Anthropic image blocks)
            for part in content.parts:
                if getattr(part, "text", None):
                    text_parts.append(part.text)
                fc = getattr(part, "function_call", None)
                if fc and getattr(fc, "name", None):
                    fn_calls.append(fc)
                fr = getattr(part, "function_response", None)
                if fr and getattr(fr, "name", None):
                    fn_responses.append(fr)
                _id_obj = getattr(part, "inline_data", None)
                if _id_obj:
                    _mime = getattr(_id_obj, "mime_type", "")
                    _data = getattr(_id_obj, "data", b"")
                    if _mime and _data and _mime.startswith("image/"):
                        import base64 as _b64a
                        inline_data_blocks.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": _mime,
                                "data": _b64a.b64encode(_data).decode(),
                            },
                        })

            if fn_responses:
                tool_result_blocks = []
                for fr in fn_responses:
                    ids = tool_id_queues.get(fr.name, deque())
                    tool_id = ids.popleft() if ids else f"call_{fr.name}_unknown"
                    resp_data = fr.response if isinstance(fr.response, dict) else {"result": str(fr.response)}
                    result_str = resp_data.get("result", json.dumps(resp_data, ensure_ascii=False))
                    tool_result_blocks.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": str(result_str),
                    })
                messages.append({"role": "user", "content": tool_result_blocks})

            elif fn_calls:
                content_blocks = []
                if text_parts:
                    content_blocks.append({"type": "text", "text": "\n".join(text_parts)})
                for fc in fn_calls:
                    tool_id = f"call_{fc.name}_{step}"
                    tool_id_queues[fc.name].append(tool_id)
                    args = dict(fc.args) if fc.args else {}
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tool_id,
                        "name": fc.name,
                        "input": args,
                    })
                messages.append({"role": "assistant", "content": content_blocks})

            else:
                text = "\n".join(text_parts)
                if inline_data_blocks:
                    # Bilder + Text als Content-Array (Anthropic-Format)
                    _blocks = []
                    if text:
                        _blocks.append({"type": "text", "text": text})
                    _blocks.extend(inline_data_blocks)
                    messages.append({"role": role, "content": _blocks})
                elif text:
                    messages.append({"role": role, "content": text})

        anthropic_tools = []
        if tools:
            for t in tools:
                raw_schema = t.parameters_schema() if hasattr(t, "parameters_schema") else {}
                anthropic_tools.append({
                    "name": t.name,
                    "description": t.description,
                    "input_schema": _normalize_schema(raw_schema),
                })

        _effort = _resolve_effort(reasoning_effort)
        _temp = _resolve_temperature(temperature)

        def _build_kwargs(with_reasoning: bool) -> dict:
            kw: dict = {
                "model": model,
                "max_tokens": 8096,
                "system": system_prompt,
                "messages": messages,
            }
            if anthropic_tools:
                kw["tools"] = anthropic_tools
            if not (with_reasoning and _effort):
                # Ohne Reasoning-Vorgabe bleibt es beim bisherigen Verhalten.
                # ACHTUNG: aktuelle Claude-Modelle (Opus 5/4.8/4.7, Sonnet 5)
                # lehnen temperature mit 400 ab – der Fallback unten faengt das.
                # Wer das vermeiden will, setzt im Profil temperature="auto".
                if _temp is not None:
                    kw["temperature"] = _temp
                return kw
            if _effort == "off":
                # Kein output_config: "thinking aus" plus hohe Effort-Stufe ist bei
                # Opus 5 eine ungueltige Kombination (400).
                kw["thinking"] = {"type": "disabled"}
                if _temp is not None:
                    kw["temperature"] = _temp
            else:
                # Adaptives Thinking + Effort-Stufe. temperature wird bewusst NICHT
                # gesetzt: die Modelle, die effort kennen, lehnen Sampling-Parameter ab.
                kw["thinking"] = {"type": "adaptive"}
                kw["output_config"] = {"effort": _ANTHROPIC_EFFORT[_effort]}
                if _effort in ("high", "max"):
                    # max_tokens deckelt Denk- UND Antworttoken gemeinsam.
                    kw["max_tokens"] = max(kw["max_tokens"], _ANTHROPIC_THINKING_MIN_TOKENS)
            return kw

        def _to_value_error(exc) -> ValueError:
            # Anthropic SDK-Exceptions in lesbare ValueError umwandeln
            raw = str(exc)
            # Typ aus Anthropic-Fehlerstruktur extrahieren
            err_msg = getattr(getattr(exc, "body", None) or {}, "get", lambda k, d=None: d)("error", {})
            if isinstance(err_msg, dict):
                err_msg = err_msg.get("message", raw)
            return ValueError(f"Anthropic API {getattr(exc, 'status_code', '')} – {err_msg or raw}")

        try:
            response = await self.client.messages.create(**_build_kwargs(True))
        except Exception as exc:
            # Zwei Faelle landen hier: ein aeltere Modell kennt thinking/output_config
            # nicht, oder ein neues Modell lehnt temperature ab. Beides einmal ohne
            # die strittigen Parameter wiederholen (nur model/messages/tools).
            if not _is_unsupported_param_error(_to_value_error(exc)):
                raise _to_value_error(exc) from exc
            _minimal = {k: v for k, v in _build_kwargs(False).items() if k != "temperature"}
            print(f"[LLM] Anthropic {model}: Zusatzparameter abgelehnt ({exc}) "
                  f"→ Wiederholung ohne thinking/effort/temperature", flush=True)
            try:
                response = await self.client.messages.create(**_minimal)
            except Exception as exc2:
                raise _to_value_error(exc2) from exc2

        parts = []
        for block in response.content:
            if block.type == "text":
                parts.append(LLMPart(text=block.text))
            elif block.type == "tool_use":
                parts.append(LLMPart(function_call=MockFC(block.name, block.input)))

        usage = None
        try:
            u = response.usage
            usage = {
                "input_tokens": getattr(u, "input_tokens", 0) or 0,
                "output_tokens": getattr(u, "output_tokens", 0) or 0,
            }
        except Exception:
            pass
        return LLMResponse(parts=parts, raw=response, usage=usage)


# ═══════════════════════════════════════════════════════════════════
#  Anthropic Claude – Session (Pro-Abo über claude.ai)
# ═══════════════════════════════════════════════════════════════════

class AnthropicSessionProvider(LLMProvider):
    """Claude-Zugriff über claude.ai Session-Cookie (Pro-Abo).

    Nutzt die interne claude.ai API mit dem sessionKey-Cookie.
    Tool-Calling wird über strukturierte Prompts simuliert, da
    die interne API kein natives Function Calling unterstützt.

    HINWEIS: Inoffiziell – kann bei API-Änderungen von Anthropic brechen.
    """

    BASE_URL = "https://claude.ai"

    def __init__(self, session_key: str):
        self.session_key = session_key
        self.org_id: str | None = None
        self.conversation_id: str | None = None
        self._last_contents_len = 0

    def _headers(self) -> dict:
        return {
            # clean_api_key auch hier: ein mitkopiertes Leerzeichen im Session-Key
            # macht den Cookie-Header ungueltig (siehe clean_api_key).
            "Cookie": f"sessionKey={clean_api_key(self.session_key)}",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": self.BASE_URL,
            "Referer": f"{self.BASE_URL}/",
        }

    async def _ensure_org_id(self):
        """Holt die Organisations-ID vom claude.ai Account."""
        if self.org_id:
            return
        client = await _get_shared_client()
        resp = await client.get(
            f"{self.BASE_URL}/api/organizations",
            headers=self._headers(),
            timeout=30.0,
        )
        resp.raise_for_status()
        orgs = resp.json()
        if not orgs:
            raise ValueError("Keine Organisation gefunden. Session-Key ungültig oder abgelaufen?")
        self.org_id = orgs[0]["uuid"]

    async def _create_conversation(self, model: str) -> str:
        """Erstellt eine neue claude.ai Konversation."""
        import uuid as uuid_lib
        conv_uuid = str(uuid_lib.uuid4())
        client = await _get_shared_client()
        resp = await client.post(
            f"{self.BASE_URL}/api/organizations/{self.org_id}/chat_conversations",
            headers=self._headers(),
            json={"name": "", "uuid": conv_uuid, "model": model},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["uuid"]

    async def _send_message(self, model: str, message: str) -> str:
        """Sendet eine Nachricht und sammelt die SSE-Antwort."""
        headers = self._headers()
        headers["Accept"] = "text/event-stream"

        payload = {
            "prompt": message,
            "timezone": "Europe/Berlin",
            "attachments": [],
            "files": [],
            "model": model,
        }

        full_response = ""
        client = await _get_shared_client()
        async with client.stream(
            "POST",
            f"{self.BASE_URL}/api/organizations/{self.org_id}/"
            f"chat_conversations/{self.conversation_id}/completion",
            headers=headers,
            json=payload,
            timeout=120.0,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                        if data.get("type") == "completion":
                            full_response += data.get("completion", "")
                    except json.JSONDecodeError:
                        pass

        return full_response

    # ─── Haupt-Methode ──────────────────────────────────────────

    async def generate_response(self, model: str, system_prompt: str, contents: list,
                                tools: list = None, reasoning_effort: str | None = None,
                                temperature=None) -> LLMResponse:
        # reasoning_effort und temperature werden bewusst ignoriert: claude.ai kennt
        # ueber die Session-Schnittstelle keine Sampling-Parameter.
        await self._ensure_org_id()

        is_first_call = self.conversation_id is None

        if is_first_call:
            self.conversation_id = await self._create_conversation(model)
            message = self._build_full_prompt(system_prompt, contents, tools)
        else:
            # Nur die neuen Tool-Ergebnisse senden (Rest kennt claude.ai schon)
            new_contents = contents[self._last_contents_len:]
            message = self._build_followup(new_contents)

        self._last_contents_len = len(contents)

        try:
            response_text = await self._send_message(model, message)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise ValueError("Session-Key ungültig oder abgelaufen. Bitte neu einloggen bei claude.ai.") from e
            if e.response.status_code == 403:
                raise ValueError("Zugriff verweigert. Eventuell hat sich das claude.ai API-Format geändert.") from e
            raise

        parts = self._parse_response(response_text)
        return LLMResponse(parts=parts, raw=response_text)

    # ─── Prompt-Builder ─────────────────────────────────────────

    def _build_full_prompt(self, system_prompt: str, contents: list, tools: list | None) -> str:
        """Baut den initialen Prompt mit System-Anweisungen + Tools."""
        parts = [system_prompt]

        if tools:
            parts.append(self._format_tools_prompt(tools))

        for content in contents:
            for part in content.parts:
                if getattr(part, "text", None):
                    parts.append(part.text)

        return "\n\n".join(parts)

    def _build_followup(self, new_contents: list) -> str:
        """Baut Follow-Up-Nachricht mit Tool-Ergebnissen."""
        parts = []
        for content in new_contents:
            for part in content.parts:
                fr = getattr(part, "function_response", None)
                if fr:
                    resp = fr.response if isinstance(fr.response, dict) else {"result": str(fr.response)}
                    result_str = resp.get("result", json.dumps(resp, ensure_ascii=False))
                    parts.append(f"[Tool-Ergebnis von {fr.name}]:\n{result_str}")
                elif getattr(part, "text", None):
                    parts.append(part.text)

        if not parts:
            return "Bitte fahre mit der Aufgabe fort."
        return "\n\n".join(parts) + "\n\nBitte fahre mit der Aufgabe fort."

    def _format_tools_prompt(self, tools: list) -> str:
        """Formatiert Tool-Beschreibungen für den System-Prompt."""
        lines = [
            "Du hast folgende Tools zur Verfügung.",
            "Wenn du ein Tool verwenden willst, antworte NUR mit einem JSON-Block:",
            "",
            "```tool_call",
            '{"name": "tool_name", "args": {"parameter": "wert"}}',
            "```",
            "",
            "Wichtig: Pro Antwort maximal EIN tool_call-Block. Nach dem Ergebnis kannst du den nächsten aufrufen.",
            "",
            "Verfügbare Tools:",
        ]
        for t in tools:
            schema = t.parameters_schema() if hasattr(t, "parameters_schema") else {}
            lines.append(f"\n**{t.name}**: {t.description}")
            props = schema.get("properties", {})
            required = schema.get("required", [])
            for pname, pschema in props.items():
                req = " (Pflicht)" if pname in required else " (optional)"
                desc = pschema.get("description", "")
                lines.append(f"  - {pname}: {desc}{req}")

        return "\n".join(lines)

    def _parse_response(self, text: str) -> list[LLMPart]:
        """Parst die Antwort auf Text und simulierte Tool-Calls."""
        parts = []

        tool_pattern = r"```tool_call\s*\n(.*?)\n\s*```"
        matches = list(re.finditer(tool_pattern, text, re.DOTALL))

        if matches:
            # Text vor dem ersten Tool-Call
            before = text[: matches[0].start()].strip()
            if before:
                parts.append(LLMPart(text=before))

            for match in matches:
                try:
                    data = json.loads(match.group(1).strip())
                    parts.append(LLMPart(function_call=MockFC(data["name"], data.get("args", {}))))
                except (json.JSONDecodeError, KeyError):
                    parts.append(LLMPart(text=match.group(0)))

            # Text nach dem letzten Tool-Call
            after = text[matches[-1].end() :].strip()
            if after:
                parts.append(LLMPart(text=after))
        else:
            if text.strip():
                parts.append(LLMPart(text=text.strip()))

        return parts

    def reset(self):
        """Setzt die Konversation zurück (für neue Aufgaben)."""
        self.conversation_id = None
        self._last_contents_len = 0


# ═══════════════════════════════════════════════════════════════════
#  Provider-Factory
# ═══════════════════════════════════════════════════════════════════

def get_provider(
    provider_name: str,
    api_key: str,
    api_url: str = None,
    auth_method: str = "api_key",
    session_key: str = None,
    prompt_tool_calling: bool = False,
) -> LLMProvider:
    name = provider_name.lower()
    if name == "google":
        return GeminiProvider(api_key)
    elif name == "openrouter":
        return OpenRouterProvider(api_key, base_url=api_url) if api_url else OpenRouterProvider(api_key)
    elif name == "anthropic":
        if auth_method == "session" and session_key:
            return AnthropicSessionProvider(session_key)
        return AnthropicProvider(api_key)
    elif name == "openai_compatible":
        return OpenAICompatibleProvider(
            api_key,
            base_url=api_url or "http://localhost:11434/v1/chat/completions",
            prompt_tool_calling=prompt_tool_calling,
        )
    raise ValueError(f"Unbekannter Provider: {provider_name}")
