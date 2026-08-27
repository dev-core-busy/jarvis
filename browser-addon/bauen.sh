#!/usr/bin/env bash
# Baut die Auslieferungspakete fuer Chrome/Edge und Firefox.
#
# WARUM ZWEI PAKETE: Firefox kennt `background.service_worker` nicht und
# verlangt `background.scripts` (Event Pages) sowie eine Add-on-Kennung unter
# `browser_specific_settings.gecko.id`. Alles andere ist identisch – deshalb
# liegen NICHT zwei Codebasen im Repo, sondern nur zwei Manifeste.
#
# Gepackt wird mit Python statt `zip`: das Werkzeug fehlt auf schlanken
# Installationen (hier beim ersten Lauf genau so passiert), python3 ist wegen
# des Backends ohnehin Voraussetzung.
set -euo pipefail

HIER="$(cd "$(dirname "$0")" && pwd)"
cd "$HIER"

command -v python3 >/dev/null || { echo "FEHLER: python3 fehlt"; exit 2; }

python3 - "$HIER" <<'PYEOF'
import json
import pathlib
import sys
import zipfile

hier = pathlib.Path(sys.argv[1])
ziel = hier / "dist"
ziel.mkdir(exist_ok=True)

DATEIEN = ["background.js", "popup.html", "popup.js", "popup.css", "einfuegen.js"]
ICONS = sorted((hier / "icons").glob("*.png"))

fehlt = [d for d in DATEIEN if not (hier / d).exists()]
if fehlt or not ICONS:
    # Fail-closed: ein Paket, dem eine Datei fehlt, installiert sich klaglos und
    # bricht erst beim Benutzen – mit einer Meldung, die niemand deutet.
    print("FEHLER: es fehlen Dateien: %s" % (", ".join(fehlt) or "icons/*.png"))
    sys.exit(2)


def bauen(name, manifest):
    quelle = hier / manifest
    if not quelle.exists():
        print("FEHLER: %s fehlt" % manifest)
        sys.exit(2)
    # Das Manifest wird GEPRUEFT, nicht nur kopiert: ein Komma zu viel und der
    # Browser lehnt die Installation mit einer generischen Meldung ab.
    try:
        m = json.loads(quelle.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print("FEHLER: %s ist kein gueltiges JSON (%s)" % (manifest, e))
        sys.exit(2)

    pfad = ziel / name
    with zipfile.ZipFile(pfad, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", quelle.read_text(encoding="utf-8"))
        for d in DATEIEN:
            z.write(hier / d, d)
        for i in ICONS:
            z.write(i, "icons/" + i.name)
    print("  %-28s %6.1f KB  (Version %s)"
          % (name, pfad.stat().st_size / 1024, m.get("version", "?")))


print("Baue Pakete nach %s:" % ziel)
bauen("jarvis-jira-chrome.zip", "manifest.json")
bauen("jarvis-jira-firefox.zip", "manifest.firefox.json")
PYEOF

cat <<'ENDE'

Weiter:
  Chrome/Edge  chrome://extensions -> Entwicklermodus -> "Entpackt laden"
               und den ORDNER browser-addon/ waehlen (nicht das ZIP).
               Das ZIP ist fuer die spaetere Verteilung per Gruppenrichtlinie.
  Firefox      about:debugging -> "Dieses Firefox" -> "Temporaeres Add-on laden"
               -> jarvis-jira-firefox.zip.
               ACHTUNG: temporaer heisst temporaer - beim Beenden ist es weg.
               Dauerhaft geht in Firefox NUR mit einer Signatur von Mozilla
               (auch fuer selbst verteilte Add-ons). Siehe README.
ENDE
