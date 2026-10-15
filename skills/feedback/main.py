"""Feedback-Skill (Formulare nach Excel-Vorbild).

Dieser Skill stellt bewusst KEINE Agent-Werkzeuge bereit. Er ist ein reiner
Bereichs-Schalter – dasselbe Muster wie ``ai_mouse``, ``userchat`` und
``support_assistant``:

- schaltet die Oberflaeche unter ``/feedback`` frei (geprueft in main.py),
- gattert ``/api/feedback/*``.

Die Datenhaltung liegt in ``backend/feedback.py``. Warum dort und nicht hier:
der Skill ist abschaltbar und deinstallierbar, die Endpunkte in ``main.py``
sind es nicht – ein Import aus ``skills.feedback`` waere dort nach einem Purge
ein 500er (dieselbe Aufteilung wie bei ``ai_mouse`` und ``jira``/``jira_assist``).

WARUM KEIN WERKZEUG: ein ``feedback_read`` fuer den Agenten waere eine zweite
Rechtefrage auf denselben Bestand – Abgaben sind personenbezogen (jede traegt
den Benutzernamen), und ein Modell, das sie im Chat vorliest, umginge die
Trennung „Administrator sieht alle, Benutzer nur seine eigenen“. Wer eine
Auswertung durch das Modell will, exportiert die CSV und haengt sie an.
"""

from backend.tools.base import BaseTool  # noqa: F401  (Konvention: Skill-Modul)


def get_tools():
    return []
