"""Shell Tool – führt Kommandozeilen-Befehle aus."""

import asyncio

from backend.tools.base import BaseTool
from backend.config import config


class ShellTool(BaseTool):
    """Führt Shell-Befehle auf dem Linux-System aus."""

    @property
    def name(self) -> str:
        return "shell_execute"

    @property
    def description(self) -> str:
        return (
            "Führt einen Shell-Befehl (bash) auf dem Linux-System aus. "
            "Gibt stdout und stderr zurück. "
            "Nutze dies für: Dateien auflisten, Pakete installieren, "
            "Systeminformationen abfragen, Programme starten, etc."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "command": {
                    "type": "STRING",
                    "description": "Der auszuführende Shell-Befehl",
                },
                "working_directory": {
                    "type": "STRING",
                    "description": "Arbeitsverzeichnis (optional, Standard: Home-Verzeichnis)",
                },
                "timeout": {
                    "type": "INTEGER",
                    "description": f"Timeout in Sekunden (optional, Standard: {config.COMMAND_TIMEOUT})",
                },
            },
            "required": ["command"],
        }

    async def execute(
        self,
        command: str,
        working_directory: str = None,
        timeout: int = None,
        **kwargs,
    ) -> str:
        """Führt Shell-Befehl aus."""
        timeout = timeout or config.COMMAND_TIMEOUT
        cwd = working_directory or None

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                return f"⏰ Timeout nach {timeout}s. Befehl abgebrochen."

            result = ""
            if stdout:
                result += f"STDOUT:\n{stdout.decode('utf-8', errors='replace')}"
            if stderr:
                result += f"\nSTDERR:\n{stderr.decode('utf-8', errors='replace')}"
            if proc.returncode != 0:
                result += f"\nExit-Code: {proc.returncode}"

            return result.strip() or "(Keine Ausgabe)"

        except Exception as e:
            return f"Fehler: {str(e)}"
