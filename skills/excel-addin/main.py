"""Excel-Assistent: Werkzeug fuer das Aufgabenfenster in Excel.

Der Skill liefert genau EIN Werkzeug – ``excel_vorschlag``. Es schreibt nichts;
es sammelt die vom Modell vorgeschlagenen Zellaenderungen ein, damit das
Aufgabenfenster sie dem Benutzer zur Bestaetigung vorlegen kann.

WARUM DAS WERKZEUG IM SKILL LIEGT UND NICHT IM KERN
----------------------------------------------------
Bis zum Umbau hing es in ``agent.py::_attach_extra_tools`` und war damit in
JEDEM Werkzeugkasten – auch auf Systemen, die gar kein Excel-Add-in benutzen.
Als Skill-Werkzeug verschwindet es mit dem Schalter: ist der Skill aus, gibt es
das Werkzeug nicht, und der Endpunkt ``/api/excel/ask`` sagt im Klartext, dass
der Assistent nicht aktiv ist. Das ist dasselbe Muster wie beim E-Mail-Skill.

Die eigentliche Logik (Pruefung der Adressen, Formel-Sperrliste, Sammelliste)
liegt in ``backend/excel_ask.py`` und ``backend/tools/excel_vorschlag.py`` –
NICHT hier. Grund: der Endpunkt braucht dieselben Funktionen, und ein Skill
kann keine Routen registrieren (gleiche Aufteilung wie bei ``sap_analyses.py``
und ``agent_roles.py``).
"""

from backend.tools.excel_vorschlag import ExcelVorschlagTool


def get_tools():
    return [ExcelVorschlagTool()]
