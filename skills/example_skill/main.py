"""Beispiel-Skill – Vorlage für eigene Erweiterungen."""

from backend.tools.base import BaseTool


class ExampleGreetTool(BaseTool):
    """Ein einfaches Beispiel-Tool als Vorlage."""

    @property
    def name(self) -> str:
        return "example_greet"

    @property
    def description(self) -> str:
        return "Begrüßt eine Person mit Namen. (Beispiel-Skill)"

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "name": {
                    "type": "STRING",
                    "description": "Name der Person",
                },
            },
            "required": ["name"],
        }

    async def execute(self, name: str = "Welt", **kwargs) -> str:
        return f"Hallo {name}! Ich bin Jarvis, dein KI-Agent. 🤖"


def get_tools():
    """Gibt die Tools dieses Skills zurück."""
    return [ExampleGreetTool()]
