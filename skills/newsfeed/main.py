"""Newsfeed-Skill (Kurzmeldungen im Portal).

Dieser Skill stellt bewusst KEINE Agent-Werkzeuge bereit. Er ist ein reiner
Bereichs-Schalter – dasselbe Muster wie ``feedback`` und ``userchat``:

- blendet die Newsfeed-Kachel unter ``/portal`` ein (permissions.newsfeed),
- gattert ``/api/newsfeed`` (Lesen) – die Pflege unter
  ``/api/newsfeed/admin/*`` bleibt auch bei ausgeschaltetem Skill bedienbar,
  damit ein Administrator Meldungen VOR dem Einschalten anlegen kann.

Die Datenhaltung liegt in ``backend/newsfeed.py``. Warum dort und nicht hier:
der Skill ist abschaltbar und deinstallierbar, die Endpunkte in ``main.py``
sind es nicht – ein Import aus ``skills.newsfeed`` waere dort nach einem Purge
ein 500er (dieselbe Aufteilung wie bei ``feedback``).
"""

from backend.tools.base import BaseTool  # noqa: F401  (Konvention: Skill-Modul)


def get_tools():
    return []
