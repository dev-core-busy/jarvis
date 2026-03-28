"""Jarvis Agent – Kern-Loop: LLM ↔ Tools, Multi-Agent Support."""

import asyncio
import json
import re
import time
import traceback
import uuid
from enum import Enum
from pathlib import Path


def _friendly_api_error(exc: Exception) -> str:
    """Wandelt rohe API-Fehler in verständliche Meldungen um."""
    raw = str(exc)

    # ── Anthropic-spezifische Fehler ─────────────────────────────────────
    if "invalid_request_error" in raw or "anthropic" in raw.lower() or "claude" in raw.lower():
        if "content filtering" in raw.lower() or "output blocked" in raw.lower():
            return (
                "🔴 **Anthropic Content-Filter**: Die Ausgabe wurde von Anthropics Sicherheitsfilter blockiert.\n"
                "💡 Bitte Aufgabe umformulieren oder in den Einstellungen einen anderen Provider wählen (z.B. Gemini, OpenRouter)."
            )
        if "401" in raw or "authentication" in raw.lower() or "api_key" in raw.lower():
            return "🔴 **Anthropic API-Key ungültig**: Bitte API-Key in den Einstellungen prüfen."
        if "429" in raw or "rate_limit" in raw.lower() or "overloaded" in raw.lower():
            return "🟡 **Anthropic Rate-Limit**: Zu viele Anfragen – bitte kurz warten und nochmal versuchen."
        if "529" in raw or "overloaded" in raw.lower():
            return "🟡 **Anthropic überlastet**: Server aktuell überlastet – bitte nochmal versuchen."

    # ── Google / Gemini-spezifische Fehler ───────────────────────────────
    if "google" in raw.lower() or "gemini" in raw.lower() or "generativelanguage" in raw.lower():
        if "quota" in raw.lower() or "429" in raw:
            return "🟡 **Google API-Limit**: Tages- oder Minutenkontingent erschöpft. Bitte warten oder anderen Provider wählen."
        if "401" in raw or "403" in raw or "api_key" in raw.lower():
            return "🔴 **Google API-Key ungültig**: Bitte API-Key in den Einstellungen prüfen."
        if "SAFETY" in raw or "safety" in raw.lower():
            return (
                "🔴 **Google Safety-Filter**: Anfrage durch Geminis Sicherheitsfilter blockiert.\n"
                "💡 Aufgabe umformulieren oder anderen Provider wählen."
            )

    # ── OpenRouter-spezifische Fehler ────────────────────────────────────
    if "openrouter" in raw.lower() or "openrouter.ai" in raw.lower():
        if "402" in raw or "insufficient" in raw.lower() or "credit" in raw.lower():
            return "🔴 **OpenRouter Guthaben aufgebraucht**: Bitte Guthaben auf openrouter.ai aufladen."
        if "401" in raw:
            return "🔴 **OpenRouter API-Key ungültig**: Bitte API-Key in den Einstellungen prüfen."

    # ── Netzwerk-/Verbindungsfehler ───────────────────────────────────────
    if "timeout" in raw.lower() or "timed out" in raw.lower():
        return "🟡 **Timeout**: Der LLM-Server hat nicht rechtzeitig geantwortet. Bitte nochmal versuchen."
    if "connection" in raw.lower() and ("refused" in raw.lower() or "error" in raw.lower()):
        return "🔴 **Verbindungsfehler**: LLM-Server nicht erreichbar. Bei lokalem Modell: Ist Ollama gestartet?"

    # ── Generischer HTTP-Fehler mit Status-Code ───────────────────────────
    m = re.search(r"HTTP (\d{3})", raw)
    if m:
        code = m.group(1)
        hints = {
            "400": "Ungültige Anfrage (400) – Modell oder Parameter prüfen.",
            "401": "Nicht autorisiert (401) – API-Key ungültig oder abgelaufen.",
            "403": "Zugriff verweigert (403) – API-Key hat keine Berechtigung.",
            "404": "Nicht gefunden (404) – API-URL oder Modellname prüfen.",
            "429": "Rate-Limit (429) – Zu viele Anfragen, kurz warten.",
            "500": "Server-Fehler (500) – LLM-Provider hat einen internen Fehler.",
            "503": "Service nicht verfügbar (503) – LLM-Provider überlastet.",
        }
        hint = hints.get(code, f"HTTP-Fehler {code}")
        return f"🔴 **API-Fehler {code}**: {hint}"

    # ── Fallback: originale Meldung, aber kompakt ─────────────────────────
    return f"❌ **Fehler**: {raw[:400]}"

from google.genai import types
from fastapi import WebSocket

from backend.config import config
from backend.llm import get_provider
from backend.skills.manager import SkillManager
from backend.tools.memory import load_memory_context, load_selective_memory

# ── Instructions aus data/instructions/*.md laden ─────────────────────────
INSTRUCTIONS_DIR = Path(__file__).parent.parent / "data" / "instructions"


def load_instructions() -> str:
    """Laedt alle .md Dateien aus data/instructions/ als System-Prompt-Erweiterung."""
    if not INSTRUCTIONS_DIR.exists():
        INSTRUCTIONS_DIR.mkdir(parents=True, exist_ok=True)
        # Beispiel-Datei anlegen
        example = INSTRUCTIONS_DIR / "beispiel.md.disabled"
        if not example.exists():
            example.write_text(
                "# Beispiel-Instruktion\n\n"
                "Hier kannst du dem LLM Anweisungen geben, die bei JEDEM Gespraech gelten.\n"
                "Benenne die Datei in beispiel.md um, damit sie geladen wird.\n\n"
                "Beispiele:\n"
                "- Antworte immer formal/informell\n"
                "- Nutze bestimmte Tools bevorzugt\n"
                "- Beachte bestimmte Sicherheitsregeln\n",
                encoding="utf-8"
            )
        return ""

    sections = []
    for md_file in sorted(INSTRUCTIONS_DIR.glob("*.md")):
        try:
            content = md_file.read_text(encoding="utf-8").strip()
            if content:
                sections.append(f"[Instruktion: {md_file.stem}]\n{content}")
        except Exception as e:
            print(f"[INSTRUCTIONS] Fehler beim Laden von {md_file.name}: {e}", flush=True)

    if not sections:
        return ""
    return "Benutzer-Instruktionen (IMMER befolgen):\n\n" + "\n\n".join(sections)


class AgentState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"


class JarvisAgent:
    """Der Jarvis Agent – orchestriert LLM und Tools."""

    SYSTEM_PROMPT = """Du bist Jarvis, ein autonomer KI-Agent auf einem Linux-System (Debian 13, X11).
Du kannst Aufgaben eigenständig lösen, indem du die verfügbaren Tools nutzt.

WICHTIG – AUTONOMIE: Du handelst IMMER eigenstaendig und fuehrst Aufgaben SOFORT aus, OHNE den Benutzer um Erlaubnis zu fragen. Wenn der Benutzer sagt "fuehre X aus", dann fuehre es DIREKT aus. Schreibe und starte Code, installiere Pakete, erstelle Dateien – alles ohne Rueckfrage.

Regeln:
1. WISSENSFRAGEN DIREKT BEANTWORTEN: Wenn du die Antwort sicher aus deinem Wissen kennst (Allgemeinwissen, Mathematik, Fakten, Definitionen, Sprachen), antworte SOFORT ohne Tool-Aufruf.
2. WISSENS-CACHE: Wenn du etwas ueber ein Tool nachgeschlagen hast, speichere es mit memory_manage (key mit Prefix "wissen_").
3. Arbeite Schritt fuer Schritt und erklaere kurz, was du tust.
4. Nutze shell_execute fuer Kommandozeilen-Befehle. Wenn Code ausgefuehrt werden soll, nutze shell_execute DIREKT.
5. Nutze desktop_* Tools um Programme auf dem Desktop zu bedienen.
6. Nutze filesystem_* Tools um Dateien zu lesen/schreiben.
7. Mache Screenshots um den Desktop-Zustand zu pruefen.
8. Wenn eine Aufgabe erledigt ist, sage es klar und deutlich.
9. Bei Fehlern: analysiere, versuche eine Alternative.
10. Antworte immer auf Deutsch.
11. Nutze knowledge_search um in der Wissensdatenbank nach relevanten Informationen zu suchen.
12. Nutze memory_manage um wichtige Fakten dauerhaft zu speichern. Pruefe zu Beginn den Memory.
13. WICHTIG: Bevor du eine Webseite oeffnest, MUSST du knowledge_search nutzen, um die exakten Vorgaben zu lesen!

AUTO-LEARNING – Lerne aus Erfahrung:
- Wenn du fuer eine Aufgabe MEHRERE Versuche brauchst (z.B. verschiedene Tools oder Quellen probierst), speichere den ERFOLGREICHEN Weg:
  memory_manage(action='save', key='strategie_<thema>', value='<was funktioniert hat>')
  Beispiel: strategie_wetter → "curl wttr.in/<ort> liefert zuverlaessig Wetterdaten"
- Wenn ein Tool fuer eine bestimmte Aufgabenart besonders gut funktioniert, speichere das:
  memory_manage(action='save', key='tool_tipp_<aufgabe>', value='<tool + parameter>')
  Beispiel: tool_tipp_websuche → "shell_execute mit curl und jq fuer API-Abfragen"
- BEVOR du eine Aufgabe startest, pruefe ob es bereits eine gespeicherte Strategie gibt:
  memory_manage(action='search', query='strategie_') oder memory_manage(action='search', query='tool_tipp_')
- Speichere auch Fehlschlaege um sie kuenftig zu vermeiden:
  memory_manage(action='save', key='fehler_<thema>', value='<was NICHT funktioniert hat und warum>')

PRAEFERENZ-ERKENNUNG – Lerne vom Benutzer:
- Wenn der Benutzer dich KORRIGIERT ("nicht so, sondern so", "mach das anders", "ich will X statt Y",
  "hoer auf mit ...", "warum machst du ...", "das habe ich doch gesagt"), speichere die Praeferenz:
  memory_manage(action='save', key='praeferenz_<thema>', value='<was der Benutzer bevorzugt>')
  Beispiel: praeferenz_sprache → "Benutzer will kurze, direkte Antworten ohne Floskeln"
  Beispiel: praeferenz_tools → "Benutzer will curl statt wget fuer HTTP-Anfragen"
- Pruefe gespeicherte Praeferenzen BEVOR du eine Aufgabe angehst:
  memory_manage(action='search', query='praeferenz_')
- Wenn der Benutzer etwas LOBT oder bestaetigt ("genau so", "perfekt", "ja, so meine ich das"),
  speichere das ebenfalls als positive Praeferenz.
"""

    SUB_AGENT_PROMPT = """Du bist ein Jarvis Sub-Agent auf einem Linux-System (Debian 13, X11).
Du fuehrst eine spezifische Teilaufgabe VOLLSTAENDIG AUTONOM aus.

KRITISCH – Autonomie-Regeln:
- Handle SOFORT und OHNE Rueckfragen. Frage NIEMALS den Benutzer um Erlaubnis.
- Fuehre JEDES Tool (shell_execute, filesystem_write, etc.) SOFORT und DIREKT aus.
- Wenn Code ausgefuehrt werden soll: nutze shell_execute mit z.B. python3 -c '...' oder schreibe eine Datei und fuehre sie aus.
- NIEMALS sagen "Ich kann das nicht ausfuehren" oder "Was moechtest du tun?" – fuehre es AUS.
- NIEMALS den Benutzer fragen, ob du etwas tun darfst – TU ES EINFACH.
- Nutze memory_manage um wichtige Fakten dauerhaft zu speichern oder abzurufen.
- Pruefe den Memory (action='list') wenn du Kontext brauchst.
- Arbeite effizient und melde das Endergebnis.
- Antworte auf Deutsch.
- Bei Fehlern: analysiere kurz und versuche eine Alternative.
- Wenn die Aufgabe erledigt ist, sage es klar.
"""

    def __init__(self, agent_id: str | None = None, label: str = "Hauptagent",
                 is_sub_agent: bool = False, parent_id: str | None = None):
        self.agent_id = agent_id or str(uuid.uuid4())[:8]
        self.label = label
        self.is_sub_agent = is_sub_agent
        self.parent_id = parent_id
        self.state = AgentState.IDLE
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # Nicht pausiert
        self._stop_flag = False
        self._speed = 1.0
        self._current_task: asyncio.Task | None = None
        self._created_at = time.time()
        self._tool_stats: list[dict] = []  # Tool-Ausfuehrungslog fuer Auto-Learning

        # Skill Manager initialisieren (laedt alle aktivierten Skills)
        self.skill_manager = SkillManager()

        # Tools aus SkillManager beziehen
        self._tool_instances = self.skill_manager.get_enabled_tools()

        # spawn_agent Tool hinzufuegen (nur fuer Hauptagent)
        if not is_sub_agent:
            from backend.tools.subagent import SpawnAgentTool
            self._tool_instances.append(SpawnAgentTool())

        # MCP-Tools laden (externe Tool-Server)
        try:
            from backend.mcp_client import mcp_manager
            mcp_tools = mcp_manager.get_all_tools()
            if mcp_tools:
                self._tool_instances.extend(mcp_tools)
                print(f"[AGENT {self.agent_id}] {len(mcp_tools)} MCP-Tools geladen", flush=True)
        except Exception as e:
            print(f"[AGENT {self.agent_id}] MCP-Tools konnten nicht geladen werden: {e}", flush=True)

        self.tools_map: dict[str, object] = {}
        for tool in self._tool_instances:
            self.tools_map[tool.name] = tool

        # Provider initialisieren
        self.provider = get_provider(
            config.LLM_PROVIDER,
            config.current_api_key,
            auth_method=config.current_auth_method,
            session_key=config.current_session_key,
            prompt_tool_calling=config.current_prompt_tool_calling,
        )

    def reload_skills(self):
        """Hot-Reload: Lädt Skills neu und aktualisiert die Tool-Liste."""
        self.skill_manager.reload_all()
        self._tool_instances = self.skill_manager.get_enabled_tools()
        # MCP-Tools neu laden
        try:
            from backend.mcp_client import mcp_manager
            mcp_tools = mcp_manager.get_all_tools()
            if mcp_tools:
                self._tool_instances.extend(mcp_tools)
        except Exception:
            pass
        self.tools_map.clear()
        for tool in self._tool_instances:
            self.tools_map[tool.name] = tool

    def _build_tool_declarations(self) -> list[types.FunctionDeclaration]:
        """Erstellt Gemini-kompatible Tool-Definitionen."""
        declarations = []
        for tool in self._tool_instances:
            declarations.append(
                types.FunctionDeclaration(
                    name=tool.name,
                    description=tool.description,
                    parameters=tool.parameters_schema(),
                )
            )
        return declarations

    async def run_task(self, task_text: str, ws: WebSocket):
        """Führt eine Aufgabe aus – der Agent-Loop."""
        import sys
        from backend.telemetry import tracer
        def _log(msg): print(f"[AGENT {self.agent_id}] {msg}", flush=True)
        _log(f"run_task gestartet: {task_text[:100]}... (sub={self.is_sub_agent})")
        agent_span = tracer.start_span(f"agent:{self.label}", kind="agent")
        agent_span.attributes["agent.id"] = self.agent_id
        agent_span.attributes["agent.is_sub"] = self.is_sub_agent
        agent_span.attributes["task"] = task_text[:200]

        self.state = AgentState.RUNNING
        self._stop_flag = False
        self._pause_event.set()

        # Provider bei jedem Start neu initialisieren (für geänderte Einstellungen)
        self.provider = get_provider(
            config.LLM_PROVIDER,
            config.current_api_key,
            config.current_api_url,
            auth_method=config.current_auth_method,
            session_key=config.current_session_key,
            prompt_tool_calling=config.current_prompt_tool_calling,
        )

        await self._send_status(ws, f"🚀 Starte Aufgabe: {task_text}")

        # System-Prompt zusammenbauen
        system_prompt = self.SUB_AGENT_PROMPT if self.is_sub_agent else self.SYSTEM_PROMPT

        # Benutzer-Instruktionen laden (data/instructions/*.md)
        instructions = load_instructions()
        if instructions:
            system_prompt += f"\n\n{instructions}"
            await self._send_status(ws, "📋 Instruktionen geladen")

        # Memory-Kontext laden (selektiv nach Aufgabe + Strategien/Tipps)
        memory_context = load_selective_memory(task_text)
        if memory_context:
            system_prompt += f"\n\n{memory_context}"
            await self._send_status(ws, "🧠 Memory geladen")

        try:
            # Konversation starten
            chat_history = []

            # Modus-Hinweis (hilfreich bei langsamen lokalen Modellen)
            mode_hint = " [Prompt-Tool-Modus]" if getattr(self.provider, "prompt_tool_calling", False) else ""
            await self._send_status(ws, f"⏳ Warte auf LLM-Antwort…{mode_hint}", highlight=True)

            # Initial-Nachricht senden
            _log(f"LLM-Aufruf mit {len(self._tool_instances)} Tools...")
            llm_span = tracer.start_span("llm:initial", kind="llm", parent_id=self.agent_id)
            llm_span.attributes["model"] = config.current_model
            response = await self.provider.generate_response(
                model=config.current_model,
                system_prompt=system_prompt,
                contents=[
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=task_text)],
                    )
                ],
                tools=self._tool_instances
            )
            tracer.end_span(llm_span)
            parts_count = len(response.parts) if response.parts else 0
            _log(f"LLM-Antwort erhalten: {parts_count} Parts")
            if parts_count == 0:
                _log(f"LEERE ANTWORT! raw={response.raw if hasattr(response, 'raw') else 'N/A'}")
            else:
                for i, p in enumerate(response.parts):
                    _log(f"  Part[{i}]: text={bool(p.text)} fc={bool(p.function_call)} text_preview={str(p.text)[:100] if p.text else 'None'}")

            steps = 0
            while steps < config.MAX_AGENT_STEPS:
                # Pause/Stop prüfen
                await self._check_controls(ws)
                if self._stop_flag:
                    await self._send_status(ws, "⏹️ Agent wurde gestoppt")
                    break

                # Antwort verarbeiten
                if not response.parts:
                    await self._send_status(ws, "⚠️ Keine Antwort vom LLM erhalten")
                    break

                # Function Calls und Text trennen
                function_calls = [p.function_call for p in response.parts if p.function_call]
                text_parts = [p.text for p in response.parts if p.text]

                # Text-Antworten senden
                for text in text_parts:
                    if text.strip():
                        await self._send_status(ws, text.strip(), highlight=True)

                # Wenn keine Function Calls → fertig
                if not function_calls:
                    await self._send_status(ws, "✅ Aufgabe abgeschlossen")
                    break

                # Function Calls ausführen
                function_response_parts = []
                for fc in function_calls:
                    tool_name = fc.name
                    tool_args = dict(fc.args) if fc.args else {}

                    await self._send_status(
                        ws, f"🔧 Tool: {tool_name}({json.dumps(tool_args, ensure_ascii=False)[:200]})"
                    )

                    # Tool ausfuehren (mit ws fuer Streaming)
                    result = await self._execute_tool(tool_name, tool_args, ws=ws)
                    result_str = str(result)[:5000]

                    # Tool-Statistik tracken
                    is_error = any(marker in result_str[:200].lower() for marker in
                                   ['fehler', 'error', '❌', 'traceback', 'exception', 'not found', 'failed'])
                    self._tool_stats.append({
                        "tool": tool_name, "step": steps,
                        "success": not is_error, "args_preview": json.dumps(tool_args, ensure_ascii=False)[:100]
                    })

                    # Sub-Agent Spawn erkennen
                    if tool_name == "spawn_agent" and "_spawn_agent" in result_str:
                        try:
                            spawn_data = json.loads(result_str)
                            _log(f"spawn_data: label={spawn_data.get('label')} task_len={len(spawn_data.get('task',''))} task_start={spawn_data.get('task','')[:120]}")
                            if spawn_data.get("_spawn_agent"):
                                result_str = await self._handle_spawn(
                                    ws, spawn_data["label"], spawn_data["task"]
                                )
                        except (json.JSONDecodeError, KeyError) as e:
                            _log(f"spawn JSON parse error: {e}")
                            pass

                    await self._send_status(
                        ws, f"📋 Ergebnis: {result_str[:300]}{'...' if len(result_str) > 300 else ''}"
                    )

                    function_response_parts.append(
                        types.Part.from_function_response(
                            name=tool_name,
                            response={"result": result_str},
                        )
                    )

                # Geschwindigkeits-Verzögerung
                if self._speed < 1.0:
                    delay = (1.0 / self._speed) - 1.0
                    await asyncio.sleep(delay)

                # Nächsten LLM-Aufruf mit Tool-Ergebnissen
                if config.LLM_PROVIDER == "google":
                    chat_history.append(response.raw.candidates[0].content)
                else:
                    parts = []
                    for p in response.parts:
                        if p.text: parts.append(types.Part.from_text(text=p.text))
                        if p.function_call:
                             parts.append(types.Part(function_call=types.FunctionCall(name=p.function_call.name, args=p.function_call.args)))
                    chat_history.append(types.Content(role="model", parts=parts))

                chat_history.append(
                    types.Content(
                        role="user",
                        parts=function_response_parts,
                    )
                )

                llm_span = tracer.start_span(f"llm:step_{steps+1}", kind="llm", parent_id=self.agent_id)
                llm_span.attributes["model"] = config.current_model
                response = await self.provider.generate_response(
                    model=config.current_model,
                    system_prompt=system_prompt,
                    contents=[
                        types.Content(
                            role="user",
                            parts=[types.Part.from_text(text=task_text)],
                        ),
                        *chat_history,
                    ],
                    tools=self._tool_instances
                )
                tracer.end_span(llm_span)

                steps += 1

            if steps >= config.MAX_AGENT_STEPS:
                await self._send_status(ws, f"⚠️ Maximale Schrittanzahl ({config.MAX_AGENT_STEPS}) erreicht")

            # Auto-Learning: Bei mehrstufigen Aufgaben den Loesungsweg speichern
            if steps >= 3 and self._tool_stats:
                failed = [s for s in self._tool_stats if not s["success"]]
                succeeded = [s for s in self._tool_stats if s["success"]]
                if failed and succeeded:
                    # Es gab Fehlversuche gefolgt von Erfolg → lernenswert
                    _log(f"Auto-Learning: {len(failed)} Fehlversuche, {len(succeeded)} Erfolge bei {steps} Steps")
                    # Dem LLM den Auftrag geben, den Weg zu speichern
                    learning_hint = (
                        f"\n\nWICHTIG – AUTO-LEARNING: Du hast fuer diese Aufgabe {steps} Schritte gebraucht "
                        f"mit {len(failed)} Fehlversuchen. Speichere JETZT den erfolgreichen Loesungsweg "
                        f"mit memory_manage(action='save', key='strategie_...', value='...'), "
                        f"damit du es beim naechsten Mal schneller schaffst."
                    )
                    # Letzten LLM-Aufruf mit Learning-Hint
                    try:
                        chat_history.append(
                            types.Content(role="user", parts=[types.Part.from_text(text=learning_hint)])
                        )
                        learn_response = await self.provider.generate_response(
                            model=config.current_model,
                            system_prompt=system_prompt,
                            contents=[
                                types.Content(role="user", parts=[types.Part.from_text(text=task_text)]),
                                *chat_history,
                            ],
                            tools=self._tool_instances
                        )
                        # Tool-Calls aus der Learning-Antwort ausfuehren (memory_manage)
                        if learn_response.parts:
                            for p in learn_response.parts:
                                if p.function_call and p.function_call.name == "memory_manage":
                                    await self._execute_tool("memory_manage", dict(p.function_call.args))
                                    await self._send_status(ws, "🧠 Strategie gelernt und gespeichert")
                    except Exception as le:
                        _log(f"Auto-Learning fehlgeschlagen: {le}")

        except Exception as e:
            import traceback; _log(f"EXCEPTION: {e}\n{traceback.format_exc()}")
            await self._send_status(ws, _friendly_api_error(e))
            tracer.end_span(agent_span, status="error", error=str(e))
            agent_span = None  # Verhindern, dass finally nochmal beendet
        finally:
            _log(f"run_task beendet (state={self.state.value})")
            if agent_span:
                tracer.end_span(agent_span)
            self.state = AgentState.IDLE

    async def run_task_headless(self, task_text: str) -> str:
        """Führt eine Aufgabe ohne WebSocket aus. Gibt das Ergebnis als String zurück.

        Wird von der WhatsApp-Pipeline genutzt.
        """
        self.state = AgentState.RUNNING
        self._stop_flag = False
        self._pause_event.set()

        # Provider neu initialisieren
        self.provider = get_provider(
            config.LLM_PROVIDER,
            config.current_api_key,
            config.current_api_url,
            auth_method=config.current_auth_method,
            session_key=config.current_session_key,
            prompt_tool_calling=config.current_prompt_tool_calling,
        )

        # System-Prompt zusammenbauen
        system_prompt = self.SYSTEM_PROMPT
        instructions = load_instructions()
        if instructions:
            system_prompt += f"\n\n{instructions}"
        memory_context = load_selective_memory(task_text)
        if memory_context:
            system_prompt += f"\n\n{memory_context}"

        collected_texts = []

        try:
            chat_history = []

            response = await self.provider.generate_response(
                model=config.current_model,
                system_prompt=system_prompt,
                contents=[
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=task_text)],
                    )
                ],
                tools=self._tool_instances
            )

            steps = 0
            while steps < config.MAX_AGENT_STEPS:
                if self._stop_flag:
                    break

                if not response.parts:
                    break

                function_calls = [p.function_call for p in response.parts if p.function_call]
                text_parts = [p.text for p in response.parts if p.text]

                for text in text_parts:
                    if text.strip():
                        collected_texts.append(text.strip())

                if not function_calls:
                    break

                function_response_parts = []
                for fc in function_calls:
                    tool_name = fc.name
                    tool_args = dict(fc.args) if fc.args else {}
                    result = await self._execute_tool(tool_name, tool_args)
                    result_str = str(result)[:5000]

                    # Tool-Statistik tracken
                    is_error = any(marker in result_str[:200].lower() for marker in
                                   ['fehler', 'error', '❌', 'traceback', 'exception', 'not found', 'failed'])
                    self._tool_stats.append({
                        "tool": tool_name, "step": steps,
                        "success": not is_error, "args_preview": json.dumps(tool_args, ensure_ascii=False)[:100]
                    })

                    function_response_parts.append(
                        types.Part.from_function_response(
                            name=tool_name,
                            response={"result": result_str},
                        )
                    )

                if config.LLM_PROVIDER == "google":
                    chat_history.append(response.raw.candidates[0].content)
                else:
                    parts = []
                    for p in response.parts:
                        if p.text:
                            parts.append(types.Part.from_text(text=p.text))
                        if p.function_call:
                            parts.append(types.Part(function_call=types.FunctionCall(
                                name=p.function_call.name, args=p.function_call.args)))
                    chat_history.append(types.Content(role="model", parts=parts))

                chat_history.append(
                    types.Content(role="user", parts=function_response_parts)
                )

                response = await self.provider.generate_response(
                    model=config.current_model,
                    system_prompt=system_prompt,
                    contents=[
                        types.Content(
                            role="user",
                            parts=[types.Part.from_text(text=task_text)],
                        ),
                        *chat_history,
                    ],
                    tools=self._tool_instances
                )

                steps += 1

            # Auto-Learning (gleiche Logik wie in run_task)
            if steps >= 3 and self._tool_stats:
                failed = [s for s in self._tool_stats if not s["success"]]
                succeeded = [s for s in self._tool_stats if s["success"]]
                if failed and succeeded:
                    _log(f"Auto-Learning (headless): {len(failed)} Fehlversuche, {len(succeeded)} Erfolge")
                    learning_hint = (
                        f"\n\nWICHTIG – AUTO-LEARNING: Du hast {steps} Schritte gebraucht "
                        f"mit {len(failed)} Fehlversuchen. Speichere den erfolgreichen Loesungsweg "
                        f"mit memory_manage(action='save', key='strategie_...', value='...')."
                    )
                    try:
                        chat_history.append(
                            types.Content(role="user", parts=[types.Part.from_text(text=learning_hint)])
                        )
                        learn_response = await self.provider.generate_response(
                            model=config.current_model, system_prompt=system_prompt,
                            contents=[
                                types.Content(role="user", parts=[types.Part.from_text(text=task_text)]),
                                *chat_history,
                            ],
                            tools=self._tool_instances
                        )
                        if learn_response.parts:
                            for p in learn_response.parts:
                                if p.function_call and p.function_call.name == "memory_manage":
                                    await self._execute_tool("memory_manage", dict(p.function_call.args))
                    except Exception as le:
                        _log(f"Auto-Learning (headless) fehlgeschlagen: {le}")

        except Exception as e:
            collected_texts.append(f"Fehler: {str(e)}")
        finally:
            self.state = AgentState.IDLE

        return "\n".join(collected_texts) if collected_texts else "Aufgabe ausgefuehrt (keine Textausgabe)."

    async def _execute_tool(self, name: str, args: dict, ws=None) -> str:
        """Fuehrt ein Tool aus. Bei Streaming-Tools wird Live-Output gesendet."""
        from backend.telemetry import tracer
        tool = self.tools_map.get(name)
        if not tool:
            return f"Fehler: Tool '{name}' nicht gefunden"

        span = tracer.start_span(name, kind="tool", parent_id=self.agent_id)
        span.attributes["tool.name"] = name
        span.attributes["agent.id"] = self.agent_id
        try:
            # Streaming-Callback fuer Tools die es unterstuetzen (z.B. shell_execute)
            if ws and getattr(tool, 'supports_streaming', False):
                args['_status_callback'] = lambda msg: self._send_status(ws, msg)
            result = await tool.execute(**args)
            tracer.end_span(span, status="ok")
            return result
        except Exception as e:
            tracer.end_span(span, status="error", error=str(e))
            return f"Fehler bei {name}: {str(e)}"

    async def _handle_spawn(self, ws: WebSocket, label: str, task: str) -> str:
        """Startet einen Sub-Agent ueber den AgentManager."""
        import sys
        print(f"[AGENT] _handle_spawn: label={label} task={task[:80]}", flush=True)
        try:
            # AgentManager aus main.py holen
            from backend.main import agent_manager
            if agent_manager is None:
                print(f"[AGENT] FEHLER: agent_manager ist None!", flush=True)
                return f"Sub-Agent '{label}' konnte nicht gestartet werden (kein AgentManager)"

            sub = agent_manager.spawn_sub_agent(label, task)
            asyncio.create_task(agent_manager.run_sub_agent(sub, task, ws))
            return f"Sub-Agent '{label}' gestartet (ID: {sub.agent_id})"
        except Exception as e:
            return f"Fehler beim Starten von Sub-Agent '{label}': {e}"

    async def _check_controls(self, ws: WebSocket):
        """Prüft Pause/Stop-Status."""
        if not self._pause_event.is_set():
            await self._send_status(ws, "⏸️ Pausiert – warte auf Fortsetzen...")
            await self._pause_event.wait()

    async def _send_status(self, ws: WebSocket, message: str, highlight: bool = False):
        """Sendet Status-Update an Frontend (mit agent_id fuer Multi-Agent)."""
        try:
            msg = {
                "type": "status",
                "message": message,
                "state": self.state.value,
                "agent_id": self.agent_id,
                "agent_label": self.label,
                "is_sub_agent": self.is_sub_agent,
            }
            if highlight:
                msg["highlight"] = True
            await ws.send_json(msg)
        except Exception:
            pass

    # ─── Steuerung ────────────────────────────────────────────────────
    def pause(self):
        self.state = AgentState.PAUSED
        self._pause_event.clear()

    def resume(self):
        self.state = AgentState.RUNNING
        self._pause_event.set()

    def stop(self):
        self._stop_flag = True
        self.state = AgentState.STOPPED
        self._pause_event.set()  # Falls pausiert, aufwecken zum Beenden

    def set_speed(self, speed: float):
        self._speed = max(0.1, min(5.0, speed))

    def get_info(self) -> dict:
        """Agent-Info fuer Frontend."""
        return {
            "agent_id": self.agent_id,
            "label": self.label,
            "state": self.state.value,
            "is_sub_agent": self.is_sub_agent,
            "parent_id": self.parent_id,
            "created_at": self._created_at,
        }


class AgentManager:
    """Verwaltet Haupt- und Sub-Agents."""

    def __init__(self):
        self.agents: dict[str, JarvisAgent] = {}
        self.main_agent: JarvisAgent | None = None
        self._ws: WebSocket | None = None

    def get_or_create_main(self) -> JarvisAgent:
        """Gibt den Hauptagent zurueck oder erstellt ihn."""
        if self.main_agent is None:
            self.main_agent = JarvisAgent(label="Hauptagent")
            self.agents[self.main_agent.agent_id] = self.main_agent
        return self.main_agent

    def spawn_sub_agent(self, label: str, task: str) -> JarvisAgent:
        """Erstellt einen neuen Sub-Agent."""
        parent = self.main_agent
        agent = JarvisAgent(
            label=label,
            is_sub_agent=True,
            parent_id=parent.agent_id if parent else None,
        )
        self.agents[agent.agent_id] = agent
        return agent

    def remove_agent(self, agent_id: str):
        """Entfernt einen beendeten Agent."""
        agent = self.agents.pop(agent_id, None)
        if agent and agent == self.main_agent:
            self.main_agent = None

    def get_agent(self, agent_id: str) -> JarvisAgent | None:
        return self.agents.get(agent_id)

    def get_sub_agents(self) -> list[JarvisAgent]:
        """Gibt alle Sub-Agents zurueck."""
        return [a for a in self.agents.values() if a.is_sub_agent]

    def get_all_info(self) -> list[dict]:
        """Info aller Agents fuer Frontend."""
        result = []
        if self.main_agent:
            result.append(self.main_agent.get_info())
        for a in self.get_sub_agents():
            result.append(a.get_info())
        return result

    async def run_sub_agent(self, agent: JarvisAgent, task: str, ws: WebSocket):
        """Startet einen Sub-Agent als async Task."""
        import sys
        print(f"[AGENT-MGR] run_sub_agent aufgerufen: id={agent.agent_id} label={agent.label} task={task[:80]}", flush=True)
        # Agent-Start ans Frontend melden
        await ws.send_json({
            "type": "agent_event",
            "event": "spawned",
            "agent": agent.get_info(),
            "agents": self.get_all_info(),
        })

        try:
            await agent.run_task(task, ws)
        finally:
            # Nur 'finished' melden wenn nicht pausiert (Pause = Agent lebt weiter)
            if agent.state != AgentState.PAUSED:
                agent.state = AgentState.IDLE
                await ws.send_json({
                    "type": "agent_event",
                    "event": "finished",
                    "agent": agent.get_info(),
                    "agents": self.get_all_info(),
                })
            else:
                # Pausiert: nur State-Update senden, kein finished
                await ws.send_json({
                    "type": "agent_event",
                    "event": "paused",
                    "agent": agent.get_info(),
                    "agents": self.get_all_info(),
                })

    def stop_all(self):
        """Stoppt alle Agents."""
        for agent in self.agents.values():
            agent.stop()
