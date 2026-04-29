"""Jarvis Agent – Kern-Loop: LLM ↔ Tools, Multi-Agent Support."""

import asyncio
import base64
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
    # Gemini SDK-Fehler (google.genai.errors.ServerError) enthalten kein "google" im str(),
    # daher auch anhand von Fehlercodes und -status erkennen
    _is_gemini = (
        "google" in raw.lower() or "gemini" in raw.lower()
        or "generativelanguage" in raw.lower()
        or type(exc).__module__.startswith("google")
    )
    if _is_gemini:
        if "quota" in raw.lower() or "429" in raw or "RESOURCE_EXHAUSTED" in raw:
            return "🟡 **Google API-Limit**: Tages- oder Minutenkontingent erschöpft. Bitte warten oder anderen Provider wählen."
        if "503" in raw or "UNAVAILABLE" in raw or "high demand" in raw.lower() or "502" in raw:
            return (
                "🟡 **Gemini temporär nicht verfügbar**: Das KI-Modell ist gerade überlastet.\n"
                "💡 Bitte kurz warten und die Anfrage nochmal senden."
            )
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

    # ── Generische Überlastungs-/Verfügbarkeitsfehler (providerunabhängig) ──
    if "503" in raw or "UNAVAILABLE" in raw or "high demand" in raw.lower() or "temporarily unavailable" in raw.lower():
        return (
            "🟡 **KI-Modell temporär nicht verfügbar**: Der Anbieter ist gerade überlastet.\n"
            "💡 Bitte kurz warten und die Anfrage nochmal senden."
        )
    if "429" in raw or "rate limit" in raw.lower() or "RESOURCE_EXHAUSTED" in raw:
        return "🟡 **Rate-Limit**: Zu viele Anfragen – bitte kurz warten und nochmal versuchen."

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
import backend.conv_log as conv_log

# ── Sicherheit: LDAP-Benutzer duerfen diese Tools NICHT verwenden ─────────
_LOCAL_PRIVILEGED_USERS = {"jarvis", "root", ""}
_BLOCKED_TOOLS_FOR_LDAP = {
    "write_file",          # Kein Dateisystem-Schreibzugriff
    "spawn_agent",         # Keine Sub-Agents (koennten Shell nutzen)
    "write_clipboard",     # Kein Clipboard-Schreibzugriff
}

# Regex fuer Shell-Befehle die LDAP-Benutzern verboten sind
# (destruktive Operationen, Secret-Dateien, System-Aenderungen)
_LDAP_SHELL_FORBIDDEN = re.compile(
    r'\b(?:rm\b|rmdir\b|chmod\b|chown\b|chattr\b|'
    r'apt(?:-get)?\b|pip3?\s+install|npm\s+install|yum\s+install|dnf\s+install|'
    r'systemctl\s+(?:start|stop|restart|enable|disable|mask|daemon-reload)\b|'
    r'service\s+\S+\s+(?:start|stop|restart)\b|'
    r'reboot\b|shutdown\b|poweroff\b|halt\b|'
    r'dd\s|mkfs\b|fdisk\b|parted\b|'
    r'useradd\b|usermod\b|userdel\b|groupadd\b|passwd\b|'
    r'crontab\s+-[er]\b|'
    r'tee\s)',
    re.IGNORECASE,
)
# Schreib-Redirects und Secret-Pfade als separate Pattern
_LDAP_SHELL_WRITE_REDIRECT = re.compile(r'(?<![<|&])>\s*\S')
_LDAP_SHELL_SECRET_PATHS = re.compile(
    r'(?:/opt/jarvis/\.env\b|/home/jarvis/jarvis/\.env\b|auth_state\.json\b)',
    re.IGNORECASE,
)

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
1. WISSENSDATENBANK ZUERST: Bei Fragen zu Produkten, Software, Technik, Kunden oder internen Vorgaben IMMER zuerst knowledge_search aufrufen. Die lokale Wissensdatenbank enthaelt Kundendokumentation, Produkthandbuecher, technische Spezifikationen und Installationsanleitungen. NIEMALS direkt ins Internet gehen, wenn ein Produktname, Softwarename oder eine fachliche Frage gestellt wird – erst knowledge_search! Den Suchbegriff IMMER selbst aus der Benutzeranfrage ableiten – NIEMALS den Benutzer nach einem Suchbegriff fragen. Beispiel: "wie funktioniert LDT Import in Medistar?" → knowledge_search({"query": "LDT Import Medistar"}).
2. WISSENSFRAGEN AUS ALLGEMEINWISSEN: Nur bei eindeutigem Allgemeinwissen (Mathematik, Geografie, Geschichte, allgemeine Sprachfragen) antworte direkt. Bei allem mit Produktbezug oder Kundenbezug IMMER knowledge_search zuerst.
3. WISSENS-CACHE: Wenn du etwas ueber ein Tool nachgeschlagen hast, speichere es mit memory_manage (key mit Prefix "wissen_").
4. Arbeite Schritt fuer Schritt und erklaere kurz, was du tust.
5. Nutze shell_execute fuer Kommandozeilen-Befehle. Wenn Code ausgefuehrt werden soll, nutze shell_execute DIREKT.
6. Nutze desktop_* Tools um Programme auf dem LINUX-Desktop zu bedienen. Fuer den Windows-Desktop: windows_desktop Tool verwenden.
7. Nutze filesystem_* Tools um Dateien zu lesen/schreiben.
8. Mache Screenshots um den Desktop-Zustand zu pruefen (screenshot Tool fuer Linux, windows_desktop(action='screenshot') fuer Windows).
9. Wenn eine Aufgabe erledigt ist, sage es klar und deutlich.
10. Bei Fehlern: analysiere, versuche eine Alternative.
11. Antworte immer auf Deutsch.
12. Nutze memory_manage um wichtige Fakten dauerhaft zu speichern. Pruefe zu Beginn den Memory.
13. ABSOLUT VERBOTEN: Bevor du eine Webseite oder Suchmaschine oeffnest, MUSST du knowledge_search aufgerufen haben. Ohne vorherigen knowledge_search-Aufruf darf KEINE Webseite geoeffnet werden!
14. ABSOLUT VERBOTEN: Lies NIEMALS .docx, .pdf, .xlsx, .pptx, .doc, .xls Dateien direkt mit filesystem_read – diese sind Binaerdateien und liefern unlesbaren Muell. Fuer Inhalte aus diesen Dateien ausschliesslich knowledge_search verwenden. Der Inhalt ist dort bereits korrekt geparst und durchsuchbar.

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
        self._tool_cache: dict[str, str] = {}  # Tool-Ergebnis-Cache (lebt nur pro Task)

        # Kontext-Tracking (live während run_task; abfragbar via API)
        try:
            from backend.config import config as _cfg
            _saved_threshold = _cfg.get_setting("compress_threshold")
            self._compress_threshold: int = int(_saved_threshold) if _saved_threshold else 30
        except Exception:
            self._compress_threshold: int = 30   # Fallback
        self._current_chat_history: list = [] # Live-Referenz auf aktuelle History
        self._session_input_tokens:  int = 0  # Token-Zähler (aktuelle Session)
        self._session_output_tokens: int = 0  # Token-Zähler (aktuelle Session)
        self._user_histories: dict[str, list] = {}  # Persistente History pro User

        # Skill Manager initialisieren (laedt alle aktivierten Skills)
        self.skill_manager = SkillManager()

        # Tools aus SkillManager beziehen
        self._tool_instances = self.skill_manager.get_enabled_tools()

        # spawn_agent Tool hinzufuegen (nur fuer Hauptagent)
        if not is_sub_agent:
            from backend.tools.subagent import SpawnAgentTool
            self._tool_instances.append(SpawnAgentTool())

        # Windows Desktop Tool (immer verfügbar; gibt Fehler wenn kein Client verbunden)
        try:
            from backend.tools.windows_desktop import WindowsDesktopTool
            self._tool_instances.append(WindowsDesktopTool())
        except Exception as e:
            print(f"[AGENT {self.agent_id}] WindowsDesktopTool nicht geladen: {e}", flush=True)

        # Android Desktop Tool (immer verfügbar; gibt Fehler wenn kein Client verbunden)
        try:
            from backend.tools.android_desktop import AndroidDesktopTool
            self._tool_instances.append(AndroidDesktopTool())
        except Exception as e:
            print(f"[AGENT {self.agent_id}] AndroidDesktopTool nicht geladen: {e}", flush=True)

        # Clipboard Tools (xclip-basiert)
        try:
            from backend.tools.clipboard import ReadClipboardTool, WriteClipboardTool
            self._tool_instances.append(ReadClipboardTool())
            self._tool_instances.append(WriteClipboardTool())
        except Exception as e:
            print(f"[AGENT {self.agent_id}] ClipboardTools nicht geladen: {e}", flush=True)

        # Screenshot-Diff / Wartelogik
        try:
            from backend.tools.screenshot import WaitForChangeTool
            self._tool_instances.append(WaitForChangeTool())
        except Exception as e:
            print(f"[AGENT {self.agent_id}] WaitForChangeTool nicht geladen: {e}", flush=True)

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

    async def run_task(self, task_text: str, ws: WebSocket, client_type: str = "browser", client_ip: str = "unknown", username: str = ""):
        """Führt eine Aufgabe aus – der Agent-Loop."""
        import sys
        from backend.telemetry import tracer
        def _log(msg): print(f"[AGENT {self.agent_id}] {msg}", flush=True)
        _log(f"run_task gestartet: {task_text[:100]}... (sub={self.is_sub_agent})")
        self._current_username = username
        # Task im Audit-Log festhalten (unabhängig ob Tools genutzt werden)
        try:
            from backend.audit_log import log_task as _audit_task
            _audit_task(user=username or "unknown", task=task_text,
                        client_type=client_type, client_ip=client_ip)
        except Exception:
            pass
        agent_span = tracer.start_span(f"agent:{self.label}", kind="agent")
        agent_span.attributes["agent.id"] = self.agent_id
        agent_span.attributes["agent.is_sub"] = self.is_sub_agent
        agent_span.attributes["task"] = task_text[:200]

        self.state = AgentState.RUNNING
        self._stop_flag = False
        self._pause_event.set()
        self._tool_cache.clear()  # Cache für diesen Task-Run leeren

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

        # Desktop-Kontext je nach Client-Typ setzen
        if client_type == "windows_desktop":
            system_prompt += (
                "\n\nWICHTIG – DU LÄUFST ALS WINDOWS DESKTOP AGENT: "
                "Der Benutzer schickt Befehle von der Jarvis Windows App. "
                "ALLE Desktop-Aufgaben MÜSSEN mit dem Tool 'windows_desktop' ausgeführt werden. "
                "Nutze NIEMALS 'desktop_control' oder 'shell_execute' – diese steuern nur den Linux-Server.\n"
                "Verfügbare Aktionen (Auswahl):\n"
                "- Webseite öffnen:    windows_desktop(action='open_url', url='https://...')\n"
                "- Programm starten:   windows_desktop(action='open_app', text='notepad')\n"
                "- Klick:              windows_desktop(action='mouse_click', x=..., y=...)\n"
                "- Rechtsklick:        windows_desktop(action='right_click', x=..., y=...)\n"
                "- Doppelklick:        windows_desktop(action='mouse_double_click', x=..., y=...)\n"
                "- Drag & Drop:        windows_desktop(action='drag_and_drop', x=..., y=..., x2=..., y2=...)\n"
                "- Scrollen:           windows_desktop(action='scroll', x=..., y=..., direction='down', amount=3)\n"
                "- Text tippen:        windows_desktop(action='type_text', text='...')\n"
                "- Tastenkombination:  windows_desktop(action='key_press', key='ctrl+c')\n"
                "- Shell-Befehl:       windows_desktop(action='shell_exec', cmd='dir C:\\\\')\n"
                "- Fenster-Liste:      windows_desktop(action='list_windows')\n"
                "- Fenster fokus:      windows_desktop(action='focus_window', text='Teiltitel')\n"
                "- Fenster schließen:  windows_desktop(action='close_window', text='Teiltitel')\n"
                "- Minimieren:         windows_desktop(action='minimize_window')\n"
                "- Maximieren:         windows_desktop(action='maximize_window')\n"
                "Empfohlener Ablauf: 1) screenshot → 2) Aktion → 3) screenshot zur Bestätigung."
            )
        elif client_type == "android":
            system_prompt += (
                "\n\nWICHTIG – DU LÄUFST ALS ANDROID AGENT: "
                "Der Benutzer schickt Befehle von der Jarvis Android App auf seinem Android-Smartphone. "
                "NIEMALS 'desktop_control', 'shell_execute', 'screenshot' oder andere Linux-Desktop-Tools verwenden – "
                "diese steuern den Linux-Server, NICHT das Android-Gerät des Benutzers. "
                "Für ALLE Aktionen auf dem Android-Gerät (App starten, Shell-Befehle, Gerätinfo) "
                "das Tool 'android_desktop' verwenden. "
                "Verfügbare Aktionen: shell_exec (Shell-Befehl), launch_app (App starten per Name), "
                "open_url (URL im Standard-Browser öffnen, text=URL z.B. 'https://google.de'), "
                "list_apps (installierte Apps anzeigen), get_info (Gerätinformationen). "
                "Empfohlener Ablauf: 1) get_info um Gerät zu identifizieren, "
                "2) list_apps wenn App-Name unklar, 3) launch_app um App zu starten. "
                "Für 'öffne Browser' oder 'öffne URL': open_url mit der gewünschten URL verwenden."
            )
        else:
            # Browser: Linux-Desktop ist der richtige Kontext (Standard)
            pass

        # LDAP-Benutzer: Eingeschränkter Systemprompt-Zusatz
        if not self.is_sub_agent and username and username not in _LOCAL_PRIVILEGED_USERS:
            system_prompt += (
                "\n\nWICHTIG – EINGESCHRÄNKTE BENUTZERRECHTE (LDAP/Netzwerk-Benutzer): "
                "Dieser Benutzer ist ein normaler Netzwerk-Benutzer ohne Administrator-Rechte. "
                "ABSOLUT VERBOTEN: Shell-Befehle die Dateien schreiben oder löschen (rm, mv, cp auf sensible Pfade, "
                "dd, mkfs, etc.), Redirect-Schreiben (> in Datei), Paketinstallationen (apt, pip, npm install), "
                "System-Dienste steuern (systemctl start/stop/restart), Nutzerkonten verwalten (useradd, passwd), "
                "System neustarten (reboot, shutdown). "
                "ABSOLUT VERBOTEN: Secrets, Credentials oder API-Keys auslesen "
                "(.env-Dateien, auth_state.json, API-Key-Felder in settings.json). "
                "ERLAUBT: Alle Lese-Operationen auf nicht-sensiblen Dateien, Wissensdatenbank, "
                "Systeminformationen (date, ls, df, free, uname, ps, top, uptime, etc.), "
                "Allgemeinwissen, Berechnungen, Textverarbeitung. "
                "Bei Anfragen auf gesperrte Ressourcen: Höflich ablehnen und erklären was nicht erlaubt ist."
            )

        # Benutzer-Instruktionen laden (data/instructions/*.md)
        instructions = load_instructions()
        if instructions:
            system_prompt += f"\n\n{instructions}"
            await self._send_status(ws, "📋 Instruktionen geladen")

        # Memory-Kontext laden (selektiv nach Aufgabe + Strategien/Tipps, user-spezifisch)
        memory_context = load_selective_memory(task_text, username=username)
        if memory_context:
            system_prompt += f"\n\n{memory_context}"
            await self._send_status(ws, "🧠 Memory geladen")

        _conv_messages = []   # Für conv_log: alle LLM-Ein/Ausgaben dieser Konversation
        _task_start_time = time.time()
        try:
            # Konversation starten – pro User persistente History weiterverwenden
            _history_key = username or "anonymous"
            if self.is_sub_agent:
                chat_history = []
            else:
                chat_history = self._user_histories.get(_history_key, [])
            self._current_chat_history  = chat_history  # Live-Referenz für Context-Stats-API
            self._session_input_tokens  = 0             # Token-Zähler zurücksetzen
            self._session_output_tokens = 0
            task_start_time = _task_start_time
            _total_input_tokens  = 0
            _total_output_tokens = 0

            # Modus-Hinweis (hilfreich bei langsamen lokalen Modellen)
            mode_hint = " [Prompt-Tool-Modus]" if getattr(self.provider, "prompt_tool_calling", False) else ""
            await self._send_status(ws, f"⏳ Warte auf LLM-Antwort…{mode_hint}", highlight=True)

            # Initial-Nachricht senden – ggf. mit vorheriger Chat-History als Kontext
            _log(f"LLM-Aufruf mit {len(self._tool_instances)} Tools...")
            _user_msg = types.Content(role="user", parts=[types.Part.from_text(text=task_text)])
            llm_span = tracer.start_span("llm:initial", kind="llm", parent_id=self.agent_id)
            llm_span.attributes["model"] = config.current_model
            response = await self.provider.generate_response(
                model=config.current_model,
                system_prompt=system_prompt,
                contents=[*chat_history, _user_msg],
                tools=self._tool_instances
            )
            tracer.end_span(llm_span)
            if response.usage:
                _total_input_tokens  += response.usage.get("input_tokens", 0)
                _total_output_tokens += response.usage.get("output_tokens", 0)
                self._session_input_tokens  = _total_input_tokens
                self._session_output_tokens = _total_output_tokens
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
                # intermediate=True wenn gleichzeitig Tool-Aufrufe kommen (kein Endergebnis)
                is_intermediate = bool(function_calls)
                for text in text_parts:
                    if text.strip():
                        await self._send_status(ws, text.strip(), highlight=True, intermediate=is_intermediate)
                        _conv_messages.append({"role": "assistant", "content": text.strip()})

                # Wenn keine Function Calls → fertig; User+Antwort in History eintragen
                if not function_calls:
                    chat_history.append(_user_msg)
                    if config.LLM_PROVIDER == "google" and hasattr(response, 'raw') and response.raw and response.raw.candidates:
                        chat_history.append(response.raw.candidates[0].content)
                    else:
                        _resp_parts = []
                        for p in response.parts:
                            if p.text: _resp_parts.append(types.Part.from_text(text=p.text))
                        if _resp_parts:
                            chat_history.append(types.Content(role="model", parts=_resp_parts))
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

                    # Screenshot-Bild erkennen (IMAGE_BASE64:pfad|base64data)
                    image_part = None
                    if isinstance(result, str) and result.startswith("IMAGE_BASE64:"):
                        try:
                            _, rest = result.split(":", 1)
                            _img_path, b64data = rest.split("|", 1)
                            png_bytes = base64.b64decode(b64data)
                            image_part = types.Part.from_bytes(data=png_bytes, mime_type="image/png")
                            size_kb = len(png_bytes) // 1024
                            result_str = f"✅ Windows-Screenshot ({size_kb} KB) – Bildinhalt folgt direkt."
                            _log(f"Screenshot-Bild als Inline-Part vorbereitet ({size_kb} KB)")
                        except Exception as img_err:
                            _log(f"Screenshot-Inline-Parse fehlgeschlagen: {img_err}")

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
                    _conv_messages.append({"role": "tool", "tool": tool_name, "content": result_str})

                    function_response_parts.append(
                        types.Part.from_function_response(
                            name=tool_name,
                            response={"result": result_str},
                        )
                    )
                    # Bild als separaten Inline-Part anfügen (Gemini Multimodal)
                    if image_part:
                        function_response_parts.append(image_part)

                # Geschwindigkeits-Verzögerung
                if self._speed < 1.0:
                    delay = (1.0 / self._speed) - 1.0
                    await asyncio.sleep(delay)

                # Nächsten LLM-Aufruf mit Tool-Ergebnissen
                # Beim ersten Tool-Step: User-Nachricht als Anker in History einbauen
                if steps == 0 and (not chat_history or chat_history[-1] != _user_msg):
                    chat_history.append(_user_msg)
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

                # Kontextfenster-Management: lange Historien komprimieren
                chat_history = await self._compress_history(chat_history, system_prompt)

                llm_span = tracer.start_span(f"llm:step_{steps+1}", kind="llm", parent_id=self.agent_id)
                llm_span.attributes["model"] = config.current_model
                response = await self.provider.generate_response(
                    model=config.current_model,
                    system_prompt=system_prompt,
                    contents=chat_history,
                    tools=self._tool_instances
                )
                tracer.end_span(llm_span)
                if response.usage:
                    _total_input_tokens  += response.usage.get("input_tokens", 0)
                    _total_output_tokens += response.usage.get("output_tokens", 0)
                    self._session_input_tokens  = _total_input_tokens
                    self._session_output_tokens = _total_output_tokens

                steps += 1

            if steps >= config.MAX_AGENT_STEPS:
                await self._send_status(ws, f"⚠️ Maximale Schrittanzahl ({config.MAX_AGENT_STEPS}) erreicht")

            # LLM-Stats senden (Dauer + Token-Verbrauch)
            _task_duration_ms = int((time.time() - task_start_time) * 1000)
            await self._send_llm_stats(ws, _task_duration_ms, _total_input_tokens, _total_output_tokens, steps)

            # Konversation im Verlauf-Log speichern
            if not self.is_sub_agent:
                try:
                    conv_log.log_conversation(
                        task=task_text,
                        model=config.current_model,
                        client_ip=client_ip,
                        client_type=client_type,
                        system_prompt=system_prompt,
                        messages=_conv_messages,
                        steps=steps,
                        duration_ms=_task_duration_ms,
                        username=username,
                    )
                except Exception as cl_err:
                    _log(f"conv_log fehlgeschlagen: {cl_err}")
                # Chat-History für nächste Anfrage dieses Users speichern
                self._user_histories[_history_key] = chat_history

            # Auto-Learning: Bei mehrstufigen Aufgaben den Loesungsweg speichern
            if steps >= 2 and self._tool_stats:
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
            err_msg = _friendly_api_error(e)
            await self._send_status(ws, err_msg)
            tracer.end_span(agent_span, status="error", error=str(e))
            agent_span = None  # Verhindern, dass finally nochmal beendet
            # History auch bei Fehler zurückspeichern
            if not self.is_sub_agent and chat_history:
                self._user_histories[_history_key] = chat_history
            if not self.is_sub_agent:
                try:
                    _dur = int((time.time() - _task_start_time) * 1000)
                    conv_log.log_conversation(
                        task=task_text,
                        model=config.current_model,
                        client_ip=client_ip,
                        client_type=client_type,
                        system_prompt=system_prompt if 'system_prompt' in locals() else "",
                        messages=_conv_messages,
                        steps=0,
                        duration_ms=_dur,
                        error=str(e)[:300],
                        username=username,
                    )
                except Exception:
                    pass
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
        memory_context = load_selective_memory(task_text, username=getattr(self, '_current_username', ''))
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

                    # Screenshot-Bild erkennen (IMAGE_BASE64:pfad|base64data)
                    image_part = None
                    if isinstance(result, str) and result.startswith("IMAGE_BASE64:"):
                        try:
                            _, rest = result.split(":", 1)
                            _img_path, b64data = rest.split("|", 1)
                            png_bytes = base64.b64decode(b64data)
                            image_part = types.Part.from_bytes(data=png_bytes, mime_type="image/png")
                            result_str = f"✅ Screenshot ({len(png_bytes)//1024} KB) – Bildinhalt folgt direkt."
                        except Exception:
                            pass

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
                    if image_part:
                        function_response_parts.append(image_part)

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
            if steps >= 2 and self._tool_stats:
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

    # Tools, deren Ergebnisse innerhalb eines Task-Runs gecacht werden können
    _CACHEABLE_TOOLS = {"read_file", "screenshot", "read_clipboard"}

    async def _execute_tool(self, name: str, args: dict, ws=None) -> str:
        """Fuehrt ein Tool aus. Bei Streaming-Tools wird Live-Output gesendet."""
        import json as _json
        import time as _time
        from backend.telemetry import tracer

        # Cache-Check für cacheable Tools
        if name in self._CACHEABLE_TOOLS:
            cache_key = f"{name}:{_json.dumps(args, sort_keys=True)}"
            if cache_key in self._tool_cache:
                return self._tool_cache[cache_key]

        tool = self.tools_map.get(name)
        if not tool:
            return f"Fehler: Tool '{name}' nicht gefunden"

        span = tracer.start_span(name, kind="tool", parent_id=self.agent_id)
        span.attributes["tool.name"] = name
        span.attributes["agent.id"] = self.agent_id
        try:
            # Streaming-Callback fuer Tools die es unterstuetzen (z.B. shell_execute)
            # Kopie anlegen um den Original-Dict nicht zu mutieren (json.dumps wuerde sonst scheitern)
            exec_args = dict(args)
            if ws and getattr(tool, 'supports_streaming', False):
                exec_args['_status_callback'] = lambda msg: self._send_status(ws, msg)
            # Benutzer-spezifischer Memory-Namespace
            if name == "memory_manage":
                exec_args.setdefault('_username', getattr(self, '_current_username', ''))
            # Read-Only Skill: schreibende Tools blockieren
            _WRITE_TOOLS = {"shell_execute", "write_file", "desktop_action"}
            if name in _WRITE_TOOLS and self.skill_manager.is_tool_readonly(name):
                result = f"Zugriff verweigert: Das Tool '{name}' ist in diesem Read-Only Skill nicht erlaubt."
                tracer.end_span(span, status="ok")
                return result

            # LDAP-Benutzer: Sicherheitskritische Tools und Befehle blockieren
            _uname = getattr(self, '_current_username', '')
            _t0 = _time.monotonic()
            _ldap_blocked = False
            if _uname and _uname not in _LOCAL_PRIVILEGED_USERS:
                if name in _BLOCKED_TOOLS_FOR_LDAP:
                    print(f"[AGENT] BLOCKED Tool '{name}' fuer LDAP-User '{_uname}'", flush=True)
                    result = f"Zugriff verweigert: Das Tool '{name}' steht LDAP-Benutzern nicht zur Verfuegung."
                    _ldap_blocked = True
                elif name == "shell_execute":
                    _cmd = args.get("command", "")
                    if _LDAP_SHELL_FORBIDDEN.search(_cmd):
                        print(f"[AGENT] BLOCKED shell command for LDAP-User '{_uname}': {_cmd[:80]}", flush=True)
                        result = "Zugriff verweigert: Dieser Shell-Befehl ist für LDAP-Benutzer nicht erlaubt (keine System-Änderungen)."
                        _ldap_blocked = True
                    elif _LDAP_SHELL_WRITE_REDIRECT.search(_cmd):
                        print(f"[AGENT] BLOCKED shell write-redirect for LDAP-User '{_uname}': {_cmd[:80]}", flush=True)
                        result = "Zugriff verweigert: Datei-Schreiben via Shell ist für LDAP-Benutzer nicht erlaubt."
                        _ldap_blocked = True
                    elif _LDAP_SHELL_SECRET_PATHS.search(_cmd):
                        print(f"[AGENT] BLOCKED shell secret-path for LDAP-User '{_uname}': {_cmd[:80]}", flush=True)
                        result = "Zugriff verweigert: Zugriff auf diese Datei ist für LDAP-Benutzer nicht erlaubt."
                        _ldap_blocked = True
            if not _ldap_blocked:
                result = await tool.execute(**exec_args)
            _dur_ms = int((_time.monotonic() - _t0) * 1000)
            tracer.end_span(span, status="ok")
            # Ergebnis cachen wenn Tool cacheable ist
            if name in self._CACHEABLE_TOOLS:
                cache_key = f"{name}:{_json.dumps(args, sort_keys=True)}"
                self._tool_cache[cache_key] = result
            # Audit-Log
            try:
                from backend.audit_log import log_tool as _audit
                _audit(
                    user=getattr(self, '_current_username', '') or 'unknown',
                    tool=name,
                    args=args,
                    result_len=len(result) if result else 0,
                    duration_ms=_dur_ms,
                )
            except Exception:
                pass
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

    async def _compress_history(self, chat_history: list, system_prompt: str) -> list:
        """Komprimiert lange Chat-Historien: Zusammenfassung der älteren Nachrichten."""
        # Nur komprimieren wenn über dem Schwellwert
        if len(chat_history) <= self._compress_threshold:
            return chat_history

        # Letzte 4 Nachrichten behalten
        keep = chat_history[-4:]
        to_summarize = chat_history[:-4]

        # Bisherigen Dialog für die Zusammenfassung als Text extrahieren
        dialog_text = []
        for entry in to_summarize:
            try:
                role = getattr(entry, "role", "unknown")
                parts = getattr(entry, "parts", [])
                for p in parts:
                    t = getattr(p, "text", None)
                    if t:
                        dialog_text.append(f"[{role}] {t[:300]}")
            except Exception:
                pass

        if not dialog_text:
            return keep  # Nichts zu komprimieren

        summary_prompt = (
            "Fasse den folgenden Gesprächsabschnitt in maximal 300 Wörtern zusammen. "
            "Behalte alle wichtigen Fakten, Ergebnisse und Entscheidungen.\n\n"
            + "\n".join(dialog_text[:60])  # Maximal 60 Zeilen
        )

        try:
            summary_response = await self.provider.generate_response(
                model=config.current_model,
                system_prompt="Du fasst Gespräche zusammen. Antworte ausschließlich mit der Zusammenfassung.",
                contents=[
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=summary_prompt)],
                    )
                ],
                tools=[],
            )
            summary_text = ""
            if summary_response.parts:
                for p in summary_response.parts:
                    if p.text:
                        summary_text += p.text
            if summary_text:
                summary_entry = types.Content(
                    role="user",
                    parts=[types.Part.from_text(
                        text=f"[Zusammenfassung des bisherigen Gesprächs]\n{summary_text}"
                    )],
                )
                print(f"[AGENT {self.agent_id}] History komprimiert: {len(chat_history)} → {len(keep)+1} Einträge", flush=True)
                return [summary_entry] + keep
        except Exception as e:
            print(f"[AGENT {self.agent_id}] History-Kompression fehlgeschlagen: {e}", flush=True)

        # Fallback: nur letzte Einträge behalten
        return keep

    async def _check_controls(self, ws: WebSocket):
        """Prüft Pause/Stop-Status."""
        if not self._pause_event.is_set():
            await self._send_status(ws, "⏸️ Pausiert – warte auf Fortsetzen...")
            await self._pause_event.wait()

    async def _send_status(self, ws: WebSocket, message: str, highlight: bool = False, intermediate: bool = False):
        """Sendet Status-Update an Frontend (mit agent_id fuer Multi-Agent).
        intermediate=True: LLM-Text der neben Tool-Aufrufen steht (Zwischenantwort, kein Endergebnis).
        """
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
            if intermediate:
                msg["intermediate"] = True
            await ws.send_json(msg)
        except Exception:
            pass

    async def _send_llm_stats(self, ws, duration_ms: int, input_tokens: int, output_tokens: int, steps: int):
        """Sendet LLM-Statistiken (Dauer + Token-Verbrauch) an alle Clients."""
        try:
            await ws.send_json({
                "type": "llm_stats",
                "duration_ms": duration_ms,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "steps": steps,
                "agent_id": self.agent_id,
            })
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

    def get_context_stats(self) -> dict:
        """Gibt aktuelle Kontext-Statistiken zurück (History-Länge, Tokens, Schwellwert)."""
        history = self._current_chat_history
        n = len(history)
        # Groben Token-Schätzwert aus History-Text berechnen (~4 Zeichen pro Token)
        estimated_chars = 0
        for entry in history:
            try:
                for p in getattr(entry, "parts", []):
                    t = getattr(p, "text", None)
                    if t:
                        estimated_chars += len(t)
            except Exception:
                pass
        estimated_tokens = estimated_chars // 4
        return {
            "history_entries":    n,
            "compress_threshold": self._compress_threshold,
            "fills_pct":          round(min(100, n / max(1, self._compress_threshold) * 100), 1),
            "session_input_tokens":  self._session_input_tokens,
            "session_output_tokens": self._session_output_tokens,
            "session_total_tokens":  self._session_input_tokens + self._session_output_tokens,
            "estimated_history_tokens": estimated_tokens,
            "agent_state": self.state.value,
        }

    async def force_compress(self) -> dict:
        """Erzwingt sofortige History-Komprimierung (unabhängig vom Schwellwert)."""
        h = self._current_chat_history
        before = len(h)
        if before < 4:
            return {"before": before, "after": before, "skipped": True, "reason": "zu kurz"}
        # Temporär Schwellwert auf 0 setzen, komprimieren, dann Ergebnis zurückschreiben
        orig_threshold = self._compress_threshold
        self._compress_threshold = 0
        try:
            from backend.llm import get_provider
            compressed = await self._compress_history(h, "")
            # History in-place ersetzen (da _current_chat_history eine Referenz ist,
            # müssen wir den Inhalt der ursprünglichen Liste ersetzen)
            h.clear()
            h.extend(compressed)
        finally:
            self._compress_threshold = orig_threshold
        return {"before": before, "after": len(h), "skipped": False}

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
