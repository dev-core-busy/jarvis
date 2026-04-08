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

# version_windows.json aktualisieren
echo "{\"versionCode\":$NUM,\"versionName\":\"$VERSION\",\"downloadUrl\":\"https://jarvis-ai.info/downloads/jarvis.exe\"}" \
  | curl --ssl-reqd --insecure -T - --user "$FTPS_USER" "$FTPS_BASE/version_windows.json"
echo "version_windows.json aktualisiert"

# index.html: Versionsstring im Download-Button aktualisieren
TMPHTML=$(mktemp)
curl -s "https://jarvis-ai.info/" -o "$TMPHTML"
# Alle "v0.XXX" im EXE-Download-Button ersetzen
sed -i "s/Download · Portable EXE · v[0-9]\+\.[0-9]\+/Download · Portable EXE · $VERSION/g" "$TMPHTML"
curl --ssl-reqd --insecure -T "$TMPHTML" --user "$FTPS_USER" "$FTPS_BASE/index.html"
rm "$TMPHTML"
echo "index.html aktualisiert"

echo "Deploy $VERSION abgeschlossen."
