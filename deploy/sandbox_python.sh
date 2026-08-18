#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Python-Module für die Agent-Shell bereitstellen
#
# DER BEFUND (gemessen auf ECHT am 2026-08-18): Ein Benutzer bat um eine
# Excel-Tabelle mit 54 Adressen aus einem PDF. Der Agent bekam
#   ModuleNotFoundError: No module named 'openpyxl'
#   ModuleNotFoundError: No module named 'pandas'
#   ModuleNotFoundError: No module named 'pdfplumber'
# lieferte daraufhin selbst die Begründung „da Excel-Bibliotheken nicht
# installiert sind" und wich auf eine CSV aus. Der zweite Anlauf verbrauchte
# alle 15 Schritte damit, aus `pdftotext -layout` die Spalten eines Formulars zu
# rekonstruieren – die Aufgabe, für die pdfplumber Koordinaten liefert – und
# endete ohne jedes Ergebnis.
#
# URSACHE sind ZWEI Python-Welten auf demselben Server:
#   * Backend und Skills laufen im venv (/opt/jarvis/venv) – dort liegt alles.
#   * `shell_execute` startet `/usr/bin/python3` (bei Domain-Benutzern zusätzlich
#     als Sandbox-OS-Benutzer). Das ist das SYSTEM-Python – eine andere Welt.
# Der Skill-Lifecycle installiert mit `sys.executable`, also ins venv. Was ein
# Skill deklariert, kommt damit NIE im System-Python an. Der Agent landet in der
# ärmeren Welt und hat keinen Weg heraus: `pip install` ist ihm verwehrt
# (kein Internet, keine Rechte) – zu Recht, aber ohne diese Vorbereitung
# bleibt ihm nur ein schlechteres Ergebnis.
#
# WARUM EIN SKRIPT UND KEINE HANDARBEIT: genau diese Handarbeit ist der Grund,
# weshalb DEV und ECHT auseinandergelaufen sind. Auf DEV lagen openpyxl, pandas,
# matplotlib, pypdf und Pillow im System-Python, auf ECHT nur lxml, python-pptx
# und xlsxwriter – dieselbe Anfrage gelingt hier und scheitert dort. Dasselbe
# Muster wie beim PDF-Export („bei dir geht PDF, bei mir nicht", CLAUDE.md).
#
# DIE LISTE IST GEMESSEN, NICHT GERATEN: sie stammt aus allen 410 gespeicherten
# Konversationen auf ECHT (`grep "No module named"`), nach Häufigkeit:
#   openpyxl 5x · pandas 4x · pypdf 2x · pdfplumber 2x · PyPDF2 1x · docx 1x
# Nicht aufgenommen: `PyPDF2` (überholt, pypdf ist der Nachfolger) und `jira`
# (dafür gibt es die jira_*-Werkzeuge – der Import war eine Fehlwahl des
# Modells, kein Bedarf). matplotlib/Pillow stehen dabei, weil der serverseitige
# Diagramm-Weg sie braucht und sie auf ECHT nie installiert wurden.
#
# NUMPY WIRD NICHT ANGEFASST: es kommt auf ECHT aus apt (2.2.4) und erfüllt die
# Anforderungen von pandas/matplotlib, pip lässt es deshalb in Ruhe (mit
# `--dry-run` nachgewiesen). Das venv unterliegt weiter `numpy<2.1` – es ist
# eine getrennte Welt und wird hier nicht berührt.
#
# IDEMPOTENT: installiert nur, was fehlt. Mehrfach ausführbar.
#
#   sudo bash deploy/sandbox_python.sh [--pruefen]
#
#   --pruefen   zeigt nur den Zustand, installiert nichts (Exit 1 = etwas fehlt)
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

NUR_PRUEFEN=0
[[ "${1:-}" == "--pruefen" ]] && NUR_PRUEFEN=1

SANDBOX_USER="${JARVIS_SANDBOX_USER:-jarvis_sandbox}"

# Modul-Importname:pip-Paketname  (beides nötig – sie weichen oft ab)
MODULE=(
    "openpyxl:openpyxl"
    "pandas:pandas"
    "pdfplumber:pdfplumber"
    "pypdf:pypdf"
    "docx:python-docx"
    "pptx:python-pptx"
    "xlsxwriter:XlsxWriter"
    "matplotlib:matplotlib"
    "PIL:Pillow"
)

# Der Interpreter, den `shell_execute` per `python3 <datei>` startet – nicht der
# des venv. Über PATH aufgelöst, damit das Skript dieselbe Datei prüft, die der
# Agent später ausführt.
PY="$(command -v python3 || true)"
if [[ -z "$PY" ]]; then
    echo "✗ python3 nicht gefunden – Abbruch." >&2
    exit 2
fi

# Läuft der Sandbox-Benutzer? Dann MIT ihm prüfen: er hat kein schreibbares HOME
# und andere Rechte, ein Import kann allein daran scheitern. Ohne ihn (Systeme
# ohne getrennten Betrieb) genügt der eigene Kontext.
if id "$SANDBOX_USER" &>/dev/null && [[ "$(id -u)" == "0" ]]; then
    pruefe() { runuser -u "$SANDBOX_USER" -- "$PY" -c "import $1" 2>/dev/null; }
    ALS="als $SANDBOX_USER"
else
    pruefe() { "$PY" -c "import $1" 2>/dev/null; }
    ALS="als $(id -un)"
fi

echo "Interpreter der Agent-Shell: $PY  (geprüft $ALS)"
echo "$("$PY" -V 2>&1)"
echo

FEHLEND_PIP=()
FEHLEND_MOD=()
for eintrag in "${MODULE[@]}"; do
    modul="${eintrag%%:*}"
    paket="${eintrag##*:}"
    if pruefe "$modul"; then
        printf '  ✓ %-12s\n' "$modul"
    else
        printf '  ✗ %-12s  (pip: %s)\n' "$modul" "$paket"
        FEHLEND_MOD+=("$modul")
        FEHLEND_PIP+=("$paket")
    fi
done
echo

if [[ ${#FEHLEND_PIP[@]} -eq 0 ]]; then
    echo "✓ Alle Module vorhanden – nichts zu tun."
    exit 0
fi

if [[ $NUR_PRUEFEN -eq 1 ]]; then
    echo "Es fehlen ${#FEHLEND_PIP[@]} Modul(e): ${FEHLEND_MOD[*]}"
    echo "Zum Installieren: sudo bash $0"
    exit 1
fi

if [[ "$(id -u)" != "0" ]]; then
    echo "✗ Zum Installieren als root ausführen (sudo bash $0)." >&2
    exit 2
fi

# numpy-Stand VOR der Installation festhalten. pandas/matplotlib bringen eine
# numpy-Anforderung mit; wird die vorhandene (apt-)Version ersetzt, muss man das
# SEHEN – auf einer VM ohne AVX/SSE4.2 ist ein numpy-Sprung nicht harmlos.
NUMPY_VOR="$("$PY" -c 'import numpy; print(numpy.__version__)' 2>/dev/null || echo '-')"

echo "Installiere: ${FEHLEND_PIP[*]}"
# --break-system-packages ist auf Debian 13 nötig (EXTERNALLY-MANAGED) und der
# auf diesem Server bereits etablierte Weg: lxml, python-pptx und XlsxWriter
# liegen genau so in /usr/local/lib/python3*/dist-packages.
if ! "$PY" -m pip install --break-system-packages "${FEHLEND_PIP[@]}"; then
    echo "✗ pip install fehlgeschlagen." >&2
    exit 3
fi
echo

NUMPY_NACH="$("$PY" -c 'import numpy; print(numpy.__version__)' 2>/dev/null || echo '-')"
if [[ "$NUMPY_VOR" != "$NUMPY_NACH" ]]; then
    echo "⚠ numpy wurde verändert: $NUMPY_VOR → $NUMPY_NACH"
    echo "  Auf Maschinen ohne AVX/SSE4.2 (die DEV-VM) prüfen, dass numpy noch lädt."
else
    echo "✓ numpy unverändert ($NUMPY_NACH)"
fi
echo

echo "Nachprüfung $ALS:"
FEHLT_NOCH=0
for eintrag in "${MODULE[@]}"; do
    modul="${eintrag%%:*}"
    if pruefe "$modul"; then
        printf '  ✓ %-12s\n' "$modul"
    else
        printf '  ✗ %-12s  IMMER NOCH NICHT IMPORTIERBAR\n' "$modul"
        FEHLT_NOCH=1
    fi
done

if [[ $FEHLT_NOCH -eq 1 ]]; then
    echo
    echo "✗ Mindestens ein Modul ist trotz Installation nicht importierbar."
    echo "  Häufigste Ursache: pip hat in einen anderen Interpreter installiert."
    exit 3
fi

echo
echo "✓ Fertig. Kein Dienst-Neustart nötig – shell_execute startet python3 pro Aufruf neu."
