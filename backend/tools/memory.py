"""Memory Tool – Persistenter Speicher für Fakten und Präferenzen."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.tools.base import BaseTool

# Memory-Datei
MEMORY_FILE = Path(__file__).parent.parent.parent / "data" / "memory.json"


class MemoryTool(BaseTool):
    """Speichert und ruft persistente Informationen ab (Fakten, Präferenzen, Notizen)."""

    @property
    def name(self) -> str:
        return "memory_manage"

    @property
    def description(self) -> str:
        return (
            "Verwaltet den persistenten Speicher (Memory) von Jarvis. "
            "Nutze dieses Tool, um wichtige Informationen dauerhaft zu speichern, "
            "abzurufen oder zu löschen. Beispiele: Benutzerpräferenzen, Projektnamen, "
            "IP-Adressen, häufig benutzte Befehle, Notizen. "
            "Memory überlebt Neustarts und steht in allen zukünftigen Gesprächen zur Verfügung."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Aktion: 'save' (Key-Value speichern), 'get' (einzelnen Key abrufen), 'list' (ALLE Eintraege auflisten – nutze dies um alles ueber den User zu erfahren), 'delete' (Key loeschen), 'search' (nach Begriff suchen).",
                    "enum": ["save", "get", "list", "delete", "search"]
                },
                "key": {
                    "type": "string",
                    "description": "Schlüssel des Memory-Eintrags (z.B. 'user_name', 'server_ip'). Benötigt bei save, get, delete."
                },
                "value": {
                    "type": "string",
                    "description": "Wert zum Speichern. Nur bei action='save' benötigt."
                },
                "query": {
                    "type": "string",
                    "description": "Suchbegriff. Nur bei action='search' benötigt."
                }
            },
            "required": ["action"]
        }

    async def execute(self, **kwargs) -> str:
        action = kwargs.get("action", "")
        key = kwargs.get("key", "")
        value = kwargs.get("value", "")
        query = kwargs.get("query", "")

        memory = self._load()

        if action == "save":
            if not key or not value:
                return "❌ 'key' und 'value' sind für 'save' erforderlich."
            memory[key] = {
                "value": value,
                "updated": datetime.now().isoformat(),
            }
            self._save(memory)
            return f"💾 Gespeichert: {key} = {value}"

        elif action == "get":
            if not key:
                return "❌ 'key' ist für 'get' erforderlich."
            if key in memory:
                entry = memory[key]
                return f"📌 {key} = {entry['value']}  (Stand: {entry.get('updated', '?')})"
            return f"❓ Kein Eintrag für '{key}' gefunden."

        elif action in ("list", "load_all", "get_all"):
            if not memory:
                return "📭 Memory ist leer."
            output = f"📋 Memory ({len(memory)} Einträge):\n"
            for k, v in sorted(memory.items()):
                output += f"  • {k}: {v['value']}\n"
            return output

        elif action == "delete":
            if not key:
                return "❌ 'key' ist für 'delete' erforderlich."
            if key in memory:
                del memory[key]
                self._save(memory)
                return f"🗑️ Gelöscht: {key}"
            return f"❓ Kein Eintrag '{key}' zum Löschen gefunden."

        elif action == "search":
            if not query:
                return "❌ 'query' ist für 'search' erforderlich."
            q = query.lower()
            results = []
            for k, v in memory.items():
                if q in k.lower() or q in v["value"].lower():
                    results.append(f"  • {k}: {v['value']}")
            if results:
                return f"🔍 {len(results)} Treffer für '{query}':\n" + "\n".join(results)
            return f"🔍 Keine Treffer für '{query}'."

        return f"❌ Unbekannte Aktion: {action}. Erlaubt: save, get, list, delete, search."

    def _load(self) -> dict:
        """Lädt Memory aus JSON-Datei."""
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        if MEMORY_FILE.exists():
            try:
                return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save(self, memory: dict):
        """Speichert Memory in JSON-Datei."""
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        MEMORY_FILE.write_text(json.dumps(memory, indent=2, ensure_ascii=False), encoding="utf-8")


def load_memory_context() -> str:
    """Lädt alle Memory-Einträge als Kontext-String für den System-Prompt.
    
    Wird beim Start jeder Konversation automatisch injiziert.
    """
    memory_file = MEMORY_FILE
    if not memory_file.exists():
        return ""

    try:
        memory = json.loads(memory_file.read_text(encoding="utf-8"))
    except Exception:
        return ""

    if not memory:
        return ""

    lines = ["Bekannte Fakten aus dem Memory:"]
    for key, entry in sorted(memory.items()):
        lines.append(f"- {key}: {entry['value']}")

    return "\n".join(lines)
