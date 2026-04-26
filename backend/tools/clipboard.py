"""Clipboard Tools – Lesen und Schreiben der Linux-Zwischenablage (xclip)."""

import asyncio
from backend.tools.base import BaseTool


class ReadClipboardTool(BaseTool):
    @property
    def name(self) -> str:
        return "read_clipboard"

    @property
    def description(self) -> str:
        return (
            "Liest den aktuellen Inhalt der Linux-Zwischenablage (Clipboard). "
            "Gibt den Text zurück, der momentan im Clipboard gespeichert ist."
        )

    def parameters_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs) -> str:
        try:
            proc = await asyncio.create_subprocess_exec(
                "xclip", "-selection", "clipboard", "-o",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
            if proc.returncode != 0:
                return f"Fehler: xclip nicht verfügbar oder Clipboard leer. ({stderr.decode().strip()})"
            return stdout.decode("utf-8", errors="replace") or "(Clipboard ist leer)"
        except FileNotFoundError:
            return "Fehler: xclip ist nicht installiert. Bitte 'apt install xclip' ausführen."
        except asyncio.TimeoutError:
            return "Fehler: Timeout beim Lesen des Clipboards."
        except Exception as e:
            return f"Fehler: {e}"


class WriteClipboardTool(BaseTool):
    @property
    def name(self) -> str:
        return "write_clipboard"

    @property
    def description(self) -> str:
        return (
            "Schreibt Text in die Linux-Zwischenablage (Clipboard). "
            "Der Text kann danach mit Strg+V eingefügt werden."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Der Text, der in die Zwischenablage geschrieben werden soll.",
                }
            },
            "required": ["text"],
        }

    async def execute(self, text: str = "", **kwargs) -> str:
        try:
            proc = await asyncio.create_subprocess_exec(
                "xclip", "-selection", "clipboard", "-i",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(
                proc.communicate(input=text.encode("utf-8")), timeout=5
            )
            if proc.returncode != 0:
                return f"Fehler: xclip nicht verfügbar. ({stderr.decode().strip()})"
            preview = text[:80] + ("…" if len(text) > 80 else "")
            return f"✅ Clipboard gesetzt: \"{preview}\""
        except FileNotFoundError:
            return "Fehler: xclip ist nicht installiert. Bitte 'apt install xclip' ausführen."
        except asyncio.TimeoutError:
            return "Fehler: Timeout beim Schreiben ins Clipboard."
        except Exception as e:
            return f"Fehler: {e}"
