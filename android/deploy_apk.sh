#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Veroeffentlicht die signierte Release-APK auf jarvis-ai.info (SFTP, Port 8023).
# Voraussetzung: APK ist gebaut  ->  ./gradlew assembleRelease
#                versionCode in app/build.gradle.kts ist HOEHER als der Live-Stand
#                (sonst greift das In-App-Auto-Update nicht – das Skript prueft es).
#
# ⚠ WEG (2026-10-12): SSH/SCP auf Port 22 ist tot ("scp: Connection closed"),
# FTPS auf Port 21 faengt das Firmennetz ab. Uebertragen wird ueber
# deploy/jarvis_ai_sftp.py (paramiko, Port 8023); Zugangsdaten in .env
# (JARVIS_SFTP_PASS), nie im Repo.
#
# Ablauf: Live-Stand lesen -> Vorfassung AUSSERHALB der Website sichern ->
# APK atomar hochladen -> version_android.json -> per HTTPS md5 gegenpruefen.
# Die Versionsdatei kommt NACH der APK: andersherum boete das Auto-Update fuer
# einen Moment eine neue Nummer mit der alten Datei an.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"

APK="${1:-app/build/outputs/apk/release/app-release.apk}"
[ -f "$APK" ] || { echo "APK fehlt: $APK – zuerst './gradlew assembleRelease'." >&2; exit 1; }
SFTP=(python3 ../deploy/jarvis_ai_sftp.py)
BASIS="https://jarvis-ai.info/downloads"

CODE=$(grep -oE 'versionCode = [0-9]+' app/build.gradle.kts | grep -oE '[0-9]+' | head -1)
NAME=$(grep -oE 'versionName = "[^"]+"' app/build.gradle.kts | sed -E 's/.*"([^"]+)".*/\1/' | head -1)
[ -n "$CODE" ] && [ -n "$NAME" ] || { echo "versionCode/Name aus build.gradle.kts nicht ermittelbar." >&2; exit 1; }

# Die APK muss DIESE Version tragen – sonst wuerde eine alte Datei unter neuer Nummer verteilt
META="$(dirname "$APK")/output-metadata.json"
if [ -f "$META" ] && ! grep -q "\"versionCode\": $CODE," "$META"; then
  echo "FEHLER: $APK traegt nicht versionCode $CODE (zuerst neu bauen)." >&2; exit 1
fi

LIVE_JSON=$("${SFTP[@]}" cat downloads/version_android.json)
LIVE_CODE=$(printf '%s' "$LIVE_JSON" | grep -oE '"versionCode": *[0-9]+' | grep -oE '[0-9]+$' || true)
LIVE_NAME=$(printf '%s' "$LIVE_JSON" | grep -oE '"versionName": *"[^"]+"' | sed -E 's/.*"([^"]+)"$/\1/' || true)
[ -n "$LIVE_CODE" ] || { echo "FEHLER: Live-Stand nicht lesbar: $LIVE_JSON" >&2; exit 1; }
echo "Live: $LIVE_NAME (Code $LIVE_CODE)  ->  neu: $NAME (Code $CODE)"
if [ "$CODE" -le "$LIVE_CODE" ]; then
  echo "FEHLER: versionCode $CODE ist nicht hoeher als der Live-Stand $LIVE_CODE – nichts geaendert." >&2
  exit 1
fi

"${SFTP[@]}" sichern downloads/jarvis.apk "jarvis-${LIVE_NAME}.apk.bak"
"${SFTP[@]}" put "$APK" downloads/jarvis.apk
printf '%s' "{\"versionCode\":$CODE,\"versionName\":\"$NAME\",\"downloadUrl\":\"$BASIS/jarvis.apk\"}" \
  | "${SFTP[@]}" putstr downloads/version_android.json

# Gegenprobe ueber HTTPS: was AUSGELIEFERT wird, nicht was hochgeladen wurde
SOLL=$(md5sum < "$APK" | cut -c1-32)
IST=$(curl -sf "$BASIS/jarvis.apk?t=$(date +%s)" | md5sum | cut -c1-32)
JSON=$(curl -sf "$BASIS/version_android.json?t=$(date +%s)" || true)
if [ "$SOLL" = "$IST" ] && printf '%s' "$JSON" | grep -q "\"versionCode\":$CODE"; then
  echo "✓ live: jarvis.apk md5-gleich, version_android.json = $CODE"
else
  echo "⚠ WARNUNG: Gegenprobe fehlgeschlagen (md5 $IST statt $SOLL, json: $JSON)" >&2
  exit 1
fi
echo "APK-Deploy ($NAME) abgeschlossen."
