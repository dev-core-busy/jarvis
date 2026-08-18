"""Short Tracks – Skill-Huelle.

DIESER SKILL BRINGT ABSICHTLICH KEINE WERKZEUGE MIT. Er ist der Ein/Aus-Schalter
und der Ort der Administrator-Einstellungen (Grenzen, Werkzeug-Freigabe) fuer den
Bereich ``/tracks``. Die Arbeit machen die Werkzeuge, die es schon gibt:
``office_read``/``filesystem`` zum Lesen, ``office_create_*``/``create_chart``
fuer das Ergebnis, optional ``knowledge_search``, die lesenden Fachsystem-
Werkzeuge und ``shell_execute``.

WARUM ein Skill und nicht einfach eine Einstellung: der Bereich soll abschaltbar
sein, ohne Code anzufassen, und er soll wie SAP und E-Mail einen eigenen
Einstellungs-Reiter bekommen (den bekommt ein Skill mit ``config_schema``
automatisch). Die Kehrseite: als Skill kostet die Funktion einen Skill-Slot –
FREE/BASIC erlauben fuenf aktive Skills.

Die Registry der Ablagen liegt im Backend (``backend/short_tracks.py``) und nicht
hier: Skills koennen keine HTTP-Routen registrieren, und die Ablagen sollen auch
bei ausgeschaltetem Skill pflegbar bleiben – dasselbe Muster wie
``agent_roles.py`` beim Orchestrator-Skill und ``sap_analyses.py`` beim
SAP-Skill.
"""


def get_tools():
    """Keine Werkzeuge – siehe Modul-Docstring.

    Die Funktion muss trotzdem existieren: der SkillManager ruft sie bei jedem
    Laden. Eine leere Liste ist das ausdrueckliche Ergebnis, kein Versehen.
    """
    return []
