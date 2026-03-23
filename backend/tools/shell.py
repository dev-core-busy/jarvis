"""Shell Tool – fuehrt Kommandozeilen-Befehle aus, mit optionalem Live-Streaming."""

import asyncio

from backend.tools.base import BaseTool
from backend.config import config


class ShellTool(BaseTool):
    """Fuehrt Shell-Befehle auf dem Linux-System aus."""

    # Streaming-Unterstuetzung: Agent kann Live-Output senden
    supports_streaming = True

    @property
    def name(self) -> str:
        return "shell_execute"

    @property
    def description(self) -> str:
        return (
            "Fuehrt einen Shell-Befehl (bash) auf dem Linux-System aus. "
            "Gibt stdout und stderr zurueck. Bei lang laufenden Befehlen "
            "wird die Ausgabe zeilenweise live gestreamt. "
            "Nutze dies fuer: Dateien auflisten, Pakete installieren, "
            "Systeminformationen abfragen, Programme starten, Code ausfuehren, etc."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "command": {
                    "type": "STRING",
                    "description": "Der auszufuehrende Shell-Befehl",
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

    @staticmethod
    def _code_to_command(code: str) -> str:
        """Wandelt Code in einen ausfuehrbaren Shell-Befehl um.
        Schreibt Python-Code in eine Temp-Datei um Quoting-Probleme zu vermeiden."""
        import tempfile, os

        # Python-Code aus 'python3 -c "..."' extrahieren
        stripped = code
        for prefix in ('python3 -c ', 'python -c '):
            if code.startswith(prefix):
                stripped = code[len(prefix):]
                # Aeussere Anfuehrungszeichen entfernen (""", ''', ", ')
                for q in ('"""', "'''", '"', "'"):
                    if stripped.startswith(q) and stripped.endswith(q):
                        stripped = stripped[len(q):-len(q)]
                        break
                break

        # Pruefen ob es ein Shell-Befehl ist (kein Python-Code)
        shell_indicators = ("ls ", "cat ", "cd ", "mkdir ", "rm ", "cp ", "mv ",
                            "chmod ", "grep ", "curl ", "wget ", "apt ", "pip ",
                            "git ", "npm ", "node ", "bash ", "sh ", "./", "/")
        if any(code.startswith(s) for s in shell_indicators):
            return code

        # Python-Code in Temp-Datei schreiben (vermeidet ALLE Quoting-Probleme)
        tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.py', prefix='jarvis_',
                                           dir='/tmp', delete=False)
        tmp.write(stripped)
        tmp.close()
        return f"python3 {tmp.name} ; rm -f {tmp.name}"

    async def execute(
        self,
        command: str = "",
        working_directory: str = None,
        timeout: int = None,
        _status_callback=None,
        code: str = "",
        **kwargs,
    ) -> str:
        """Fuehrt Shell-Befehl aus. Bei _status_callback wird stdout live gestreamt."""
        # Fallback: LLM schickt manchmal "code" statt "command"
        if not command and code:
            command = self._code_to_command(code.strip())
        elif command and code:
            if command.strip().endswith("-c"):
                # command="python3 -c" + code separat -> Temp-Datei
                command = self._code_to_command(code.strip())
            # Sonst: command hat Vorrang, code ignorieren

        if not command:
            return "Fehler: Kein Befehl angegeben (Parameter 'command' ist Pflicht)"

        timeout = timeout or config.COMMAND_TIMEOUT
        cwd = working_directory or None

        # Python-Buffering deaktivieren fuer Live-Streaming
        import os
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                env=env,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            # Live-Streaming: stdout zeilenweise lesen und senden
            print(f"[SHELL] callback={_status_callback is not None} stdout={proc.stdout is not None}", flush=True)
            if _status_callback and proc.stdout:
                stdout_lines = []
                stderr_data = b""

                async def _read_stderr():
                    nonlocal stderr_data
                    if proc.stderr:
                        stderr_data = await proc.stderr.read()

                stderr_task = asyncio.create_task(_read_stderr())

                try:
                    while True:
                        try:
                            line = await asyncio.wait_for(
                                proc.stdout.readline(), timeout=timeout
                            )
                        except asyncio.TimeoutError:
                            proc.kill()
                            return f"⏰ Timeout nach {timeout}s. Befehl abgebrochen."

                        if not line:
                            break

                        decoded = line.decode("utf-8", errors="replace").rstrip()
                        stdout_lines.append(decoded)
                        # Live an Frontend senden
                        try:
                            await _status_callback(f"💻 {decoded}")
                        except Exception as cb_err:
                            print(f"[SHELL] callback error: {cb_err}", flush=True)

                    await asyncio.wait_for(proc.wait(), timeout=5)
                    await stderr_task

                except asyncio.TimeoutError:
                    proc.kill()
                    return f"⏰ Timeout nach {timeout}s. Befehl abgebrochen."

                result = ""
                if stdout_lines:
                    result += f"STDOUT:\n" + "\n".join(stdout_lines)
                if stderr_data:
                    result += f"\nSTDERR:\n{stderr_data.decode('utf-8', errors='replace')}"
                if proc.returncode and proc.returncode != 0:
                    result += f"\nExit-Code: {proc.returncode}"

                return result.strip() or "(Keine Ausgabe)"

            else:
                # Klassischer Modus: alles auf einmal
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
