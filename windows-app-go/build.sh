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

# ── Deploy auf jarvis-ai.info via SSH/SCP ─────────────────────────────────────
# FTP/FTPS ist ueber manche Netze unbrauchbar (FTP-ALG kapert das AUTH-Kommando);
# Deploy laeuft daher per SSH mit Public-Key (keyless) – kein Secret im Repo.
# Ueberschreibbar via JARVIS_SSH_HOST / JARVIS_SSH_KEY / JARVIS_DOCROOT.
SSH_HOST="${JARVIS_SSH_HOST:-jarvis@jarvis-ai.info}"
SSH_KEY="${JARVIS_SSH_KEY:-$HOME/.ssh/id_rsa}"
DOCROOT="${JARVIS_DOCROOT:-/var/www/vhosts/jarvis-ai.info/www}"
SSH=(ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ConnectTimeout=20)
SCP=(scp -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ConnectTimeout=20)

echo "Deploying $VERSION auf $SSH_HOST:$DOCROOT ..."

# EXE hochladen
"${SCP[@]}" jarvis.exe "$SSH_HOST:$DOCROOT/downloads/jarvis.exe"
echo "EXE hochgeladen"

# version_windows.json aktualisieren (PFAD: /downloads/ – UpdateChecker liest von dort)
printf '%s' "{\"versionCode\":$NUM,\"versionName\":\"$VERSION\",\"downloadUrl\":\"https://jarvis-ai.info/downloads/jarvis.exe\"}" \
  | "${SSH[@]}" "$SSH_HOST" "cat > '$DOCROOT/downloads/version_windows.json'"
echo "version_windows.json aktualisiert"

# Verify version_windows.json (HTTPS)
ACTUAL=$(curl -s "https://jarvis-ai.info/downloads/version_windows.json?t=$(date +%s)" --insecure | grep -o "\"versionCode\":$NUM" || true)
if [ -z "$ACTUAL" ]; then
  echo "⚠ WARNUNG: version_windows.json Verifikation fehlgeschlagen!"
else
  echo "✓ version_windows.json verifiziert: versionCode=$NUM"
fi

# index.html: Versionsstring im Download-Button aktualisieren (drift-sicher: live laden, patchen, zurueck)
TMPHTML=$(mktemp)
"${SCP[@]}" "$SSH_HOST:$DOCROOT/index.html" "$TMPHTML"
# Pattern: "Portable EXE · v0.XXX" (mit v-Präfix wie in der Landing Page)
sed -i "s/Portable EXE · v[0-9]\+\.[0-9]\+/Portable EXE · v$VERSION/g" "$TMPHTML"
"${SCP[@]}" "$TMPHTML" "$SSH_HOST:$DOCROOT/index.html"
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
