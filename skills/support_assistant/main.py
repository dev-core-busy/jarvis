"""Support-Assistent-Skill.

Dieser Skill stellt keine Agent-Tools bereit, sondern:
- haelt das vorangestellte LLM-Prompt in der Skill-Config (``system_prompt``),
- schaltet die Support-Oberflaeche unter ``/support`` frei (geprueft in main.py),
- liefert die Such-/Ranking-Logik fuer ``/api/support/query``.

Konfiguration ueber den eigenen Reiter in den Einstellungen.
"""

from backend.tools.base import BaseTool  # noqa: F401  (Konvention: Skill-Modul)


def get_tools():
    return []
