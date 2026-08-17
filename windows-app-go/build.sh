#!/bin/bash
# Cross-Compile jarvis.exe für Windows (von Linux aus)
set -e

# Buildnummer aus buildnum.txt lesen und inkrementieren
NUMFILE="$(dirname "$0")/buildnum.txt"
NUM=$(cat "$NUMFILE" 2>/dev/null || echo "800")
NUM=$((NUM + 1))
echo "$NUM" > "$NUMFILE"
VERSION="0.$(printf '%03d' "$NUM")"
echo "Build $VERSION..."

CGO_ENABLED=1 \
GOOS=windows \
GOARCH=amd64 \
CC=x86_64-w64-mingw32-gcc \
CXX=x86_64-w64-mingw32-g++ \
go build -ldflags="-H windowsgui -s -w -X main.AppVersion=$VERSION" -o jarvis.exe .

echo "Fertig: $(ls -lh jarvis.exe)  [Build $VERSION]"

# ── Deploy auf jarvis-ai.info via FTPS ────────────────────────────────────────
# Der SSH-Weg ist TOT: der Abo-Benutzer laeuft in eine defekte chroot-Umgebung,
# Shell UND sftp-server scheitern mit Exit 255 (nachgemessen 2026-08-17).
# FTPS ist am Server korrekt aktiviert und funktioniert.
#
# ⚠ NETZWEG: In den Firmennetzen faengt ein FTP-ALG das Kommando 'AUTH TLS' ab
#   ("502 ... contact your network administrator"). Dann bricht der Deploy mit
#   einem Klartext-Hinweis ab. Aus einem Netz OHNE ALG (Handy-Tethering, VPN,
#   Homeoffice) laeuft er durch. Das ist KEIN Zertifikatsproblem – TLS kommt
#   gar nicht erst zustande.
#
# Zugangsdaten NIE hier eintragen (Repo ist oeffentlich!): entweder
# JARVIS_FTPS_USER/JARVIS_FTPS_PASS als Umgebungsvariablen, oder die Datei
# windows-app-go/.ftps_credentials (gitignored). Details: deploy_ftps.py
DOCROOT="${JARVIS_DOCROOT:-/var/www/vhosts/jarvis-ai.info/www}"
FTPS=("$(dirname "$0")/deploy_ftps.py")

echo "Deploying $VERSION nach $DOCROOT (FTPS) ..."

# Vorabpruefung: einmal anmelden. Scheitert es (z.B. ALG), bricht der Deploy
# hier ab – BEVOR halb hochgeladene Dateien einen inkonsistenten Stand erzeugen.
python3 "${FTPS[@]}" check

# EXE hochladen
python3 "${FTPS[@]}" put jarvis.exe "downloads/jarvis.exe"

# version_windows.json aktualisieren (PFAD: /downloads/ – UpdateChecker liest von dort)
printf '%s' "{\"versionCode\":$NUM,\"versionName\":\"$VERSION\",\"downloadUrl\":\"https://jarvis-ai.info/downloads/jarvis.exe\"}" \
  | python3 "${FTPS[@]}" putstr "downloads/version_windows.json"
echo "version_windows.json aktualisiert"

# Verify version_windows.json (HTTPS)
ACTUAL=$(curl -s "https://jarvis-ai.info/downloads/version_windows.json?t=$(date +%s)" --insecure | grep -o "\"versionCode\":$NUM" || true)
if [ -z "$ACTUAL" ]; then
  echo "⚠ WARNUNG: version_windows.json Verifikation fehlgeschlagen!"
else
  echo "✓ version_windows.json verifiziert: versionCode=$NUM"
fi

# index.html: Versionsstring im Download-Button aktualisieren
# DRIFT-SICHER: die LIVE-Datei laden, gezielt patchen, zurueckspielen. Niemals die
# Repo-Kopie hochladen – docs/landing-page/index.html driftet (siehe CLAUDE.md).
TMPHTML=$(mktemp)
python3 "${FTPS[@]}" get "index.html" "$TMPHTML"
# Pattern: "Portable EXE · v0.XXX" (mit v-Präfix wie in der Landing Page)
sed -i "s/Portable EXE · v[0-9]\+\.[0-9]\+/Portable EXE · v$VERSION/g" "$TMPHTML"
python3 "${FTPS[@]}" put "$TMPHTML" "index.html"
rm "$TMPHTML"

# Verify index.html
VERHTML=$(curl -s "https://jarvis-ai.info/" --insecure | grep -o "Portable EXE · v$VERSION" || true)
if [ -z "$VERHTML" ]; then
  echo "⚠ WARNUNG: index.html EXE-Version Verifikation fehlgeschlagen!"
else
  echo "✓ index.html verifiziert: $VERHTML"
fi
echo "index.html aktualisiert"

echo "Deploy $VERSION abgeschlossen."
