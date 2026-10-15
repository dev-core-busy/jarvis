"""Agent Autonomy Kit – Proaktives Aufgaben-Management via QUEUE.md und tägliche Logs.

Protokoll (aus templates/QUEUE.md + templates/HEARTBEAT.md):
  data/tasks/QUEUE.md       ← Aufgaben-Warteschlange
  data/memory/YYYY-MM-DD.md ← Tägliche Aktivitätslogs

Queue-Sektionen:
  🔴 Ready      – Aufgaben die sofort begonnen werden können
  🟡 In Progress – Laufende Aufgaben
  🔵 Blocked    – Blockierte Aufgaben (mit Begründung)
  ✅ Done Today  – Heute abgeschlossene Aufgaben
  💡 Ideas       – Ideen (noch keine Aufgaben)
"""

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.tools.base import BaseTool

_PROJECT_ROOT = Path(__file__).parent.parent.parent

QUEUE_TEMPLATE = """\
# Task Queue

*Last updated: {timestamp}*

---

## 🔴 Ready (can be picked up)

### High Priority
{high}
### Medium Priority
{medium}
### Low Priority
{low}

---

## 🟡 In Progress

{in_progress}

---

## 🔵 Blocked

{blocked}

---

## ✅ Done Today

{done}

---

## 💡 Ideas (not yet tasks)

{ideas}

---

*Add tasks as you discover them. Pick from Ready when you have capacity.*
"""

HEARTBEAT_TEMPLATE = """\
# Aktivitätslog – {date}

## Erledigte Aufgaben
{tasks_done}

## Neue Aufgaben entdeckt
{new_tasks}

## Erkenntnisse / Notizen
{notes}

---
*Erstellt: {timestamp}*
"""


def _queue_file() -> Path:
    try:
        from backend.config import config
        rel = config.get_skill_states().get("agent_autonomy_kit", {}).get("config", {}).get(
            "queue_file", "data/tasks/QUEUE.md"
        )
        return _PROJECT_ROOT / rel
    except Exception:
        return _PROJECT_ROOT / "data" / "tasks" / "QUEUE.md"


def _memory_dir() -> Path:
    try:
        from backend.config import config
        rel = config.get_skill_states().get("agent_autonomy_kit", {}).get("config", {}).get(
            "memory_dir", "data/memory"
        )
        return _PROJECT_ROOT / rel
    except Exception:
        return _PROJECT_ROOT / "data" / "memory"


# ─── Queue-Parser ─────────────────────────────────────────────────────────────

_SECTION_MARKERS = {
    "high":        r"### High Priority",
    "medium":      r"### Medium Priority",
    "low":         r"### Low Priority",
    "in_progress": r"## 🟡 In Progress",
    "blocked":     r"## 🔵 Blocked",
    "done":        r"## ✅ Done Today",
    "ideas":       r"## 💡 Ideas",
}

_SECTION_ORDER = ["high", "medium", "low", "in_progress", "blocked", "done", "ideas"]


def _parse_queue(text: str) -> dict[str, list[str]]:
    """Parst QUEUE.md und gibt Sektionen als Listen zurück."""
    sections: dict[str, list[str]] = {k: [] for k in _SECTION_ORDER}
    current = None

    for line in text.splitlines():
        stripped = line.strip()
        # Sektion erkennen
        for key, marker in _SECTION_MARKERS.items():
            if stripped.startswith(marker.lstrip("#").lstrip(" ") if not marker.startswith("#") else marker):
                current = key
                break
        else:
            if current and stripped.startswith("- "):
                sections[current].append(stripped)
    return sections


def _render_queue(sections: dict[str, list[str]], timestamp: str) -> str:
    """Rendert QUEUE.md aus Sektionen."""
    def join(lst): return "\n".join(lst) if lst else "*(keine)*"
    return QUEUE_TEMPLATE.format(
        timestamp=timestamp,
        high=join(sections.get("high", [])),
        medium=join(sections.get("medium", [])),
        low=join(sections.get("low", [])),
        in_progress=join(sections.get("in_progress", [])),
        blocked=join(sections.get("blocked", [])),
        done=join(sections.get("done", [])),
        ideas=join(sections.get("ideas", [])),
    )


def _read_queue() -> tuple[str, dict[str, list[str]]]:
    """Liest QUEUE.md; erstellt Default wenn nicht vorhanden."""
    qf = _queue_file()
    if qf.exists():
        text = qf.read_text(encoding="utf-8", errors="replace")
    else:
        # Default-Queue erstellen
        now = datetime.now(timezone.utc).isoformat(timespec="minutes")
        text = _render_queue({k: [] for k in _SECTION_ORDER}, now)
        qf.parent.mkdir(parents=True, exist_ok=True)
        qf.write_text(text, encoding="utf-8")
    return text, _parse_queue(text)


def _write_queue(sections: dict[str, list[str]]) -> None:
    qf = _queue_file()
    qf.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec="minutes")
    qf.write_text(_render_queue(sections, now), encoding="utf-8")


# ─── Tools ────────────────────────────────────────────────────────────────────

class QueueAddTool(BaseTool):
    """Fügt eine neue Aufgabe zur QUEUE.md hinzu."""

    @property
    def name(self) -> str:
        return "queue_add"

    @property
    def description(self) -> str:
        return (
            "Fügt eine neue Aufgabe zur Task-Queue hinzu. "
            "Priorität: high|medium|low. "
            "Sektion kann auch 'ideas' oder 'blocked' sein."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "task":     {"type": "string", "description": "Aufgabenbeschreibung"},
                "priority": {"type": "string", "description": "high|medium|low (Standard: medium)", "enum": ["high", "medium", "low"]},
                "section":  {"type": "string", "description": "ready_high|ready_medium|ready_low|ideas|blocked (Standard: abhängig von priority)"},
                "agent":    {"type": "string", "description": "Agent-Kürzel für In-Progress (optional)"},
                "blocker":  {"type": "string", "description": "Was blockiert die Aufgabe (nur für section=blocked)"},
            },
            "required": ["task"],
        }

    async def execute(self, **kwargs) -> str:
        task      = kwargs.get("task", "").strip()
        priority  = kwargs.get("priority", "medium").lower()
        section   = kwargs.get("section", "").lower()
        agent     = kwargs.get("agent", "")
        blocker   = kwargs.get("blocker", "")

        if not task:
            return "❌ Aufgabe darf nicht leer sein."

        # Sektion bestimmen
        if section in ("ideas",):
            target = "ideas"
            entry  = f"- {task}"
        elif section in ("blocked",):
            target = "blocked"
            entry  = f"- [ ] {task}" + (f" (needs: {blocker})" if blocker else "")
        elif section in ("in_progress",):
            target = "in_progress"
            entry  = f"- [ ] @{agent}: {task}" if agent else f"- [ ] {task}"
        else:
            # Ready-Sektion nach Priorität
            pmap = {"high": "high", "medium": "medium", "low": "low"}
            target = pmap.get(priority, "medium")
            entry  = f"- [ ] {task}"

        _, sections = _read_queue()
        sections[target].append(entry)
        _write_queue(sections)

        section_labels = {
            "high": "🔴 Ready / High",
            "medium": "🔴 Ready / Medium",
            "low": "🔴 Ready / Low",
            "in_progress": "🟡 In Progress",
            "blocked": "🔵 Blocked",
            "done": "✅ Done Today",
            "ideas": "💡 Ideas",
        }
        return f"✅ Aufgabe hinzugefügt zu [{section_labels.get(target, target)}]:\n  {entry}"


class QueueListTool(BaseTool):
    """Zeigt die aktuelle Task-Queue."""

    @property
    def name(self) -> str:
        return "queue_list"

    @property
    def description(self) -> str:
        return (
            "Zeigt die aktuelle Task-Queue (QUEUE.md) mit allen Sektionen. "
            "Optional: nur eine bestimmte Sektion anzeigen."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": "Nur diese Sektion anzeigen: ready|in_progress|blocked|done|ideas|all (Standard: all)",
                    "enum": ["all", "ready", "high", "medium", "low", "in_progress", "blocked", "done", "ideas"],
                },
            },
            "required": [],
        }

    async def execute(self, **kwargs) -> str:
        section_filter = kwargs.get("section", "all").lower()
        _, sections = _read_queue()

        lines = ["📋 **Task Queue**\n"]

        def show(key: str, label: str):
            items = sections.get(key, [])
            count = len(items)
            lines.append(f"{label} ({count})")
            if items:
                lines.extend(f"  {item}" for item in items)
            else:
                lines.append("  *(keine)*")
            lines.append("")

        if section_filter in ("all", "ready"):
            show("high",        "🔴 Ready / High Priority")
            show("medium",      "🔴 Ready / Medium Priority")
            show("low",         "🔴 Ready / Low Priority")
        elif section_filter == "high":
            show("high",        "🔴 Ready / High Priority")
        elif section_filter == "medium":
            show("medium",      "🔴 Ready / Medium Priority")
        elif section_filter == "low":
            show("low",         "🔴 Ready / Low Priority")

        if section_filter in ("all", "in_progress"):
            show("in_progress", "🟡 In Progress")
        if section_filter in ("all", "blocked"):
            show("blocked",     "🔵 Blocked")
        if section_filter in ("all", "done"):
            show("done",        "✅ Done Today")
        if section_filter in ("all", "ideas"):
            show("ideas",       "💡 Ideas")

        total_ready = (len(sections.get("high", [])) +
                       len(sections.get("medium", [])) +
                       len(sections.get("low", [])))
        lines.append(f"📊 Gesamt: {total_ready} bereit, "
                     f"{len(sections.get('in_progress', []))} laufend, "
                     f"{len(sections.get('blocked', []))} blockiert")
        return "\n".join(lines)


class QueueNextTool(BaseTool):
    """Holt die nächste höchstpriorisierte Aufgabe und verschiebt sie nach 'In Progress'."""

    @property
    def name(self) -> str:
        return "queue_next"

    @property
    def description(self) -> str:
        return (
            "Holt die nächste bereite Aufgabe (höchste Priorität zuerst) aus der Queue "
            "und verschiebt sie in 'In Progress'. Gibt die Aufgabe zurück, damit der Agent sie bearbeiten kann."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "agent": {"type": "string", "description": "Agent-Kürzel, das die Aufgabe übernimmt (optional)"},
            },
            "required": [],
        }

    async def execute(self, **kwargs) -> str:
        agent = kwargs.get("agent", "")
        _, sections = _read_queue()

        # Höchste Priorität zuerst
        task = None
        source = None
        for prio in ("high", "medium", "low"):
            lst = sections.get(prio, [])
            if lst:
                task = lst.pop(0)
                source = prio
                break

        if not task:
            return "📭 Keine bereiten Aufgaben in der Queue. Alle Sektionen sind leer."

        # Checkbox von Ready → In Progress
        task_text = re.sub(r"^- \[.\] ?", "", task).strip()
        in_progress_entry = f"- [ ] @{agent}: {task_text}" if agent else f"- [ ] {task_text}"
        sections["in_progress"].append(in_progress_entry)

        _write_queue(sections)

        prio_labels = {"high": "High", "medium": "Medium", "low": "Low"}
        return (
            f"▶️ Nächste Aufgabe [{prio_labels.get(source, source)} Priority]:\n"
            f"  **{task_text}**\n\n"
            f"→ Status: 🟡 In Progress\n"
            f"→ Wenn fertig: `queue_complete` mit dieser Aufgabe aufrufen."
        )


class QueueCompleteTool(BaseTool):
    """Markiert eine In-Progress-Aufgabe als abgeschlossen."""

    @property
    def name(self) -> str:
        return "queue_complete"

    @property
    def description(self) -> str:
        return (
            "Markiert eine laufende Aufgabe als abgeschlossen. "
            "Verschiebt sie von 'In Progress' nach 'Done Today' und setzt die Checkbox auf [x]."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "task":   {"type": "string", "description": "Aufgabenbeschreibung (oder Teiltext) der abzuschließenden Aufgabe"},
                "agent":  {"type": "string", "description": "Agent-Kürzel (optional, für Done-Eintrag)"},
                "result": {"type": "string", "description": "Kurze Zusammenfassung des Ergebnisses (optional)"},
            },
            "required": ["task"],
        }

    async def execute(self, **kwargs) -> str:
        task_search = kwargs.get("task", "").strip().lower()
        agent       = kwargs.get("agent", "")
        result      = kwargs.get("result", "")

        if not task_search:
            return "❌ Aufgabe darf nicht leer sein."

        _, sections = _read_queue()

        # Aufgabe in In-Progress suchen (partial match)
        found_idx = None
        found_item = None
        for i, item in enumerate(sections.get("in_progress", [])):
            if task_search in item.lower():
                found_idx = i
                found_item = item
                break

        if found_idx is None:
            # Fallback: auch in Ready suchen
            for prio in ("high", "medium", "low"):
                for i, item in enumerate(sections.get(prio, [])):
                    if task_search in item.lower():
                        found_idx = i
                        found_item = item
                        sections[prio].pop(i)
                        break
                if found_idx is not None:
                    break
            if found_idx is None:
                return f"❌ Aufgabe nicht gefunden: '{task_search}'\nVerwende `queue_list` um die genaue Bezeichnung zu sehen."
        else:
            sections["in_progress"].pop(found_idx)

        # Task-Text extrahieren
        task_text = re.sub(r"^- \[.\] ?(@\w+: )?", "", found_item).strip()
        result_suffix = f" → {result}" if result else ""
        agent_prefix  = f"@{agent}: " if agent else ""
        done_entry    = f"- [x] {agent_prefix}{task_text}{result_suffix}"

        sections["done"].append(done_entry)
        _write_queue(sections)

        return (
            f"✅ Aufgabe abgeschlossen:\n"
            f"  {done_entry}\n\n"
            f"→ Verschoben nach: ✅ Done Today"
        )


class HeartbeatLogTool(BaseTool):
    """Schreibt einen täglichen Aktivitätslog und aktualisiert die Queue."""

    @property
    def name(self) -> str:
        return "heartbeat_log"

    @property
    def description(self) -> str:
        return (
            "Schreibt einen täglichen Aktivitätslog in data/memory/YYYY-MM-DD.md. "
            "Dokumentiert erledigte Aufgaben, neue Erkenntnisse und nächste Schritte. "
            "Soll am Ende jeder Arbeitssession aufgerufen werden."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "tasks_done": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Liste der heute erledigten Aufgaben",
                },
                "new_tasks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Neu entdeckte Aufgaben (werden auch der Queue hinzugefügt)",
                },
                "notes": {
                    "type": "string",
                    "description": "Erkenntnisse, Probleme, Notizen",
                },
                "date": {
                    "type": "string",
                    "description": "Datum (YYYY-MM-DD), Standard: heute",
                },
            },
            "required": ["tasks_done"],
        }

    async def execute(self, **kwargs) -> str:
        tasks_done = kwargs.get("tasks_done", [])
        new_tasks  = kwargs.get("new_tasks", [])
        notes      = kwargs.get("notes", "")
        date_str   = kwargs.get("date", "")

        now = datetime.now(timezone.utc)
        if not date_str:
            date_str = now.strftime("%Y-%m-%d")

        timestamp = now.isoformat(timespec="minutes")

        # Log-Datei schreiben
        mem_dir = _memory_dir()
        mem_dir.mkdir(parents=True, exist_ok=True)
        log_file = mem_dir / f"{date_str}.md"

        # Existierenden Log anhängen oder neu erstellen
        tasks_md    = "\n".join(f"- {t}" for t in tasks_done) if tasks_done else "*(keine)*"
        new_tasks_md = "\n".join(f"- {t}" for t in new_tasks) if new_tasks else "*(keine)*"

        if log_file.exists():
            existing = log_file.read_text(encoding="utf-8")
            append_block = (
                f"\n---\n\n## Update – {timestamp}\n\n"
                f"### Erledigt\n{tasks_md}\n\n"
                f"### Neue Aufgaben\n{new_tasks_md}\n\n"
            )
            if notes:
                append_block += f"### Notizen\n{notes}\n"
            log_file.write_text(existing + append_block, encoding="utf-8")
            action = "aktualisiert"
        else:
            content = HEARTBEAT_TEMPLATE.format(
                date=date_str,
                tasks_done=tasks_md,
                new_tasks=new_tasks_md,
                notes=notes or "*(keine)*",
                timestamp=timestamp,
            )
            log_file.write_text(content, encoding="utf-8")
            action = "erstellt"

        # Neue Aufgaben der Queue hinzufügen
        added_to_queue = []
        if new_tasks:
            _, sections = _read_queue()
            for t in new_tasks:
                entry = f"- [ ] {t}"
                sections["medium"].append(entry)
                added_to_queue.append(t)
            _write_queue(sections)

        result_lines = [
            f"📓 Aktivitätslog {action}: `data/memory/{date_str}.md`",
            f"  • {len(tasks_done)} Aufgabe(n) dokumentiert",
        ]
        if added_to_queue:
            result_lines.append(f"  • {len(added_to_queue)} neue Aufgabe(n) zur Queue hinzugefügt (Medium Priority)")
        result_lines.append(f"\n→ Log-Datei: {log_file}")

        return "\n".join(result_lines)


def get_tools():
    return [
        QueueAddTool(),
        QueueListTool(),
        QueueNextTool(),
        QueueCompleteTool(),
        HeartbeatLogTool(),
    ]
