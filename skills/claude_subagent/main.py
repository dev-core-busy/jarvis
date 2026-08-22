"""Claude-Subagent-Skill – Codearbeiten, die Claude Code an Jarvis abgibt.

Dieser Skill stellt bewusst KEINE Agent-Werkzeuge bereit. Er ist ein reiner
Bereichs-Schalter – dasselbe Muster wie ``userchat`` und ``support_assistant``:

- schaltet die Oberflaeche unter ``/claude`` frei (geprueft in main.py),
- gattert ``/api/claude/*``,
- haelt die Grenzwerte des Bereichs in der Skill-Config.

Die Logik liegt in ``backend/claude_subagent.py`` (Schluessel, Auftraege,
Arbeitsbereich, Riegel) – Skills koennen keine Routen registrieren, deshalb
dieselbe Aufteilung wie bei ``sap_analyses.py`` und ``agent_roles.py``.

WARUM KEINE WERKZEUGE: Ein Werkzeug wie ``delegiere_code`` waere ein Weg, mit
dem ein MODELL Agentenlaeufe unter der Kennung des angemeldeten Benutzers
starten koennte – und damit ein Kandidat fuer jede Prompt-Injektion, die im
Chat, in einer E-Mail oder in einer abgelegten Datei steckt. Der Bereich wird
ausschliesslich von aussen bedient (Claude Code mit dem Delegations-Schluessel
des Benutzers) oder vom Menschen im Browser.

DIE HARTEN ZUSAGEN DES BEREICHS, damit sie beim Umbau nicht verlorengehen:
- Der Lauf ist IMMER unprivilegiert (``privileged`` hart ``False``, kein Feld).
- Er arbeitet in einem WEGWERF-KLON unter /tmp – nie in /opt/jarvis.
- Der Werkzeug-Zuschnitt ist eine Whitelist auf ``_role_tools`` (harte Schranke
  im Dispatch, nicht nur in der Werkzeugliste, die das Modell sieht).
- Das Ergebnis (Patch, Dateiliste, Riegel) rechnet das Backend, nicht das
  Modell. In der Machbarkeitsprobe vom 2026-08-21 war die vom Modell
  ABGELEITETE Zahl in drei von drei Laeufen falsch.
"""

from backend.tools.base import BaseTool  # noqa: F401  (Konvention: Skill-Modul)


def get_tools():
    return []
