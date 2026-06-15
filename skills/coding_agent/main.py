"""Coding-Agent-Skill – startet einen autonomen Coding-Sub-Agenten,
der dem Staff-Engineer-Workflow aus verhalte_dich_wie_claude.md folgt.

Der Workflow-Text wird zur Laufzeit eingelesen und der Aufgabe vorangestellt,
sodass Aenderungen an verhalte_dich_wie_claude.md sofort wirken.
"""

import json
from pathlib import Path

from backend.tools.base import BaseTool

# Workflow-Datei liegt im Projekt-Root (skills/coding_agent/ -> ../../)
_WORKFLOW_FILE = Path(__file__).resolve().parent.parent.parent / "verhalte_dich_wie_claude.md"

# Fallback-Kurzworkflow, falls die Datei fehlt
_FALLBACK_WORKFLOW = (
    "Arbeite wie ein Staff-Engineer:\n"
    "1. PLANUNG: Zerlege die Aufgabe in Schritte, definiere Done-Kriterien.\n"
    "2. IMPLEMENTIERUNG: Minimaler, sauberer Eingriff – keine Hacks, Root-Cause beheben.\n"
    "3. REFLEXION: Pruefe das Ergebnis kritisch (Advocatus Diaboli).\n"
    "4. VERIFIZIERUNG: Teste/validiere, dass nichts kaputt ist.\n"
)


def _load_workflow() -> str:
    try:
        text = _WORKFLOW_FILE.read_text(encoding="utf-8").strip()
        return text or _FALLBACK_WORKFLOW
    except Exception:
        return _FALLBACK_WORKFLOW


class CodingAgentTool(BaseTool):
    """Startet einen autonomen Coding-Agenten fuer eine Entwicklungsaufgabe."""

    @property
    def name(self) -> str:
        return "coding_agent"

    @property
    def description(self) -> str:
        return (
            "Startet einen autonomen CODING-AGENTEN fuer eine Entwicklungsaufgabe "
            "(Code schreiben/aendern, Bugs fixen, refactoren, Tests). Er arbeitet strikt "
            "nach einem Staff-Engineer-Workflow (Planung -> Implementierung -> Reflexion -> "
            "Verifizierung) und fuehrt alles eigenstaendig mit shell_execute aus. "
            "Nutze dies fuer nicht-triviale, mehrstufige Coding-Aufgaben. "
            "Mehrere coding_agent-Aufrufe laufen parallel als eigene Agenten. "
            "Gib die komplette Aufgabe klar und konkret im 'task'-Feld an."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "task": {
                    "type": "STRING",
                    "description": "Die vollstaendige Entwicklungsaufgabe – klar, konkret, inkl. Kontext (Dateien/Ziele).",
                },
                "label": {
                    "type": "STRING",
                    "description": "Kurzes Label fuer den Agenten (optional, wird sonst aus der Aufgabe abgeleitet).",
                },
            },
            "required": ["task"],
        }

    async def execute(self, task: str = "", label: str = "", **kwargs) -> str:
        # Fehlertolerant: alternative Parameternamen
        task = (task or kwargs.get("aufgabe", "") or kwargs.get("code", "")).strip()
        if not task:
            return "Fehler: 'task' (Entwicklungsaufgabe) ist ein Pflichtfeld."

        workflow = _load_workflow()
        full_task = (
            "Du bist ein autonomer CODING-AGENT. Arbeite die folgende Aufgabe strikt nach "
            "diesem Staff-Engineer-Workflow ab:\n\n"
            f"{workflow}\n\n"
            "=== DEINE AUFGABE ===\n"
            f"{task}\n\n"
            "Arbeite VOLLSTAENDIG und AUTONOM (kein Rueckfragen). Fuehre Code/Tests direkt "
            "mit shell_execute aus. Halte den Eingriff minimal und sauber. Melde am Ende "
            "kurz: Ergebnis, geaenderte Dateien und ob die Verifizierung bestanden hat."
        )

        if not label:
            label = "Coding: " + task.split("\n")[0][:36]

        return json.dumps({
            "_spawn_agent": True,
            "label": label,
            "task": full_task,
        })


def get_tools():
    """Gibt die Tools dieses Skills zurueck."""
    return [CodingAgentTool()]
