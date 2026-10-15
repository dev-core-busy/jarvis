"""Pruefung der Python-Module, die der Agent per ``shell_execute`` braucht.

WARUM ES DIESES MODUL GIBT: Backend und Skills laufen im venv, ``shell_execute``
startet dagegen ``/usr/bin/python3`` (bei Domain-Benutzern zusaetzlich als
Sandbox-OS-Benutzer). Das sind ZWEI Python-Welten, und der Skill-Lifecycle
installiert mit ``sys.executable``, also ausschliesslich in die eine. Was in der
anderen fehlt, kann weder der Agent (kein Internet, keine Rechte) noch das
Backend (pip als root) nachholen.

Auf ECHT hat genau das am 2026-08-18 eine Excel-Anfrage in einer CSV-Notloesung
enden lassen, waehrend dieselbe Anfrage auf DEV gelang - dort lagen die Module
zufaellig. Hergestellt wird der Zustand von ``deploy/sandbox_python.sh``
(Automatik in ``start_jarvis_root.sh``, Schritt 6c). Dieses Modul PRUEFT nur und
macht das Ergebnis sichtbar: eine Automatik, die still fehlschlaegt, ist keine.

Die Pruefung ist bewusst billig (ein Unterprozess) und laeuft einmal beim Start.
"""
import subprocess

# Importname -> was ohne das Modul fehlt. Muss zur Liste in
# deploy/sandbox_python.sh passen; ein Test haelt das fest, damit die beiden
# Stellen nicht auseinanderlaufen.
MODULE = {
    "openpyxl":   "Excel lesen/schreiben per Shell",
    "pandas":     "Tabellen-Auswertung",
    "pdfplumber": "PDF mit Koordinaten (Formulare, Spalten)",
    "pypdf":      "PDF zusammenfuegen/teilen",
    "docx":       "Word per Shell",
    "pptx":       "PowerPoint per Shell",
    "xlsxwriter": "Excel schreiben (Alternative)",
    "matplotlib": "Diagramme als PNG",
    "PIL":        "Bildbearbeitung",
}

# Der Interpreter, den shell.py per "python3 <datei>" startet - NICHT sys.executable.
INTERPRETER = "/usr/bin/python3"

_TIMEOUT = 20


def fehlende(interpreter: str = INTERPRETER) -> list:
    """Liefert die Importnamen der fehlenden Module (leer = alles vorhanden).

    Gibt ``None`` zurueck, wenn die Pruefung selbst nicht moeglich war (fehlender
    Interpreter, Zeitueberschreitung). Das ist ausdruecklich NICHT dasselbe wie
    "nichts fehlt" - der Aufrufer soll beides unterscheiden koennen, statt einen
    unbekannten Zustand als gesund zu melden.
    """
    # Ein Unterprozess fuer alle Module: neun einzelne Starts kosten ein
    # Vielfaches, und die Frage ist pro Modul unabhaengig.
    code = (
        "import importlib.util as u\n"
        "for n in %r:\n"
        "    print(n if u.find_spec(n) is None else '', end=';')\n" % (list(MODULE),)
    )
    try:
        p = subprocess.run([interpreter, "-c", code], capture_output=True,
                           text=True, timeout=_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    return [n for n in p.stdout.split(";") if n]


def bericht(interpreter: str = INTERPRETER) -> str:
    """Einzeiler fuer das Journal. Leerer String = alles in Ordnung.

    Absichtlich nur bei einem PROBLEM eine Meldung: eine Zeile bei jedem Start,
    die immer dasselbe sagt, wird nach zwei Tagen nicht mehr gelesen.
    """
    fehlt = fehlende(interpreter)
    if fehlt is None:
        return (f"[Sandbox-Python] Pruefung nicht moeglich ({interpreter} nicht "
                "ausfuehrbar?) - Zustand der Agent-Shell unbekannt.")
    if not fehlt:
        return ""
    was = ", ".join(f"{n} ({MODULE[n]})" for n in fehlt)
    return (f"[Sandbox-Python] WARNUNG: {len(fehlt)} Modul(e) fehlen in {interpreter} "
            f"- {was}. Der Agent kann diese Aufgaben per Shell NICHT erledigen. "
            "Abhilfe: sudo bash deploy/sandbox_python.sh")
