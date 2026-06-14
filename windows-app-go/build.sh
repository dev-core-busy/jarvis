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

# ── Deploy auf jarvis-ai.info ─────────────────────────────────────────────────
# FTPS-Zugang NICHT hier hardcoden (oeffentliches Repo!). Quelle (erste gewinnt):
#   1) Umgebungsvariable JARVIS_FTPS_USER  (Format "user:passwort")
#   2) gitignore-te Datei  windows-app-go/.ftps_credentials  (setzt JARVIS_FTPS_USER=...)
CRED_FILE="$(dirname "$0")/.ftps_credentials"
if [ -z "$JARVIS_FTPS_USER" ] && [ -f "$CRED_FILE" ]; then
  # shellcheck disable=SC1090
  . "$CRED_FILE"
fi
FTPS_USER="${JARVIS_FTPS_USER:?FTPS-Zugang fehlt – JARVIS_FTPS_USER setzen oder windows-app-go/.ftps_credentials anlegen (Format: JARVIS_FTPS_USER='jarvis:PASSWORT')}"
FTPS_BASE='ftp://jarvis-ai.info/www'

echo "Deploying $VERSION auf jarvis-ai.info..."

# EXE hochladen
curl --ssl-reqd --insecure -T jarvis.exe --user "$FTPS_USER" "$FTPS_BASE/downloads/jarvis.exe"
echo "EXE hochgeladen"

# version_windows.json aktualisieren (PFAD: /downloads/ – UpdateChecker liest von dort)
echo "{\"versionCode\":$NUM,\"versionName\":\"$VERSION\",\"downloadUrl\":\"https://jarvis-ai.info/downloads/jarvis.exe\"}" \
  | curl --ssl-reqd --insecure -T - --user "$FTPS_USER" "$FTPS_BASE/downloads/version_windows.json"
echo "version_windows.json aktualisiert"

# Verify version_windows.json
ACTUAL=$(curl -s "https://jarvis-ai.info/downloads/version_windows.json?t=$(date +%s)" --insecure | grep -o "\"versionCode\":$NUM" || true)
if [ -z "$ACTUAL" ]; then
  echo "⚠ WARNUNG: version_windows.json Verifikation fehlgeschlagen!"
else
  echo "✓ version_windows.json verifiziert: versionCode=$NUM"
fi

# index.html: Versionsstring im Download-Button aktualisieren
TMPHTML=$(mktemp)
curl -s --ssl-reqd --insecure --user "$FTPS_USER" "$FTPS_BASE/index.html" -o "$TMPHTML"
# Pattern: "Portable EXE · v0.XXX" (mit v-Präfix wie in der Landing Page)
sed -i "s/Portable EXE · v[0-9]\+\.[0-9]\+/Portable EXE · v$VERSION/g" "$TMPHTML"
curl --ssl-reqd --insecure -T "$TMPHTML" --user "$FTPS_USER" "$FTPS_BASE/index.html"
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
