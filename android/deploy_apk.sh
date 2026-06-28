#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Veroeffentlicht die signierte Release-APK auf jarvis-ai.info via SSH/SCP.
# Voraussetzung: APK ist gebaut  ->  ./gradlew assembleRelease
#                versionCode in app/build.gradle.kts ist HOEHER als der Live-Stand
#                (sonst greift das In-App-Auto-Update nicht).
# Auth: SSH Public-Key (keyless) – kein Secret im Repo. FTP/FTPS wird bewusst
# NICHT genutzt (FTP-ALG mancher Netze kapert das AUTH-Kommando).
# Override via JARVIS_SSH_HOST / JARVIS_SSH_KEY / JARVIS_DOCROOT.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"

APK="${1:-app/build/outputs/apk/release/app-release.apk}"
[ -f "$APK" ] || { echo "APK fehlt: $APK – zuerst './gradlew assembleRelease'." >&2; exit 1; }

SSH_HOST="${JARVIS_SSH_HOST:-jarvis@jarvis-ai.info}"
SSH_KEY="${JARVIS_SSH_KEY:-$HOME/.ssh/id_rsa}"
DOCROOT="${JARVIS_DOCROOT:-/var/www/vhosts/jarvis-ai.info/www}"
SSH=(ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ConnectTimeout=20)
SCP=(scp -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ConnectTimeout=20)

CODE=$(grep -oE 'versionCode = [0-9]+' app/build.gradle.kts | grep -oE '[0-9]+' | head -1)
NAME=$(grep -oE 'versionName = "[^"]+"' app/build.gradle.kts | sed -E 's/.*"([^"]+)".*/\1/' | head -1)
[ -n "$CODE" ] && [ -n "$NAME" ] || { echo "versionCode/Name aus build.gradle.kts nicht ermittelbar." >&2; exit 1; }

echo "Veroeffentliche APK $NAME (Code $CODE) -> $SSH_HOST:$DOCROOT/downloads/jarvis.apk"
"${SCP[@]}" "$APK" "$SSH_HOST:$DOCROOT/downloads/jarvis.apk"

printf '%s' "{\"versionCode\":$CODE,\"versionName\":\"$NAME\",\"downloadUrl\":\"https://jarvis-ai.info/downloads/jarvis.apk\"}" \
  | "${SSH[@]}" "$SSH_HOST" "cat > '$DOCROOT/downloads/version_android.json'"
echo "version_android.json aktualisiert"

ACTUAL=$(curl -s "https://jarvis-ai.info/downloads/version_android.json?t=$(date +%s)" --insecure | grep -o "\"versionCode\":$CODE" || true)
if [ -n "$ACTUAL" ]; then
  echo "✓ version_android.json live: versionCode=$CODE"
else
  echo "⚠ WARNUNG: version_android.json Verifikation fehlgeschlagen (Cache?)." >&2
fi
echo "APK-Deploy ($NAME) abgeschlossen."
