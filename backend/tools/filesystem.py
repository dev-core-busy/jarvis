"""Dateisystem Tool – Dateien lesen, schreiben, auflisten."""

import os
from pathlib import Path

from backend.tools.base import BaseTool


class FileSystemTool(BaseTool):
    """Liest, schreibt und listet Dateien/Verzeichnisse auf."""

    @property
    def name(self) -> str:
        return "filesystem"

    @property
    def description(self) -> str:
        return (
            "Dateisystem-Operationen. Aktionen: "
            "'read' – Datei lesen (gibt Inhalt zurück). "
            "'write' – Datei schreiben (erstellt/überschreibt). "
            "'append' – Text an Datei anhängen. "
            "'list' – Verzeichnisinhalt auflisten. "
            "'exists' – Prüfen ob Datei/Verzeichnis existiert. "
            "'mkdir' – Verzeichnis erstellen."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "Aktion: read, write, append, list, exists, mkdir",
                },
                "path": {
                    "type": "STRING",
                    "description": "Pfad zur Datei oder zum Verzeichnis",
                },
                "content": {
                    "type": "STRING",
                    "description": "Inhalt zum Schreiben (für write/append)",
                },
            },
            "required": ["action", "path"],
        }

    async def execute(
        self,
        action: str,
        path: str,
        content: str = "",
        **kwargs,
    ) -> str:
        """Dateisystem-Operation ausführen."""
        p = Path(path).expanduser()

        try:
            if action == "read":
                if not p.exists():
                    return f"Datei nicht gefunden: {p}"
                if p.is_dir():
                    return f"{p} ist ein Verzeichnis, nicht eine Datei"
                text = p.read_text(encoding="utf-8", errors="replace")
                if len(text) > 10000:
                    return text[:10000] + f"\n\n... (gekürzt, {len(text)} Zeichen gesamt)"
                return text

            elif action == "write":
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
                return f"✅ Datei geschrieben: {p} ({len(content)} Zeichen)"

            elif action == "append":
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(p, "a", encoding="utf-8") as f:
                    f.write(content)
                return f"✅ An Datei angehängt: {p}"

            elif action == "list":
                if not p.exists():
                    return f"Verzeichnis nicht gefunden: {p}"
                if not p.is_dir():
                    return f"{p} ist kein Verzeichnis"

                entries = []
                for item in sorted(p.iterdir()):
                    prefix = "📁" if item.is_dir() else "📄"
                    size = ""
                    if item.is_file():
                        s = item.stat().st_size
                        if s < 1024:
                            size = f" ({s} B)"
                        elif s < 1024 * 1024:
                            size = f" ({s / 1024:.1f} KB)"
                        else:
                            size = f" ({s / (1024 * 1024):.1f} MB)"
                    entries.append(f"{prefix} {item.name}{size}")

                if not entries:
                    return f"(Verzeichnis ist leer: {p})"
                return "\n".join(entries)

            elif action == "exists":
                if p.exists():
                    kind = "Verzeichnis" if p.is_dir() else "Datei"
                    return f"✅ Existiert ({kind}): {p}"
                return f"❌ Existiert nicht: {p}"

            elif action == "mkdir":
                p.mkdir(parents=True, exist_ok=True)
                return f"✅ Verzeichnis erstellt: {p}"

            else:
                return f"Unbekannte Aktion: {action}"

        except PermissionError:
            return f"❌ Zugriff verweigert: {p}"
        except Exception as e:
            return f"Fehler: {str(e)}"
