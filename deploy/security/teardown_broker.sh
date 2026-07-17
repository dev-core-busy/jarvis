#!/bin/bash
# Jarvis: Rueckweg vom getrennten Betrieb zum ALT-BETRIEB (Backend als root).
#
# Idempotent. Als root auf dem Jarvis-Server ausfuehren:
#   bash /opt/jarvis/deploy/security/teardown_broker.sh [JARVIS_DIR]
#
# Schritte:
#   1. Alt-Unit (repo-root jarvis.service, User=root) installieren
#   2. jarvis-broker.service deaktivieren/stoppen + Socket entfernen
#   3. jarvis.service neu starten und verifizieren (laeuft als root, HTTPS ok)
#
# Hinweis: Freigabeliste + Audit bleiben aktiv (broker_client hat einen
# root-Fallback) – es entfaellt nur die Prozess-Trennung.

set -u

JARVIS_DIR="${1:-/opt/jarvis}"
UNIT_DIR="/etc/systemd/system"

fail() { echo "❌ $*" >&2; exit 1; }
step() { echo ""; echo "── $*"; }

[ "$(id -u)" = "0" ] || fail "Bitte als root ausfuehren."
[ -d "$JARVIS_DIR" ] || fail "Verzeichnis $JARVIS_DIR fehlt."
[ -f "$JARVIS_DIR/jarvis.service" ] || fail "Alt-Unit fehlt: $JARVIS_DIR/jarvis.service"

step "1/3 Alt-Unit installieren (User=root)"
cp "$JARVIS_DIR/jarvis.service" "$UNIT_DIR/jarvis.service"
if [ "$JARVIS_DIR" != "/opt/jarvis" ]; then
    sed -i "s|/opt/jarvis|$JARVIS_DIR|g" "$UNIT_DIR/jarvis.service"
fi
chmod +x "$JARVIS_DIR/start_jarvis.sh" 2>/dev/null
systemctl daemon-reload
echo "   OK"

step "2/3 Root-Broker-Dienst deaktivieren"
systemctl disable --now jarvis-broker.service >/dev/null 2>&1
# Stale Socket entfernen – sonst meldet mode() weiterhin 'broker'
rm -f /run/jarvis-broker.sock
echo "   OK"

step "3/3 Backend als root neu starten + Verifikation"
systemctl restart jarvis.service
sleep 4
ok=1
MAIN_PID="$(systemctl show -p MainPID --value jarvis.service)"
if [ -n "$MAIN_PID" ] && [ "$MAIN_PID" != "0" ]; then
    RUN_USER="$(ps -o user= -p "$MAIN_PID" | tr -d ' ')"
    if [ "$RUN_USER" = "root" ]; then
        echo "   ✅ Backend laeuft als root (PID $MAIN_PID)"
    else
        echo "   ❌ Backend laeuft als '$RUN_USER' (erwartet: root)"; ok=0
    fi
else
    echo "   ❌ jarvis.service laeuft nicht – journalctl -u jarvis.service pruefen"; ok=0
fi
for _i in 1 2 3 4 5 6 7 8 9 10; do
    sleep 2
    if curl -sk -m 5 https://localhost/api/config >/dev/null 2>&1; then
        echo "   ✅ HTTPS (Port 443) erreichbar"
        break
    fi
    [ "$_i" = "10" ] && { echo "   ❌ HTTPS nicht erreichbar"; ok=0; }
done

echo ""
if [ "$ok" = "1" ]; then
    echo "✅ Alt-Betrieb wiederhergestellt (Backend als root, Broker-Dienst aus)."
else
    echo "⚠️  Rueckbau unvollstaendig – siehe Meldungen oben."
    exit 1
fi
