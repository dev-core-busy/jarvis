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


class LLMProvider(ABC):
    @abstractmethod
    async def generate_response(self, model: str, system_prompt: str, contents: list, tools: list = None) -> LLMResponse:
        pass


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


async def _get_shared_client() -> httpx.AsyncClient:
    """Gibt den shared AsyncClient zurueck (lazy init, thread-safe)."""
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        async with _client_lock:
            if _shared_client is None or _shared_client.is_closed:
                _shared_client = httpx.AsyncClient(
                    timeout=httpx.Timeout(180.0, connect=10.0, read=180.0, write=30.0),
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

    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)

    async def generate_response(self, model: str, system_prompt: str, contents: list, tools: list = None) -> LLMResponse:
        gemini_tools = [types.Tool(function_declarations=tools)] if tools else None

        async def _call():
            resp = await asyncio.to_thread(
                self.client.models.generate_content,
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    tools=gemini_tools,
                    temperature=0.2,
                ),
            )
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
        if self.api_key:
            # Nur ASCII-Zeichen behalten (verhindert UnicodeEncodeError bei versehentlich
            # kopierten Emojis oder Sonderzeichen im API-Key)
            clean_key = self.api_key.strip().encode("ascii", errors="ignore").decode("ascii")
            headers["Authorization"] = f"Bearer {clean_key}"
        return headers

    def _get_timeout(self) -> httpx.Timeout:
        # Lokale Modelle brauchen mehr Zeit als Cloud-APIs (Application Programming Interfaces)
        return httpx.Timeout(180.0, connect=10.0, read=180.0, write=30.0)

    async def generate_response(self, model: str, system_prompt: str, contents: list, tools: list = None) -> LLMResponse:
        """Wählt zwischen nativem und Prompt-basiertem Tool-Calling (mit Retry bei 429/503)."""
        async def _call():
            if self.prompt_tool_calling:
                return await self._generate_prompt_mode(model, system_prompt, contents, tools or [])
            return await self._generate_native(model, system_prompt, contents, tools)
        return await _retry_with_backoff(_call)

    # ── Nativer Modus (OpenAI tool_calls API) ────────────────────────

    async def _generate_native(self, model: str, system_prompt: str, contents: list, tools: list = None) -> LLMResponse:
        messages = [{"role": "system", "content": system_prompt}]

        for content in contents:
            role = "assistant" if content.role == "model" else "user"
            content_str = ""
            tool_call_id = None

            for part in content.parts:
                if part.text:
                    content_str += part.text
                if part.function_response:
                    role = "tool"
                    tool_call_id = "call_" + part.function_response.name
                    content_str = json.dumps(part.function_response.response)

            msg = {"role": role, "content": content_str}
            if tool_call_id:
                msg["tool_call_id"] = tool_call_id
            messages.append(msg)

        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
            "stream": False,   # Kein Streaming – wir lesen die komplette JSON-Antwort
        }

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
                err_detail = err_body.get("detail") or err_body.get("message") or err_body.get("error") or resp.text[:300]
            except Exception:
                err_detail = resp.text[:300]
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

    async def _generate_prompt_mode(self, model: str, system_prompt: str, contents: list, tools: list) -> LLMResponse:
        """Prompt-basiertes Tool-Calling: keine tools-API, stattdessen XML-Tags im Text."""
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

        payload = {"model": model, "messages": messages, "temperature": 0.2, "stream": False}

        client = await _get_shared_client()
        resp = await client.post(self.base_url, headers=self._build_headers(), json=payload, timeout=self._get_timeout())
        resp.raise_for_status()
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

    def _get_timeout(self) -> float:
        return 60.0


# ═══════════════════════════════════════════════════════════════════
#  Anthropic Claude – API Key (offiziell)
# ═══════════════════════════════════════════════════════════════════

class AnthropicProvider(LLMProvider):
    """Direkter Anthropic Claude API Provider (mit API Key)."""

    def __init__(self, api_key: str):
        import anthropic
        self.client = anthropic.AsyncAnthropic(api_key=api_key)

    async def generate_response(self, model: str, system_prompt: str, contents: list, tools: list = None) -> LLMResponse:
        messages = []
        tool_id_queues: dict[str, deque] = defaultdict(deque)
        step = 0

        for content in contents:
            step += 1
            role = "assistant" if content.role == "model" else "user"

            text_parts = []
            fn_calls = []
            fn_responses = []

            for part in content.parts:
                if getattr(part, "text", None):
                    text_parts.append(part.text)
                fc = getattr(part, "function_call", None)
                if fc and getattr(fc, "name", None):
                    fn_calls.append(fc)
                fr = getattr(part, "function_response", None)
                if fr and getattr(fr, "name", None):
                    fn_responses.append(fr)

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
                if text:
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

        kwargs: dict = {
            "model": model,
            "max_tokens": 8096,
            "system": system_prompt,
            "messages": messages,
            "temperature": 0.2,
        }
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools

        try:
            response = await self.client.messages.create(**kwargs)
        except Exception as exc:
            # Anthropic SDK-Exceptions in lesbare ValueError umwandeln
            raw = str(exc)
            # Typ aus Anthropic-Fehlerstruktur extrahieren
            err_type = getattr(getattr(exc, "body", None) or {}, "get", lambda k, d=None: d)("type", "")
            err_msg  = getattr(getattr(exc, "body", None) or {}, "get", lambda k, d=None: d)("error", {})
            if isinstance(err_msg, dict):
                err_msg = err_msg.get("message", raw)
            raise ValueError(f"Anthropic API {getattr(exc, 'status_code', '')} – {err_msg or raw}") from exc

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
            "Cookie": f"sessionKey={self.session_key}",
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

    async def generate_response(self, model: str, system_prompt: str, contents: list, tools: list = None) -> LLMResponse:
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
