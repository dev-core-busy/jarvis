"""Benutzer-Chat-Skill (Direktnachrichten zwischen angemeldeten Benutzern).

Dieser Skill stellt bewusst KEINE Agent-Werkzeuge bereit. Er ist ein reiner
Bereichs-Schalter – dasselbe Muster wie ``support_assistant``:

- schaltet die Oberflaeche unter ``/userchat`` frei (geprueft in main.py),
- gattert ``/api/userchat/*``, ``/api/users/online`` und den WebSocket ``/ws/users``,
- haelt die zwei Grenzwerte des Bereichs in der Skill-Config
  (``history_max``, ``attachment_max_mb``).

Die Gespraechslogik selbst liegt weiter in ``backend/main.py`` (WebSocket,
Verlauf, Praesenz) – sie haengt an Prozess-Zustand (offene Verbindungen), den
ein nachladbares Skill-Modul nicht halten kann.

WARUM KEINE WERKZEUGE: Ein Werkzeug wie ``userchat_send`` waere ein Versandweg
im Namen des angemeldeten Benutzers, den ein Modell – und damit auch ein per
Prompt-Injektion eingeschleuster Satz – auswaehlen koennte. Der Bereich bleibt
deshalb ausschliesslich von Menschen bedienbar.
"""

from backend.tools.base import BaseTool  # noqa: F401  (Konvention: Skill-Modul)


def get_tools():
    return []
