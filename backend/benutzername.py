"""Normierung eines Benutzernamens – EINE Stelle fuer alle Vergleiche.

Bis 2026-11-10 stand dieselbe Zeile dreimal im Repo (main._norm_login,
tools.geraete_verbindungen.norm_benutzer, agent._lauf_limit_schluessel).
Aendert sich die Regel an einer Stelle, laufen Geraete-Zuordnung,
Lauf-Deckel und Anmeldung auseinander: ein Benutzer "DOM\\name" erreicht
seinen Client nicht mehr oder zaehlt unter zwei Schluesseln. Das Modul
importiert NICHTS aus dem Backend, damit es von ueberall ladbar ist
(agent.py und die Werkzeuge duerfen main nur lazy importieren).
"""


def norm_login(name) -> str:
    """Blosser sAMAccountName, klein: ohne Domaenen-Praefix (``DOMAIN\\user``),
    ohne UPN-Suffix (``user@domain``), ohne Leerraum."""
    return (name or "").split("@")[0].split("\\")[-1].strip().lower()
