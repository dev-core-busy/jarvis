#!/bin/bash
# Cross-Compile jarvis.exe für Windows (von Linux aus) und Veroeffentlichung.
#
#   build.sh                  Buildnummer +1, bauen, hochladen (wie bisher)
#   build.sh --ohne-hochladen Buildnummer +1, nur bauen
#   build.sh --nur-hochladen  die schon gebaute jarvis.exe zur AKTUELLEN Nummer
#                             hochladen (kein Neubau, Nummer bleibt)
#
# Die Nummer wird erst NACH einem erfolgreichen Bau fortgeschrieben – ein
# gescheiterter Bau verbraucht sonst eine Nummer, die nie ausgeliefert wurde.
set -euo pipefail
cd "$(dirname "$0")"

MODUS="alles"
case "${1:-}" in
  "") ;;
  --ohne-hochladen) MODUS="bauen" ;;
  --nur-hochladen)  MODUS="hochladen" ;;
  *) echo "Aufruf: $0 [--ohne-hochladen | --nur-hochladen]" >&2; exit 1 ;;
esac

NUMFILE="buildnum.txt"
NUM=$(cat "$NUMFILE" 2>/dev/null || echo "800")
[ "$MODUS" = "hochladen" ] || NUM=$((NUM + 1))
VERSION="0.$(printf '%03d' "$NUM")"

if [ "$MODUS" != "hochladen" ]; then
  echo "Build $VERSION..."
  # Vorgabe-Server des Clients: NIE im Repo, optional aus Umgebung/.env
  # (JARVIS_CLIENT_SERVER_URL, z.B. wss://<host>/ws). Leer = Eingabe in den Einstellungen.
  CLIENT_URL="${JARVIS_CLIENT_SERVER_URL:-$(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import ziele; print(ziele.finde("JARVIS_CLIENT_SERVER_URL") or "")' ../deploy)}"

  CGO_ENABLED=1 \
  GOOS=windows \
  GOARCH=amd64 \
  CC=x86_64-w64-mingw32-gcc \
  CXX=x86_64-w64-mingw32-g++ \
  go build -ldflags="-H windowsgui -s -w -X main.AppVersion=$VERSION -X main.DefaultServerURL=$CLIENT_URL" -o jarvis.exe .

  echo "$NUM" > "$NUMFILE"
  echo "Fertig: $(ls -lh jarvis.exe)  [Build $VERSION]"
  [ "$MODUS" = "bauen" ] && exit 0
fi

# ── Deploy auf jarvis-ai.info via SFTP (Port 8023) ────────────────────────────
# ⚠ WEG (2026-10-12): FTPS auf Port 21 faengt das Firmennetz ab (FTP-ALG
# kapert 'AUTH TLS'), SSH/SCP auf Port 22 ist tot. Uebertragen wird ueber
# deploy/jarvis_ai_sftp.py (paramiko, Port 8023, atomarer Upload); Zugangsdaten
# in .env (JARVIS_SFTP_PASS), NIE hier – das Repo ist oeffentlich.
#
# Reihenfolge: EXE vor version_windows.json – andersherum boete der
# UpdateChecker fuer einen Moment die neue Nummer mit der alten Datei an.
SFTP=(python3 ../deploy/jarvis_ai_sftp.py)
BASIS="https://jarvis-ai.info"

[ -f jarvis.exe ] || { echo "FEHLER: jarvis.exe fehlt – zuerst bauen." >&2; exit 1; }
# Die EXE muss DIESE Version tragen (-X main.AppVersion steht als Text darin)
if ! grep -aqF "$VERSION" jarvis.exe; then
  echo "FEHLER: jarvis.exe traegt nicht Version $VERSION – nichts hochgeladen." >&2; exit 1
fi

LIVE_JSON=$("${SFTP[@]}" cat downloads/version_windows.json)
LIVE_NUM=$(printf '%s' "$LIVE_JSON" | grep -oE '"versionCode": *[0-9]+' | grep -oE '[0-9]+$' || true)
LIVE_NAME=$(printf '%s' "$LIVE_JSON" | grep -oE '"versionName": *"[^"]+"' | sed -E 's/.*"([^"]+)"$/\1/' || true)
[ -n "$LIVE_NUM" ] || { echo "FEHLER: Live-Stand nicht lesbar: $LIVE_JSON" >&2; exit 1; }
echo "Live: $LIVE_NAME  ->  neu: $VERSION"
if [ "$NUM" -le "$LIVE_NUM" ]; then
  echo "FEHLER: Build $NUM ist nicht hoeher als der Live-Stand $LIVE_NUM – nichts geaendert." >&2
  exit 1
fi

# index.html VORHER laden und pruefen: fehlt der Versionsstring, lieber gar
# nichts aendern als eine EXE ausliefern, deren Knopf die alte Nummer nennt.
# DRIFT-SICHER: die LIVE-Datei patchen, niemals die Repo-Kopie hochladen –
# docs/landing-page/index.html driftet (siehe CLAUDE.md).
TMPHTML=$(mktemp)
trap 'rm -f "$TMPHTML"' EXIT
"${SFTP[@]}" get index.html "$TMPHTML"
# Pattern: "Portable EXE · v0.XXX" (mit v-Präfix wie in der Landing Page)
if ! grep -q "Portable EXE · v[0-9]\+\.[0-9]\+" "$TMPHTML"; then
  echo "FEHLER: 'Portable EXE · v…' nicht in der Live-index.html – nichts hochgeladen." >&2; exit 1
fi

"${SFTP[@]}" sichern downloads/jarvis.exe "jarvis-${LIVE_NAME}.exe.bak"
"${SFTP[@]}" put jarvis.exe downloads/jarvis.exe
# sha256 der EXE (Code-Review 2026-10-18): der Client vergleicht ihn vor dem
# Einwechseln (update.go) – eine abgeschnittene oder ersetzte Datei faellt so auf.
EXE_SHA=$(sha256sum jarvis.exe | cut -d' ' -f1)
printf '%s' "{\"versionCode\":$NUM,\"versionName\":\"$VERSION\",\"downloadUrl\":\"$BASIS/downloads/jarvis.exe\",\"sha256\":\"$EXE_SHA\"}" \
  | "${SFTP[@]}" putstr downloads/version_windows.json
sed -i "s/Portable EXE · v[0-9]\+\.[0-9]\+/Portable EXE · v$VERSION/g" "$TMPHTML"
"${SFTP[@]}" put "$TMPHTML" index.html

# Gegenprobe ueber HTTPS: was AUSGELIEFERT wird, nicht was hochgeladen wurde
FEHLER=0
SOLL=$(md5sum < jarvis.exe | cut -c1-32)
IST=$(curl -sf "$BASIS/downloads/jarvis.exe?t=$(date +%s)" | md5sum | cut -c1-32)
[ "$SOLL" = "$IST" ] && echo "✓ jarvis.exe md5-gleich" || { echo "⚠ jarvis.exe: md5 $IST statt $SOLL" >&2; FEHLER=1; }
curl -sf "$BASIS/downloads/version_windows.json?t=$(date +%s)" | grep -q "\"versionCode\":$NUM" \
  && echo "✓ version_windows.json = $NUM" || { echo "⚠ version_windows.json nicht aktualisiert" >&2; FEHLER=1; }
curl -sf "$BASIS/?t=$(date +%s)" | grep -q "Portable EXE · v$VERSION" \
  && echo "✓ index.html nennt v$VERSION" || { echo "⚠ index.html nennt nicht v$VERSION" >&2; FEHLER=1; }
[ "$FEHLER" = 0 ] || exit 1
echo "Deploy $VERSION abgeschlossen."
