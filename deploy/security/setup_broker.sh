#!/bin/bash
# Jarvis: Migration auf getrennten Betrieb (unprivilegiertes Backend + Root-Broker)
#
# Idempotent. Als root auf dem Jarvis-Server ausfuehren:
#   bash /opt/jarvis/deploy/security/setup_broker.sh [JARVIS_DIR] [SERVICE_USER]
#
# Schritte:
#   1. Dienst-Benutzer pruefen (Standard: jarvis – der Desktop-Benutzer)
#   2. Eigentuemerschaft Projektverzeichnis(se) + data/ + certs/ auf den Benutzer
#   3. Gruppen fuer Kamera (video) und Log-Lesen (adm, systemd-journal)
#   4. systemd-Units installieren: jarvis-broker.service (root) +
#      jarvis.service (User=jarvis, CAP_NET_BIND_SERVICE)
#   5. Dienste aktivieren/neustarten und verifizieren (Broker-Socket, euid)
#
# Rueckweg (Alt-Betrieb): das alte jarvis.service (User=root) wieder
# installieren und jarvis-broker.service deaktivieren – der Code funktioniert
# in beiden Betriebsarten (Broker-Client hat einen root-Fallback).

set -u

JARVIS_DIR="${1:-/opt/jarvis}"
SVC_USER="${2:-jarvis}"
UNIT_DIR="/etc/systemd/system"

fail() { echo "❌ $*" >&2; exit 1; }
step() { echo ""; echo "── $*"; }

[ "$(id -u)" = "0" ] || fail "Bitte als root ausfuehren."
[ -d "$JARVIS_DIR" ] || fail "Verzeichnis $JARVIS_DIR fehlt."
[ -f "$JARVIS_DIR/backend/broker/daemon.py" ] || fail "Broker-Code fehlt in $JARVIS_DIR – erst Code deployen."
id "$SVC_USER" >/dev/null 2>&1 || fail "Benutzer $SVC_USER existiert nicht."

step "1/5 Eigentuemerschaft: $JARVIS_DIR (und /home/jarvis/jarvis, falls vorhanden) → $SVC_USER"
chown -R "$SVC_USER:$SVC_USER" "$JARVIS_DIR"
if [ -d "/home/jarvis/jarvis" ] && [ "/home/jarvis/jarvis" != "$JARVIS_DIR" ]; then
    chown -R "$SVC_USER:$SVC_USER" /home/jarvis/jarvis
fi
# Secrets bleiben eng (Eigentuemer darf, Gruppe/Andere nicht)
for f in "$JARVIS_DIR/.env" "$JARVIS_DIR/data/settings.json" "$JARVIS_DIR/certs/server.key"; do
    [ -f "$f" ] && chmod 600 "$f"
done
echo "   OK"

step "2/5 Gruppen fuer $SVC_USER (Kamera, Journal-Lesen)"
for grp in video adm systemd-journal; do
    getent group "$grp" >/dev/null && usermod -aG "$grp" "$SVC_USER" 2>/dev/null && echo "   + $grp"
done

step "3/5 systemd-Units installieren"
cp "$JARVIS_DIR/deploy/security/jarvis-broker.service" "$UNIT_DIR/jarvis-broker.service"
cp "$JARVIS_DIR/deploy/security/jarvis.service" "$UNIT_DIR/jarvis.service"
# Pfad/Benutzer anpassen, falls abweichend
if [ "$JARVIS_DIR" != "/opt/jarvis" ]; then
    sed -i "s|/opt/jarvis|$JARVIS_DIR|g" "$UNIT_DIR/jarvis-broker.service" "$UNIT_DIR/jarvis.service"
fi
if [ "$SVC_USER" != "jarvis" ]; then
    sed -i "s|^User=jarvis$|User=$SVC_USER|;s|^Group=jarvis$|Group=$SVC_USER|" "$UNIT_DIR/jarvis.service"
    sed -i "s|JARVIS_BROKER_GROUP=jarvis|JARVIS_BROKER_GROUP=$SVC_USER|" "$UNIT_DIR/jarvis-broker.service"
fi
chmod +x "$JARVIS_DIR/start_jarvis_root.sh" "$JARVIS_DIR/start_jarvis.sh"
systemctl daemon-reload
echo "   OK"

step "4/5 Dienste starten"
# Reihenfolge wichtig: erst jarvis.service neu starten (killt ein evtl. noch
# im alten root-Dienst laufendes x11vnc in dessen cgroup), DANN den Broker
# (neu) starten – sein Bootstrap sieht sonst das alte x11vnc und ueberspringt
# den VNC-Start.
systemctl enable jarvis-broker.service >/dev/null 2>&1
systemctl restart jarvis.service
systemctl enable jarvis.service >/dev/null 2>&1
sleep 2
systemctl restart jarvis-broker.service
sleep 4

step "5/5 Verifikation"
ok=1
if [ -S /run/jarvis-broker.sock ]; then
    echo "   ✅ Broker-Socket vorhanden: /run/jarvis-broker.sock ($(stat -c '%U:%G %a' /run/jarvis-broker.sock))"
else
    echo "   ❌ Broker-Socket fehlt – journalctl -u jarvis-broker.service pruefen"; ok=0
fi
MAIN_PID="$(systemctl show -p MainPID --value jarvis.service)"
if [ -n "$MAIN_PID" ] && [ "$MAIN_PID" != "0" ]; then
    RUN_USER="$(ps -o user= -p "$MAIN_PID" | tr -d ' ')"
    if [ "$RUN_USER" = "$SVC_USER" ]; then
        echo "   ✅ Backend laeuft unprivilegiert als '$RUN_USER' (PID $MAIN_PID)"
    else
        echo "   ❌ Backend laeuft als '$RUN_USER' (erwartet: $SVC_USER)"; ok=0
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
    echo "✅ Migration abgeschlossen: getrennter Betrieb aktiv."
    echo "   Root-Freigaben verwalten: Einstellungen → Sicherheit → Root-Freigaben"
else
    echo "⚠️  Migration unvollstaendig – siehe Meldungen oben."
    exit 1
fi
