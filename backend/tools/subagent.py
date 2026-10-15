"""Sub-Agent Tool – erlaubt dem Hauptagent, parallele Sub-Agents zu starten."""

import json

from backend.tools.base import BaseTool


class SpawnAgentTool(BaseTool):
    """Startet einen Sub-Agent fuer eine parallele Teilaufgabe."""

    @property
    def name(self) -> str:
        return "spawn_agent"

    @property
    def description(self) -> str:
        return (
            "Startet einen neuen Sub-Agent, der eine Teilaufgabe parallel bearbeitet. "
            "Jeder Sub-Agent arbeitet VOLLSTAENDIG AUTONOM und fuehrt Code direkt aus. "
            "WICHTIG: Gib die komplette Aufgabe im 'task'-Feld als klare Anweisung an. "
            "Wenn Code ausgefuehrt werden soll, schreibe den Code DIREKT ins 'task'-Feld, "
            "z.B.: 'Fuehre folgendes Python-Skript mit shell_execute aus: python3 -c \"print(42)\"'"
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "label": {
                    "type": "STRING",
                    "description": "Kurzer Name/Label fuer den Sub-Agent (optional, wird auto-generiert)",
                },
                "task": {
                    "type": "STRING",
                    "description": "Die vollstaendige Aufgabe inkl. ggf. auszufuehrendem Code",
                },
            },
            "required": ["task"],
        }

    async def execute(self, task: str = "", label: str = "", **kwargs) -> str:
        """Startet einen Sub-Agent. Wird ueber den AgentManager im WebSocket-Handler ausgefuehrt."""
        # Fehlertolerant: "name" statt "label", "code" statt/zusaetzlich zu "task"
        if not label:
            label = kwargs.get("name", "")

        code = kwargs.get("code", "")

        # Falls nur Code ohne Task: Code wird zur Aufgabe
        if not task and code:
            task = f"Fuehre folgenden Code mit shell_execute aus:\npython3 -c {repr(code)}"
        elif task and code:
            task += f"\n\nFuehre folgenden Code mit shell_execute aus:\npython3 -c {repr(code)}"

        if not task:
            return "Fehler: 'task' ist ein Pflichtfeld."

        # Label auto-generieren wenn nicht angegeben
        if not label:
            # Ersten sinnvollen Teil der Aufgabe als Label nehmen
            first_line = task.strip().split('\n')[0][:40]
            label = f"Sub-Agent: {first_line}"

        return json.dumps({
            "_spawn_agent": True,
            "label": label,
            "task": task,
        })
