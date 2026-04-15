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
FTPS_USER='jarvis:FrLz%$w3iby36aZc'
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
# Pattern: "Portable EXE · 0.XXX" (ohne v-Präfix)
sed -i "s/Portable EXE · [0-9]\+\.[0-9]\+/Portable EXE · $VERSION/g" "$TMPHTML"
curl --ssl-reqd --insecure -T "$TMPHTML" --user "$FTPS_USER" "$FTPS_BASE/index.html"
rm "$TMPHTML"

# Verify index.html
VERHTML=$(curl -s "https://jarvis-ai.info/" --insecure | grep -o "Portable EXE · $VERSION" || true)
if [ -z "$VERHTML" ]; then
  echo "⚠ WARNUNG: index.html EXE-Version Verifikation fehlgeschlagen!"
else
  echo "✓ index.html verifiziert: $VERHTML"
fi
echo "index.html aktualisiert"

echo "Deploy $VERSION abgeschlossen."
