"""Memory Tool – Persistenter Speicher für Fakten und Präferenzen."""

import json
import re
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.tools.base import BaseTool

# Memory-Datei
MEMORY_FILE = Path(__file__).parent.parent.parent / "data" / "memory.json"

# Thread-Lock fuer parallelen Zugriff (Sub-Agents)
_lock = threading.Lock()

# Token-Limits
TOKEN_LIMIT = 2000       # Warnung im System-Prompt
COMPRESS_THRESHOLD = 1500  # Kompression empfehlen


def _estimate_tokens(text: str) -> int:
    """Grobe Token-Schaetzung (~4 Zeichen pro Token fuer deutschen Text)."""
    return len(text) // 4


def _load_memory_dict() -> dict:
    """Laedt Memory aus JSON-Datei mit Backup-Recovery."""
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if MEMORY_FILE.exists():
        try:
            return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError) as e:
            print(f"[MEMORY] WARNUNG: memory.json korrupt ({e}), versuche Backup...", flush=True)
            bak = MEMORY_FILE.with_suffix(".json.bak")
            if bak.exists():
                try:
                    data = json.loads(bak.read_text(encoding="utf-8"))
                    print(f"[MEMORY] Backup geladen ({len(data)} Eintraege)", flush=True)
                    # Backup wiederherstellen
                    MEMORY_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                    return data
                except Exception:
                    pass
            print("[MEMORY] Kein nutzbares Backup gefunden, starte mit leerem Memory", flush=True)
            return {}
    return {}


def _save_memory_dict(memory: dict):
    """Speichert Memory mit Backup der vorherigen Version."""
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if MEMORY_FILE.exists():
        shutil.copy2(MEMORY_FILE, MEMORY_FILE.with_suffix(".json.bak"))
    MEMORY_FILE.write_text(json.dumps(memory, indent=2, ensure_ascii=False), encoding="utf-8")


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
            "Memory überlebt Neustarts und steht in allen zukünftigen Gesprächen zur Verfügung. "
            "Bei zu grossem Memory: action='compress' um alte wissen_-Eintraege zusammenzufassen."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Aktion: 'save' (Key-Value speichern), 'get' (einzelnen Key abrufen), 'list' (ALLE Eintraege auflisten – nutze dies um alles ueber den User zu erfahren), 'delete' (Key loeschen), 'search' (nach Begriff suchen), 'compress' (alte wissen_-Eintraege zusammenfassen).",
                    "enum": ["save", "get", "list", "delete", "search", "compress"]
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
        with _lock:
            return self._execute_inner(**kwargs)

    def _execute_inner(self, **kwargs) -> str:
        action = kwargs.get("action", "")
        key = kwargs.get("key", "")
        value = kwargs.get("value", "")
        query = kwargs.get("query", "")

        memory = _load_memory_dict()

        if action == "save":
            if not key or not value:
                return "❌ 'key' und 'value' sind für 'save' erforderlich."
            # Validierung
            if len(key) > 100:
                return "❌ Key zu lang (max 100 Zeichen)."
            if len(str(value)) > 5000:
                return "❌ Value zu lang (max 5000 Zeichen)."
            if not re.match(r'^[a-zA-Z0-9_.\-äöüÄÖÜß ]+$', str(key)):
                return "❌ Key enthält ungueltige Zeichen. Erlaubt: Buchstaben, Zahlen, _ . - Leerzeichen"
            memory[key] = {
                "value": str(value),
                "updated": datetime.now().isoformat(),
            }
            _save_memory_dict(memory)
            count = len(memory)
            tokens = _estimate_tokens(json.dumps(memory, ensure_ascii=False))
            hint = f" (Memory: {count} Eintraege, ~{tokens} Tokens)" if tokens > COMPRESS_THRESHOLD else ""
            return f"💾 Gespeichert: {key} = {value}{hint}"

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
            tokens = _estimate_tokens(json.dumps(memory, ensure_ascii=False))
            output = f"📋 Memory ({len(memory)} Einträge, ~{tokens} Tokens):\n"
            for k, v in sorted(memory.items()):
                output += f"  • {k}: {v['value']}\n"
            if tokens > COMPRESS_THRESHOLD:
                output += f"\n⚠️ Memory ist gross (~{tokens} Tokens). Nutze action='compress' zum Zusammenfassen."
            return output

        elif action == "delete":
            if not key:
                return "❌ 'key' ist für 'delete' erforderlich."
            if key in memory:
                del memory[key]
                _save_memory_dict(memory)
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

        elif action == "compress":
            wissen = {k: v for k, v in memory.items() if k.startswith("wissen_")}
            if len(wissen) < 5:
                return f"📊 Nur {len(wissen)} wissen_-Eintraege vorhanden – Kompression nicht noetig (min. 5)."
            tokens = _estimate_tokens(json.dumps(wissen, ensure_ascii=False))
            if tokens < COMPRESS_THRESHOLD:
                return f"📊 wissen_-Eintraege haben ~{tokens} Tokens – unter Schwellwert ({COMPRESS_THRESHOLD}), Kompression nicht noetig."

            entries_text = "\n".join(f"- {k}: {v['value']}" for k, v in sorted(wissen.items()))
            return (
                f"📊 {len(wissen)} wissen_-Eintraege mit ~{tokens} geschaetzten Tokens gefunden.\n\n"
                f"Bitte fasse folgende Eintraege zusammen und speichere sie als weniger, "
                f"konsolidierte wissen_-Eintraege via memory_manage(action='save'). "
                f"Loesche danach die alten Keys via memory_manage(action='delete').\n\n"
                f"Aktuelle Eintraege:\n{entries_text}"
            )

        return f"❌ Unbekannte Aktion: {action}. Erlaubt: save, get, list, delete, search, compress."


def load_memory_context() -> str:
    """Lädt alle Memory-Einträge als Kontext-String für den System-Prompt.

    Wird beim Start jeder Konversation automatisch injiziert.
    """
    memory = _load_memory_dict()
    if not memory:
        return ""

    # Wissens-Cache und normale Einträge trennen
    wissen = []
    fakten = []
    for key, entry in sorted(memory.items()):
        val = entry.get("value", "") if isinstance(entry, dict) else str(entry)
        if key.startswith("wissen_"):
            wissen.append(f"- {key[7:]}: {val}")
        else:
            fakten.append(f"- {key}: {val}")

    lines = []
    if wissen:
        lines.append("Gelerntes Wissen (direkt nutzen, NICHT erneut nachschlagen):")
        lines.extend(wissen)
    if fakten:
        if lines:
            lines.append("")
        lines.append("Gespeicherte Fakten:")
        lines.extend(fakten)

    context = "\n".join(lines)

    # Token-Check
    tokens = _estimate_tokens(context)
    if tokens > TOKEN_LIMIT:
        context += (
            f"\n\n⚠️ WARNUNG: Memory ist sehr gross (~{tokens} Tokens). "
            f"Nutze memory_manage(action='compress') um alte wissen_-Eintraege zusammenzufassen!"
        )

    return context
