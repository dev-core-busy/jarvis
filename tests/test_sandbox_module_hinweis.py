#!/usr/bin/env python3
"""Prueft den Klartext-Hinweis bei fehlenden Python-Modulen (shell.py)
und das Bereitstellungs-Skript deploy/sandbox_python.sh.

HINTERGRUND (Vorfall ECHT 2026-08-18): Eine Anfrage "54 Adressen aus dem PDF in
eine Exceltabelle" endete in einer CSV-Notloesung und danach in einem Lauf ohne
jedes Ergebnis. Ursache waren fehlende Module im SYSTEM-Python, in dem
shell_execute laeuft (das Backend laeuft im venv, wo alles vorhanden ist).
Ohne Hinweis probiert das Modell weitere Importe, statt das vorhandene Werkzeug
zu nehmen.

Laeuft OHNE fastapi: die Funktionen werden per Quelltext aus shell.py geladen,
backend.config ist ein Stub. Der echte Import wuerde eine Profil-Migration
ausloesen und die Live-settings.json zurueckschreiben.
"""
import re
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
SHELL_PY = WURZEL / "backend" / "tools" / "shell.py"
SKRIPT = WURZEL / "deploy" / "sandbox_python.sh"

ok = fail = 0


def pruef(name, bedingung, info=""):
    global ok, fail
    if bedingung:
        ok += 1
        print(f"  \033[32m✓\033[0m {name}")
    else:
        fail += 1
        print(f"  \033[31m✗\033[0m {name}" + (f"  → {info}" if info else ""))


# ── Funktionen per Quelltext laden (kein fastapi-Import) ────────────────────
quelle = SHELL_PY.read_text(encoding="utf-8")
raum = {"re": re}
for stueck in ("_MODUL_ERSATZ", "_MODUL_FEHLT_RE", "def _modul_hinweis"):
    start = quelle.index(stueck)
    # bis zur naechsten Top-Level-Definition
    rest = quelle[start:]
    m = re.search(r"\n(?=[A-Za-z_@#]|class |def )", rest[1:])
    ende = len(rest)
    for kandidat in ("\n_MODUL_FEHLT_RE", "\n# Nur der Wurzel", "\n\nclass "):
        p = rest.find(kandidat, 1)
        if p > 0:
            ende = min(ende, p)
    exec(compile(rest[:ende], "shell.py", "exec"), raum)
_modul_hinweis = raum["_modul_hinweis"]
_MODUL_ERSATZ = raum["_MODUL_ERSATZ"]


def nur_code(text: str) -> str:
    """Kommentare und Docstrings entfernen.

    Ein Waechter, der seine eigene Begruendung liest, prueft nichts - dieser
    Fehler ist im Projekt viermal aufgetreten.
    """
    text = re.sub(r'"""(?:.|\n)*?"""', "", text)
    return "\n".join(z.split("#")[0] for z in text.splitlines())


CODE = nur_code(quelle)

print("\n\033[1m1. Erkennung der Fehlermeldung\033[0m")
echt = ("STDERR:\nTraceback (most recent call last):\n"
        "  File \"/tmp/extract_kim.py\", line 1, in <module>\n"
        "    import pdfplumber\nModuleNotFoundError: No module named 'pdfplumber'\n"
        "\nExit-Code: 1")
res = _modul_hinweis(echt)
pruef("gemeldeter pdfplumber-Fehler wird erkannt", "HINWEIS_AN_NUTZER" in res)
pruef("Originalausgabe bleibt vollstaendig erhalten", echt in res)
pruef("nennt den Ersatzweg pdftotext", "pdftotext" in res)

res_x = _modul_hinweis("ModuleNotFoundError: No module named 'openpyxl'")
pruef("openpyxl verweist auf office_create_excel",
      "office_create_excel" in res_x, res_x)
pruef("sagt, dass Nachinstallieren nicht moeglich ist",
      "NICHT moeglich" in res_x)
pruef("nennt das Skript fuer den Administrator",
      "deploy/sandbox_python.sh" in res_x)

print("\n\033[1m2. Keine Falschmeldung\033[0m")
sauber = "STDOUT:\n3855 /tmp/pdf_text.txt"
pruef("unauffaellige Ausgabe bleibt unveraendert",
      _modul_hinweis(sauber) == sauber)
pruef("leere Ausgabe bleibt leer", _modul_hinweis("") == "")
pruef("'No module named' ohne Namen erzeugt keinen Hinweis",
      "HINWEIS_AN_NUTZER" not in _modul_hinweis("No module named"))
# Ein Suchbegriff im Text darf nicht wie ein Fehler wirken
treffer = _modul_hinweis("STDOUT:\n  grep: kein Treffer fuer openpyxl")
pruef("blosse Nennung eines Modulnamens loest nichts aus",
      "HINWEIS_AN_NUTZER" not in treffer)

print("\n\033[1m3. Mehrere und verschachtelte Module\033[0m")
zwei = _modul_hinweis("No module named 'openpyxl'\nNo module named 'pandas'")
pruef("beide Module werden genannt",
      "openpyxl" in zwei and "pandas" in zwei)
pruef("Hinweiskopf steht nur einmal", zwei.count("HINWEIS_AN_NUTZER") == 1)
doppelt = _modul_hinweis("No module named 'pandas'\nNo module named 'pandas'")
pruef("derselbe Name wird nicht doppelt aufgefuehrt",
      doppelt.count("- pandas ist nicht") == 1)
unter = _modul_hinweis("No module named 'docx.oxml'")
pruef("Untermodul wird auf die Wurzel zurueckgefuehrt",
      "office_create_word" in unter, unter)
unbekannt = _modul_hinweis("No module named 'irgendwas_exotisches'")
pruef("unbekanntes Modul wird gemeldet, ohne Rat zu erfinden",
      "irgendwas_exotisches" in unbekannt and "HINWEIS_AN_NUTZER" in unbekannt)

print("\n\033[1m4. Inhalt der Zuordnung\033[0m")
# Jede Empfehlung muss auf ein Werkzeug ODER die Standardbibliothek zeigen -
# niemals auf ein weiteres Fremdmodul, das genauso fehlen kann.
for modul, rat in _MODUL_ERSATZ.items():
    pass
pruef("Excel-Module zeigen auf office_create_excel",
      all("office_create_excel" in _MODUL_ERSATZ[m]
          for m in ("openpyxl", "xlsxwriter", "xlwt")))
pruef("Diagramm-Module zeigen auf create_chart",
      all("create_chart" in _MODUL_ERSATZ[m]
          for m in ("matplotlib", "seaborn", "plotly")))
pruef("PDF-Module zeigen auf den Verlauf bzw. pdftotext",
      all("pdftotext" in _MODUL_ERSATZ[m]
          for m in ("pdfplumber", "pypdf", "PyPDF2", "fitz")))
pruef("jira verweist auf die jira_*-Werkzeuge, nicht auf pip",
      "jira_*" in _MODUL_ERSATZ["jira"])
pruef("kein Rat empfiehlt pip install",
      not any("pip install" in r for r in _MODUL_ERSATZ.values()))
pruef("pandas verweist auf csv + office_create_excel",
      "csv" in _MODUL_ERSATZ["pandas"]
      and "office_create_excel" in _MODUL_ERSATZ["pandas"])

print("\n\033[1m5. Verdrahtung in shell.py\033[0m")
# Der Hinweis muss an JEDEM Ergebnis-Rueckgabepunkt greifen. Der Broker-Weg ist
# auf ECHT der maszgebliche (Domain-Benutzer laufen als Sandbox-OS-Benutzer);
# haenge er nur am lokalen Zweig, waere der Fix dort still unwirksam.
pruef("alle Ergebnis-Rueckgaben laufen durch _modul_hinweis",
      CODE.count("_modul_hinweis(result.strip())") == 3,
      f"gefunden: {CODE.count('_modul_hinweis(result.strip())')}")
pruef("kein Rueckgabepunkt umgeht den Hinweis",
      'return result.strip() or "(Keine Ausgabe)"' not in CODE)
broker = CODE[CODE.index("_exec_via_broker(self"):]
pruef("der Broker-Weg (Sandbox) ist verdrahtet",
      "_modul_hinweis" in broker)
pruef("_modul_hinweis ist genau einmal definiert",
      CODE.count("def _modul_hinweis") == 1)
pruef("Fehler in der Hinweis-Logik kippt den Befehl nicht",
      "except Exception:" in quelle[quelle.index("def _modul_hinweis"):
                                    quelle.index("class ShellTool")])

print("\n\033[1m6. Bereitstellungs-Skript\033[0m")
pruef("deploy/sandbox_python.sh existiert", SKRIPT.exists())
skript = SKRIPT.read_text(encoding="utf-8")
pruef("ist ausfuehrbar", SKRIPT.stat().st_mode & 0o111)
pruef("Bash-Syntax fehlerfrei",
      subprocess.run(["bash", "-n", str(SKRIPT)],
                     capture_output=True).returncode == 0)
# Die gemessene Modul-Liste MUSS die Faelle aus dem Vorfall abdecken.
for modul in ("openpyxl", "pandas", "pdfplumber", "pypdf", "docx", "matplotlib"):
    pruef(f"Liste enthaelt {modul}", f'"{modul}:' in skript)
pruef("PyPDF2 wird NICHT installiert (ueberholt, pypdf ist der Nachfolger)",
      '"PyPDF2:' not in skript)
pruef("das Python-jira-Paket wird NICHT installiert (jira_*-Werkzeuge)",
      '"jira:' not in skript)
pruef("prueft mit dem Sandbox-Benutzer, nicht nur als root",
      "runuser -u" in skript and "SANDBOX_USER" in skript)
pruef("nutzt python3 aus dem PATH, nicht das venv",
      "command -v python3" in skript and "venv/bin/python" not in skript)
pruef("idempotent: installiert nur Fehlendes",
      "FEHLEND_PIP" in skript and "-eq 0" in skript)
pruef("--pruefen installiert nichts",
      "NUR_PRUEFEN" in skript and "exit 1" in skript)
pruef("beobachtet den numpy-Stand",
      "NUMPY_VOR" in skript and "NUMPY_NACH" in skript)
pruef("prueft nach der Installation nach",
      "Nachpr" in skript and "FEHLT_NOCH" in skript)
pruef("nennt --break-system-packages (Debian 13)",
      "--break-system-packages" in skript)

print("\n\033[1m7. Der Vorfall selbst\033[0m")
# Genau die Ausgabe, die auf ECHT zur CSV-Notloesung fuehrte.
vorfall = ("STDOUT:\nTraceback (most recent call last):\n"
           "  File \"<string>\", line 1, in <module>\n"
           "    import openpyxl; print('ok')\n    ^^^^^^^^^^^^^^^\n"
           "ModuleNotFoundError: No module named 'openpyxl'\n"
           "openpyxl nicht verfügbar")
erg = _modul_hinweis(vorfall)
pruef("der protokollierte Fall erzeugt jetzt einen Hinweis",
      "HINWEIS_AN_NUTZER" in erg)
pruef("und weist auf office_create_excel statt auf eine CSV",
      "office_create_excel" in erg)

print("\n\033[1m8. Prompt-Waechter: keine unhaltbare Zusage\033[0m")
# DER KERN DES VORFALLS: der System-Prompt behauptete woertlich, openpyxl/pandas/
# matplotlib seien installiert, und verbot dem Modell zugleich, das Gegenteil zu
# sagen ("Behaupte NIEMALS, sie seien nicht installiert"). Auf ECHT war davon
# fast nichts vorhanden. Das Modell hat daraufhin weitergesucht statt das
# Werkzeug zu nehmen - dieselbe Fehlerklasse wie beim alten WA_TASK_PROMPT:
# eine Zusage, die der Code nicht haelt.
AGENT_PY = (WURZEL / "backend" / "agent.py").read_text(encoding="utf-8")
prompt_start = AGENT_PY.index("16. OFFICE-DOKUMENTE")
PUNKT16 = AGENT_PY[prompt_start:AGENT_PY.index("17. CODE & SKRIPTE")]

pruef("kein absolutes Verbot mehr, ein fehlendes Modul zu benennen",
      "Behaupte NIEMALS, sie seien nicht installiert" not in PUNKT16
      and "Behaupte NIEMALS, matplotlib" not in PUNKT16)
pruef("der Fall 'Modul fehlt doch' ist geregelt",
      "ModuleNotFoundError" in PUNKT16 and "HINWEIS_AN_NUTZER" in PUNKT16)
pruef("verbietet das Weitersuchen nach Modulen",
      "suche NICHT nach weiteren Modulen" in PUNKT16)
pruef("verlangt, dem Benutzer das fehlende Modul zu nennen",
      "welches Modul fehlt" in PUNKT16)
pruef("Excel geht ueber office_create_excel, nicht per openpyxl-Eigenbau",
      "openpyxl/pandas selbst zusammenbauen" in PUNKT16
      and "office_create_excel da" in PUNKT16)
# Genau die Notloesung, die auf ECHT herauskam.
pruef("CSV als Ersatz fuer eine gewuenschte Excel-Datei ist untersagt",
      "ersatzweise als CSV" in PUNKT16)
# Der Prompt-Waechter in test_skill_audit.py zaehlt Werkzeug-Nennungen ZEILENWEISE
# und wertet eine Zeile mit kein/nicht/NIEMALS als negative Nennung. Steht das
# Verbot in derselben Zeile wie die Aufforderung, faellt die positive Nennung
# weg und jener Test bricht ab. Eine Zeile = eine Aussage.
_z_positiv = [z for z in PUNKT16.splitlines()
              if "office_create_excel" in z
              and not re.search(r"kein[e]?\s|NIEMALS|NICHT\s|nicht\s", z)]
pruef("mindestens eine Zeile nennt office_create_excel OHNE Verbotswort",
      bool(_z_positiv), "Verbot und Aufforderung stehen in derselben Zeile")
pruef("die office_*-Werkzeuge sind als backend-seitig gekennzeichnet",
      "IM BACKEND" in PUNKT16)

print(f"\n{'─'*60}")
print(f"  \033[1m{ok} bestanden, {fail} fehlgeschlagen\033[0m")
sys.exit(1 if fail else 0)
