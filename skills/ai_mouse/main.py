"""AI-Mouse-Skill (Bildschirmausschnitt vom Arbeitsplatz an das Hausmodell).

Dieser Skill stellt bewusst KEINE Agent-Werkzeuge bereit. Er ist ein reiner
Bereichs-Schalter – dasselbe Muster wie ``userchat`` und ``support_assistant``:

- schaltet die Oberflaeche unter ``/ai-mouse`` frei (geprueft in main.py),
- gattert ``/api/ai-mouse/*``,
- haelt die Freigabe der Werkzeug-Bereiche in der Skill-Config (``bereiche``).

Die Auswertung selbst liegt in ``backend/ai_mouse.py``, die Windows-Anwendung
unter ``ai-mouse/`` (C#). Warum das Modul im Backend liegt und nicht hier: der
Skill ist abschaltbar und deinstallierbar, die Endpunkte in ``main.py`` sind es
nicht – ein Import aus ``skills.ai_mouse`` waere dort nach einem Purge ein
500er (dieselbe Aufteilung wie bei ``jira``/``jira_assist``).

WARUM KEIN WERKZEUG: Ein Werkzeug ``ai_mouse_analyze`` fuer den Agenten waere
sinnlos – der Agent laeuft auf dem Server und hat keinen Bildschirm des
Arbeitsplatzes. Der Bildausschnitt kann nur vom Client kommen.
"""

from backend.tools.base import BaseTool  # noqa: F401  (Konvention: Skill-Modul)


def get_tools():
    return []
