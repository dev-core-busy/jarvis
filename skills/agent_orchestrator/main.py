"""Agent Orchestrator Skill – Koordiniert Sub-Agenten via Dateisystem.

Protokoll (aus references/communication-protocol.md):
  agent-workspaces/<name>/
    inbox/instructions.md   ← Aufgabe vom Orchestrator
    inbox/<input-files>     ← Eingabedaten
    outbox/<deliverables>   ← Ergebnisse des Sub-Agenten
    workspace/              ← Privater Arbeitsbereich
    status.json             ← Zustand: pending|running|completed|failed

Sub-Agenten-Typen: research, code, analysis, writer, review, integration
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.tools.base import BaseTool

# Basis-Verzeichnis für alle Agent-Workspaces
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_DEFAULT_ROOT = _PROJECT_ROOT / "data" / "agent-workspaces"


def _workspace_root() -> Path:
    try:
        from backend.config import config
        rel = config.get_skill_states().get("agent_orchestrator", {}).get("config", {}).get(
            "workspace_root", "data/agent-workspaces"
        )
        return _PROJECT_ROOT / rel
    except Exception:
        return _DEFAULT_ROOT


def _safe_name(name: str) -> str:
    """Bereinigt einen Namen zu einem sicheren Verzeichnisnamen."""
    return re.sub(r"[^\w\-]", "_", name.lower().strip())[:60]


def _read_status(workspace: Path) -> dict:
    status_file = workspace / "status.json"
    if status_file.exists():
        try:
            return json.loads(status_file.read_text())
        except Exception:
            pass
    return {"state": "unknown"}


def _write_status(workspace: Path, state: str, **extra):
    status = {"state": state, **extra}
    if state == "running" and "started" not in status:
        status["started"] = datetime.now(timezone.utc).isoformat()
    (workspace / "status.json").write_text(json.dumps(status, indent=2, ensure_ascii=False))


# ─── Tools ────────────────────────────────────────────────────────────

AGENT_TYPES = {
    "research":    "Recherchiert Informationen aus dem Web und Dokumenten.",
    "code":        "Schreibt, testet und refaktorisiert Code.",
    "analysis":    "Analysiert Daten, erkennt Muster, generiert Erkenntnisse.",
    "writer":      "Erstellt Dokumente, Berichte und Inhalte.",
    "review":      "Prüft Qualität, gibt Feedback, validiert Ergebnisse.",
    "integration": "Führt Ausgaben mehrerer Agenten zusammen.",
}


class OrchestrateTaskTool(BaseTool):
    """Erstellt Sub-Agenten-Workspaces für eine koordinierte Aufgabe."""

    @property
    def name(self) -> str:
        return "orchestrate_task"

    @property
    def description(self) -> str:
        return (
            "Zerlegt eine komplexe Aufgabe in Sub-Agenten und erstellt deren Workspaces. "
            "Jeder Sub-Agent bekommt eine inbox/instructions.md und einen status.json. "
            "Gibt eine Übersicht der erstellten Workspaces zurück. "
            "Danach: Jeden Sub-Agenten-Workspace selbst bearbeiten (inbox lesen → "
            "work → outbox befüllen → status=completed setzen). "
            "Sub-Agenten-Typen: research, code, analysis, writer, review, integration."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "session_name": {
                    "type": "string",
                    "description": "Name der Orchestrierungs-Session, z.B. 'marktanalyse-2024'",
                },
                "agents": {
                    "type": "array",
                    "description": "Liste der zu erstellenden Sub-Agenten",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name":         {"type": "string", "description": "Eindeutiger Name, z.B. 'web-recherche'"},
                            "type":         {"type": "string", "description": "research|code|analysis|writer|review|integration"},
                            "objective":    {"type": "string", "description": "Klares Ziel dieses Sub-Agenten"},
                            "inputs":       {"type": "string", "description": "Welche Eingaben werden bereitgestellt (optional)"},
                            "outputs":      {"type": "string", "description": "Erwartete Ausgaben in outbox/"},
                            "depends_on":   {"type": "array", "items": {"type": "string"}, "description": "Abhängigkeiten (andere Agent-Namen)"},
                        },
                        "required": ["name", "type", "objective"],
                    },
                },
            },
            "required": ["session_name", "agents"],
        }

    async def execute(self, **kwargs) -> str:
        session_name = _safe_name(kwargs.get("session_name", "session"))
        agents_spec  = kwargs.get("agents", [])

        if not agents_spec:
            return "❌ Keine Agenten angegeben."

        root = _workspace_root() / session_name
        root.mkdir(parents=True, exist_ok=True)

        created = []
        for spec in agents_spec:
            agent_name = _safe_name(spec.get("name", "agent"))
            agent_type = spec.get("type", "research").lower()
            objective  = spec.get("objective", "")
            inputs_txt = spec.get("inputs", "")
            outputs_txt = spec.get("outputs", "")
            depends_on = spec.get("depends_on", [])

            workspace = root / agent_name
            (workspace / "inbox").mkdir(parents=True, exist_ok=True)
            (workspace / "outbox").mkdir(parents=True, exist_ok=True)
            (workspace / "workspace").mkdir(parents=True, exist_ok=True)

            # instructions.md schreiben
            instructions = f"""# Task: {spec.get('name', agent_name)}

## Objective
{objective}

## Agent Type
{agent_type} – {AGENT_TYPES.get(agent_type, '')}

## Inputs Provided
{inputs_txt or '(keine spezifischen Eingabedateien – nutze vorhandenes Wissen)'}

## Output Expectations
{outputs_txt or f'Hauptergebnis in outbox/{agent_name}_result.md + outbox/summary.md'}

## Constraints
- Status in status.json pflegen: pending → running → completed/failed
- Bei Fehler: outbox/error_report.md erstellen
{f'- Abhängigkeiten abwarten: {", ".join(depends_on)}' if depends_on else ''}

## Communication Protocol
- Eingaben lesen aus: inbox/
- Ergebnisse schreiben nach: outbox/
- Zwischenergebnisse: workspace/
- Status-Updates: status.json
"""
            (workspace / "inbox" / "instructions.md").write_text(instructions)

            # Status initialisieren
            _write_status(workspace, "pending",
                          agent=agent_name,
                          type=agent_type,
                          depends_on=depends_on,
                          created=datetime.now(timezone.utc).isoformat())

            created.append(f"  • {agent_name} [{agent_type}]{' (wartet auf: ' + ', '.join(depends_on) + ')' if depends_on else ''}")

        lines = [
            f"✅ Session '{session_name}' erstellt mit {len(created)} Sub-Agent(en):",
            *created,
            "",
            f"📁 Workspace: data/agent-workspaces/{session_name}/",
            "",
            "→ Nächste Schritte:",
            "  1. agent_status() aufrufen um Übersicht zu sehen",
            "  2. Jeden Agenten bearbeiten: inbox/instructions.md lesen,",
            "     Arbeit ausführen, Ergebnisse in outbox/ schreiben,",
            "     status=completed setzen",
            "  3. agent_collect() zum Einsammeln der Ergebnisse",
        ]
        return "\n".join(lines)


class AgentStatusTool(BaseTool):
    """Zeigt Status aller Sub-Agenten einer Session."""

    @property
    def name(self) -> str:
        return "agent_status"

    @property
    def description(self) -> str:
        return (
            "Zeigt den aktuellen Status aller Sub-Agenten einer Orchestrierungs-Session "
            "(pending/running/completed/failed). Gibt auch Fortschritt und Blockierungen aus."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "session_name": {
                    "type": "string",
                    "description": "Name der Session (leer = alle Sessions anzeigen)",
                },
            },
            "required": [],
        }

    async def execute(self, **kwargs) -> str:
        session_name = _safe_name(kwargs.get("session_name", "")) if kwargs.get("session_name") else ""
        root = _workspace_root()

        if not root.exists():
            return "Keine Agent-Workspaces vorhanden."

        sessions = [root / session_name] if session_name else sorted(root.iterdir())
        lines = []

        for session_dir in sessions:
            if not session_dir.is_dir():
                continue
            lines.append(f"\n📁 Session: {session_dir.name}")
            agents = sorted(session_dir.iterdir())
            if not agents:
                lines.append("  (leer)")
                continue

            state_icons = {"pending": "⏸", "running": "🔄", "completed": "✅", "failed": "❌", "unknown": "❓"}
            for agent_dir in agents:
                if not agent_dir.is_dir():
                    continue
                status = _read_status(agent_dir)
                state  = status.get("state", "unknown")
                icon   = state_icons.get(state, "❓")
                progress = status.get("progress", {})
                prog_str = ""
                if progress and "steps_completed" in progress:
                    prog_str = f" ({progress['steps_completed']}/{progress.get('total_steps','?')} Schritte)"
                outbox = list((agent_dir / "outbox").glob("*")) if (agent_dir / "outbox").exists() else []
                out_str = f", {len(outbox)} Ausgabe(n)" if outbox else ""
                lines.append(f"  {icon} {agent_dir.name}: {state}{prog_str}{out_str}")
                if status.get("error"):
                    lines.append(f"     ⚠️  {status['error']}")

        return "\n".join(lines) if lines else "Keine Sessions gefunden."


class AgentCollectTool(BaseTool):
    """Sammelt alle Ergebnisse aus den outbox-Verzeichnissen einer Session."""

    @property
    def name(self) -> str:
        return "agent_collect"

    @property
    def description(self) -> str:
        return (
            "Sammelt und gibt alle Ergebnisse (outbox/summary.md und outbox/ Dateien) "
            "aus abgeschlossenen Sub-Agenten einer Session zurück."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "session_name": {
                    "type": "string",
                    "description": "Name der Session",
                },
                "agent_name": {
                    "type": "string",
                    "description": "Nur diesen Agenten lesen (leer = alle completed Agenten)",
                },
            },
            "required": ["session_name"],
        }

    async def execute(self, **kwargs) -> str:
        session_name = _safe_name(kwargs.get("session_name", ""))
        agent_filter = _safe_name(kwargs.get("agent_name", "")) if kwargs.get("agent_name") else ""
        session_dir  = _workspace_root() / session_name

        if not session_dir.exists():
            return f"❌ Session '{session_name}' nicht gefunden."

        results = []
        for agent_dir in sorted(session_dir.iterdir()):
            if not agent_dir.is_dir():
                continue
            if agent_filter and agent_dir.name != agent_filter:
                continue

            status = _read_status(agent_dir)
            if status.get("state") not in ("completed", "failed") and not agent_filter:
                continue

            outbox = agent_dir / "outbox"
            results.append(f"\n─── {agent_dir.name} [{status.get('state','?')}] ───")

            if not outbox.exists() or not list(outbox.iterdir()):
                results.append("  (keine Ausgaben)")
                continue

            # Zuerst summary.md, dann andere Dateien
            files = sorted(outbox.rglob("*"), key=lambda p: (p.name != "summary.md", p.name))
            for f in files:
                if not f.is_file():
                    continue
                rel = f.relative_to(outbox)
                results.append(f"\n📄 outbox/{rel}:")
                try:
                    content = f.read_text(errors="replace")
                    # Lange Dateien kürzen
                    if len(content) > 2000:
                        content = content[:2000] + "\n… [gekürzt]"
                    results.append(content)
                except Exception as e:
                    results.append(f"  (Lesefehler: {e})")

        return "\n".join(results) if results else "Keine abgeschlossenen Agenten gefunden."


class AgentListTool(BaseTool):
    """Listet alle vorhandenen Agent-Sessions auf."""

    @property
    def name(self) -> str:
        return "agent_list"

    @property
    def description(self) -> str:
        return "Listet alle vorhandenen Orchestrierungs-Sessions und ihre Sub-Agenten auf."

    def parameters_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs) -> str:
        root = _workspace_root()
        if not root.exists() or not list(root.iterdir()):
            return "Keine Agent-Sessions vorhanden. Mit orchestrate_task() eine neue Session starten."

        lines = [f"📁 Agent-Workspaces ({root}):"]
        for session in sorted(root.iterdir()):
            if not session.is_dir():
                continue
            agents = [d for d in session.iterdir() if d.is_dir()]
            states = [_read_status(a).get("state", "?") for a in agents]
            done   = sum(1 for s in states if s == "completed")
            lines.append(f"  • {session.name}: {len(agents)} Agent(en), {done} abgeschlossen")
        return "\n".join(lines)


def get_tools():
    return [
        OrchestrateTaskTool(),
        AgentStatusTool(),
        AgentCollectTool(),
        AgentListTool(),
    ]
