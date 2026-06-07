# LLM-Provider-Patches – Zuordnung & Wechsel-Checkliste

> **Zweck:** Alle provider-spezifischen Sonderbehandlungen im Jarvis-Code an
> einer Stelle, damit beim Wechsel zwischen Gemini ↔ Anthropic ↔ OpenRouter ↔
> Lokal nichts vergessen oder doppelt gepatcht wird.
>
> **Konvention:** Provider-Switch passiert über `config.LLM_PROVIDER`
> (`"google" | "anthropic" | "anthropic_session" | "openai" | "openrouter"`)
> und `config.current_model`. Alle Quellen liegen unter `backend/`.

---

## 1 · Abstraktions-Schicht (immer gleich)

`backend/llm.py` normalisiert alle Provider auf ein gemeinsames Schema:

| Feld | Typ | Quelle |
|---|---|---|
| `LLMResponse.parts[*].text` | `str` | Provider-Text |
| `LLMResponse.parts[*].function_call` | `MockFC(name, args)` oder Gemini-FC | Tool-Aufruf |
| `LLMResponse.usage["input_tokens"]` | `int` | siehe §6 |
| `LLMResponse.usage["output_tokens"]` | `int` | siehe §6 |
| `LLMResponse.raw` | provider-spezifisch | Roh-Antwort (siehe §2) |

Der Agent (`agent.py`) sieht in 95 % der Fälle nur dieses neutrale Format.
Restliche 5 % sind in dieser Datei dokumentiert.

---

## 2 · History-Serialisierung (kritisch)

Wenn die LLM-Antwort wieder in `chat_history` zurückgeschrieben wird,
unterscheidet `agent.py` zwischen Gemini und Rest:

| Stelle | Gemini-Pfad | Rest-Pfad |
|---|---|---|
| `agent.py:586` (Fertig, kein Tool-Call) | `response.raw.candidates[0].content` direkt anhängen | Parts aus `response.parts` manuell zu `types.Content(role="model", parts=[…])` zusammensetzen |
| `agent.py:670` (nach Tool-Call, run_task) | dito | dito (inkl. `function_call`) |
| `agent.py:995` (nach Tool-Call, headless) | dito | dito |

**Warum:** Gemini liefert ein vollständig serialisierbares `Content`-Objekt,
das ungeprüft wieder in die History fließt. Anthropic / OpenAI liefern eigene
Antwort-Strukturen, die wir in unser internes Gemini-`types.Content`-Format
übersetzen, weil der Agent intern damit arbeitet.

> ⚠️ **Wechsel-Fallstrick:** Wenn ein neuer Provider hinzukommt und nicht
> `LLM_PROVIDER == "google"` ist, läuft er automatisch über den
> Rest-Pfad. Falls der Provider eine andere Part-Struktur als
> `text` + `function_call` braucht (z. B. Vision-Antworten, structured-output),
> muss hier ein weiterer Branch ergänzt werden.

---

## 3 · Max-Steps-Fallback (alle Provider)

`agent.py:707-786` (run_task) und `agent.py:1028-1080` (headless).

Wenn `MAX_AGENT_STEPS` (Default 75, `config.py`) erreicht ist, läuft ein
**zweistufiger** No-Tools-Fallback, um eine Antwort zu erzwingen:

1. **Versuch `with_history`** – komplette History + neue User-Anweisung
   („Bitte beantworte jetzt direkt …"). Funktioniert bei OpenAI, Anthropic,
   OpenRouter zuverlässig.
2. **Versuch `reset_only_task`** – frischer Kontext, nur Original-Aufgabe,
   neutraler System-Prompt. Nötig, weil Gemini bei langer
   `function_response`-Schwanz-Historie häufig leeren Text zurückgibt
   (interpretiert das letzte User-Turn als bereits beantwortet).

> ⚠️ **Wechsel-Fallstrick:** Wenn von Gemini weg gewechselt wird, kann
> Versuch 1 fast immer reichen. Versuch 2 schadet aber nicht und bleibt
> als Sicherheitsnetz.

---

## 4 · Gemini-spezifisch

**Provider-Klasse:** `GeminiProvider` (`llm.py:149-183`)

### 4.1 Safety-Filter (`finish_reason=STOP, parts=None`)
- **Auslöser:** Inhalte in `data/instructions/soul.md` (Autonomie-Phrasen,
  „handle SOFORT", aggressive Imperative).
- **Symptom:** Leere Antwort, kein Text, keine Tools. `agent.py:552-569`
  retried einmalig mit verkürztem Prompt.
- **Fix-Optionen beim Wechsel:**
  - Bleibt bei Gemini → soul.md entschärfen oder via
    `safety_settings={category: BLOCK_NONE}` in
    `GenerateContentConfig` (aktuell **nicht** gesetzt, müsste in
    `llm.py:162` ergänzt werden).
  - Wechsel zu Anthropic/OpenAI → Safety-Filter entfällt, Retry-Logik
    kann bleiben (greift dort nie).

### 4.2 Token-Felder
- Input: `usage_metadata.prompt_token_count`
- Output: `usage_metadata.candidates_token_count`
- `llm.py:176-178` mappt auf Standard-Schema.

### 4.3 Multimodal (Bilder)
- Inline-Bild: `types.Part.from_bytes(data=bytes, mime_type="image/png")`
- Wird vom Agenten an Function-Response-Parts angehängt
  (`agent.py:617-619, 657-659`).

### 4.4 Tool-Schema
- Verwendet `types.Tool(function_declarations=[…])` mit Google-eigenem
  JSON-Schema-Dialekt (akzeptiert `OBJECT`, `STRING`, … in Großbuchstaben,
  Tools liefern bereits korrektes Format via `parameters_schema()`).

### 4.5 Konfiguration
- `temperature=0.2` hart kodiert (`llm.py:165`).
- Kein expliziter `max_output_tokens` (Default des Modells).

---

## 5 · Anthropic-spezifisch (API-Key)

**Provider-Klasse:** `AnthropicProvider` (`llm.py:502-637`)

### 5.1 Tool-Use-ID-Pairing (HART)
- Anthropic verlangt zu jedem `tool_use`-Block exakt ein `tool_result`
  mit gleicher `tool_use_id`. Verletzung → API-Fehler.
- Workaround: pro Tool-Name eine FIFO-Queue `tool_id_queues[name]`
  (`llm.py:511,548-559`), die `tool_use`-IDs beim Anlegen pusht und beim
  Result wieder zieht.
- IDs sind selbst generiert (`call_{name}_{step}`), weil unser internes
  `types.Part`-Format keine IDs hat.

> ⚠️ **Wechsel-Fallstrick zurück auf Anthropic:** Wenn Tools parallel
> ausgeführt werden und dieselbe Tool-Funktion mehrfach pro Step aufgerufen
> wird, muss die Queue-Reihenfolge identisch zur Aufruf-Reihenfolge bleiben –
> sonst Result-Mismatch.

### 5.2 `max_tokens`-Limit
- Hardcoded `max_tokens=8096` (`llm.py:601`).
- Aktueller Claude 4.x kann mehr. Bei langen Antworten ggf. hochsetzen.

### 5.3 Token-Felder
- Direkt verwendbar: `response.usage.input_tokens` /
  `response.usage.output_tokens` (`llm.py:629-634`).
- **Kein Patch nötig**, Schema passt 1:1.

### 5.4 Multimodal
- Bilder als `{"type": "image", "source": {"type": "base64",
  "media_type": "...", "data": "..."}}` im Content-Array
  (`llm.py:537-545, 580-585`).
- **Anderes Format** als Gemini/OpenAI – darauf achten, falls neue
  Image-Quellen hinzukommen.

### 5.5 Fehlermeldungen
- SDK-Exceptions werden in `ValueError(f"Anthropic API {status} – {msg}")`
  übersetzt (`llm.py:611-619`), damit der Agent-Loop sie lesbar
  protokollieren kann.

---

## 6 · Anthropic-Session-Provider (Pro-Abo via claude.ai)

**Provider-Klasse:** `AnthropicSessionProvider` (`llm.py:644+`)

- Nutzt `sessionKey`-Cookie statt API-Key.
- Internes Endpunkt-Format anders als die offizielle API.
- **Vorsicht:** Inoffiziell, kann jederzeit brechen. Bei API-Verfügbarkeit
  immer `AnthropicProvider` bevorzugen.

---

## 7 · OpenAI-Compatible (Basis für OpenRouter / Ollama / LM Studio / vLLM)

**Provider-Klasse:** `OpenAICompatibleProvider` (`llm.py:190-477`)

### 7.1 Zwei Modi
- **Nativ** (`prompt_tool_calling=False`, Default) – nutzt OpenAI
  `tool_calls`-Field.
- **Prompt-Mode** (`prompt_tool_calling=True`) – Tools werden in den
  System-Prompt als XML-Beschreibung eingebettet, Antwort wird mit
  Regex auf `<tool_call>…</tool_call>` durchsucht. Für Modelle ohne
  native Function-Calling-API (manche Ollama-Modelle, Mistral 7B etc.).
- Schalter pro Modell in der UI / `settings.json`.

### 7.2 SSE-Fallback
- Manche Server (Open WebUI) liefern SSE auch wenn `stream:false`
  gesetzt ist → `_parse_sse_to_completion()` (`llm.py:41-78`)
  baut daraus ein synthetisches Non-Stream-JSON.

### 7.3 Token-Felder
- `usage.prompt_tokens` / `usage.completion_tokens` (OpenAI-Standard).
- Werden im `_generate_native`-Pfad gemappt.

### 7.4 Image-Format
- `{"type": "image_url", "image_url": {"url": "data:<mime>;base64,..."}}`
  (`llm.py:253-256`).

### 7.5 Timeout
- `OpenAICompatibleProvider._get_timeout()` → 180 s
  (lokale Modelle sind langsam).
- `OpenRouterProvider._get_timeout()` → 60 s (Cloud).

### 7.6 ASCII-Sanitization des API-Keys
- `llm.py:213` strippt Nicht-ASCII-Zeichen aus dem Bearer-Token,
  weil Nutzer manchmal Keys mit Emojis aus Discord kopieren →
  `UnicodeEncodeError` im HTTP-Header.

---

## 8 · OpenRouter-spezifisch (erbt OpenAICompatible)

**Provider-Klasse:** `OpenRouterProvider` (`llm.py:482-495`)

| Header | Wert | Zweck |
|---|---|---|
| `HTTP-Referer` | `https://github.com/google-deepmind/antigravity` | OpenRouter-Analytics |
| `X-Title` | `Jarvis Agent` | Anzeige im OR-Dashboard |

> ⚠️ Bei eigener OpenRouter-Anmeldung beide Header **auf die eigene
> Domain umstellen**, sonst tauchen die Stats unter „antigravity" auf.

---

## 9 · Token-Counter-Normalisierung (Übersicht)

| Provider | Roh-Feld Input | Roh-Feld Output | Standard-Mapping |
|---|---|---|---|
| Gemini | `prompt_token_count` | `candidates_token_count` | `llm.py:176-178` |
| Anthropic | `input_tokens` | `output_tokens` | direkt |
| Anthropic Session | aus Stream-Events extrahiert | dito | `llm.py:644+` |
| OpenAI-Compat | `prompt_tokens` | `completion_tokens` | im `_generate_native` |
| OpenRouter | wie OpenAI-Compat | wie OpenAI-Compat | – |

Frontend (`app.js`, `chat.js`) zeigt seit v95/v24 zusätzlich
`output_tokens / duration_s` als `tok/s`. Funktioniert für **alle**
Provider, da `output_tokens` immer normalisiert vorliegt.

---

## 10 · Context-Window-Größen (Compression-Trigger)

`agent.py:_compress_history` (`agent.py:1218+`) löst bei zu langer
History eine LLM-basierte Zusammenfassung aus. Die Schwelle ist
**provider-agnostisch** (Token-Schätzung), aber Modelle haben
unterschiedliche Hard-Limits:

| Modell | Context-Window | Anmerkung |
|---|---|---|
| Gemini 2.0 Flash | 1 M | praktisch unlimited für Chat |
| Gemini 1.5 Pro | 2 M | dito |
| Claude Sonnet 4.x | 200 K | großzügig, aber teuer |
| Claude Opus 4.x | 200 K | dito |
| GPT-4o / GPT-4.1 | 128 K | OK |
| OpenRouter (variabel) | je Modell | siehe Karte |
| Lokal (Ollama 7B/8B) | 8K – 32 K typisch | Compression früh wichtig |

> Bei Wechsel auf ein kleines Lokal-Modell: `_compress_history`-Threshold
> in `agent.py` aggressiver setzen (z. B. 50 % statt 80 % des Limits).

---

## 11 · Funktionierende Modell-Kombinationen (Stand 2026-06-07)

| Provider | Modell | Tools | Multimodal | Bemerkung |
|---|---|---|---|---|
| `google` | `gemini-2.0-flash-exp` | ✅ nativ | ✅ Bilder | Standard, schnell, billig |
| `google` | `gemini-2.5-flash` | ✅ nativ | ✅ Bilder | Neuer, oft präziser |
| `anthropic` | `claude-sonnet-4-20250514` | ✅ nativ | ✅ Bilder | Hochwertig, teurer |
| `anthropic` | `claude-opus-4-20250514` | ✅ nativ | ✅ Bilder | Beste Reasoning-Qualität |
| `openrouter` | `anthropic/claude-sonnet-4` | ✅ nativ | ✅ Bilder | Via OR statt direkt |
| `openrouter` | `google/gemini-2.0-flash-exp:free` | ✅ nativ | ✅ | Rate-limitiert |
| `openai_compat` | lokal Ollama `qwen2.5:7b` | ⚠️ Prompt-Mode | ❌ | nur kleine Tasks |

---

## 12 · Wechsel-Checkliste (Provider-Switch)

Vor dem Umschalten via UI-Settings oder `LLM_PROVIDER`-env:

1. **API-Key in Settings/.env hinterlegt?** (`config.current_api_key`)
2. **Modell-Name kompatibel?** (siehe §11; sonst HTTP 400)
3. **Bei OpenAI-Compat:** stimmt `prompt_tool_calling` (nativ ja/nein)?
4. **Bei OpenRouter:** Referer/Title in `llm.py:489-491` ggf. anpassen.
5. **Bei Anthropic:** `max_tokens=8096` reicht? (`llm.py:601`)
6. **Bei Gemini:** `soul.md` enthält keine triggernden Phrasen?
   (sonst leere Antworten – §4.1)
7. **Tool-Tests:** Erste Task mit jedem aktiven Skill (besonders
   `shell_execute`, `screenshot`, `spawn_agent`) durchspielen –
   Function-Calling kann pro Provider unterschiedlich strikt sein.
8. **History-Persistenz:** alte Chat-History eines Users ist im internen
   Gemini-`types.Content`-Format gespeichert. Beim Wechsel zu Anthropic
   wird sie automatisch via `AnthropicProvider.generate_response()`
   übersetzt – funktioniert, solange Parts nur `text` + `function_call`
   enthalten. Bei Multimodal-History eventuell `data/memory.json` /
   `_user_histories` zurücksetzen.

---

## 13 · Bekannte Fallstricke (kurz)

- **Gemini + soul.md** → leere Antworten (§4.1).
- **Anthropic + parallele Tool-Calls** → Tool-Use-ID-Reihenfolge wichtig (§5.1).
- **OpenAI-Compat + Open WebUI** → braucht SSE-Fallback (§7.2).
- **Local Models** → fast immer `prompt_tool_calling=True` setzen,
  sonst stille Tool-Aufrufe.
- **Token-Schätzung in `_compress_history`** ist heuristisch (Wörter ×
  1.3) – bei nicht-lateinischen Sprachen ggf. korrigieren.
- **MAX_AGENT_STEPS** Default jetzt 75 (war 50 bis 2026-06). Für
  kleinere/lokale Modelle eventuell auf 30 senken, um Wiederhol-Loops
  zu begrenzen.
