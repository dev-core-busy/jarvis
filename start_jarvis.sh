#!/bin/bash
# Jarvis Start-Skript (VNC & Xvfb Recovery Fix)
#
# Zwei Betriebsarten:
# - GETRENNT (empfohlen): jarvis.service laeuft mit User=jarvis. Die root-
#   pflichtigen Startaufgaben (iptables, dconf, Xvfb/x11vnc, websockify) macht
#   start_jarvis_root.sh (jarvis-broker.service). Dieses Skript ueberspringt
#   sie dann und startet nur das Backend.
# - ALT (root): laeuft dieses Skript als root (nicht migrierte Installation),
#   fuehrt es wie bisher ALLE Schritte selbst aus.

JARVIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$JARVIS_DIR"

IS_ROOT=0
[ "$(id -u)" = "0" ] && IS_ROOT=1

# 1. Display-Erkennung (Priorität: LightDM :1, dann :0, dann :10)
# Beim Boot startet lightdm PARALLEL zu diesem Dienst. Ohne Warten landet x11vnc
# dauerhaft auf dem leeren Xvfb :10 (-> schwarzer VNC-Bildschirm), obwohl der
# echte Desktop Sekunden spaeter da ist. Daher: bis zu 60s auf :0/:1 warten,
# solange ein Display-Manager aktiviert ist.
if [ -z "$DISPLAY" ] || [ "$DISPLAY" == ":10" ]; then
    if systemctl is-enabled lightdm >/dev/null 2>&1; then
        for _i in $(seq 1 30); do
            [ -S "/tmp/.X11-unix/X0" ] || [ -S "/tmp/.X11-unix/X1" ] && break
            echo "Warte auf Display-Manager (:0/:1)... ($_i/30)"
            sleep 2
        done
    fi
    if [ -f "/var/run/lightdm/root/:1" ] && [ -S "/tmp/.X11-unix/X1" ]; then
        export DISPLAY=:1
        export XAUTHORITY="/var/run/lightdm/root/:1"
        echo "LightDM-Display :1 erkannt."
    elif [ -S "/tmp/.X11-unix/X0" ]; then
        export DISPLAY=:0
        echo "Physisches Display :0 erkannt."
    else
        export DISPLAY=:10
        echo "Nutze virtuelles Display :10 (Xvfb)."
    fi
fi

# XAUTHORITY ermitteln (für :0, bei :1 bereits oben gesetzt)
if [ "$DISPLAY" == ":0" ] && [ -z "$XAUTHORITY" ]; then
    if [ "$IS_ROOT" = "1" ] && [ -f "/var/run/lightdm/root/:0" ]; then
        export XAUTHORITY="/var/run/lightdm/root/:0"
    elif [ -f "$HOME/.Xauthority" ]; then
        # Unprivilegiert: eigene Xauthority des Dienst-Benutzers (Desktop-User jarvis)
        export XAUTHORITY="$HOME/.Xauthority"
    else
        for home_dir in /home/*; do
            if [ -f "$home_dir/.Xauthority" ]; then
                export XAUTHORITY="$home_dir/.Xauthority"
                break
            fi
        done
    fi
fi

echo "Nutze DISPLAY=$DISPLAY mit XAUTHORITY=$XAUTHORITY"

if [ "$IS_ROOT" = "1" ]; then
# ── Root-Startaufgaben (nur Alt-Betrieb; getrennt: start_jarvis_root.sh) ──

# Jarvis-Ports vor Tailscale ts-input-DROP freischalten (443, 80, 6080)
# Nur mit iptables – Begruendung siehe start_jarvis_root.sh (nft-only-Systeme).
if command -v iptables >/dev/null 2>&1; then
    for PORT in 443 80 6080; do
        iptables -C INPUT -p tcp --dport $PORT -j ACCEPT 2>/dev/null || \
            iptables -I INPUT 1 -p tcp --dport $PORT -j ACCEPT
    done
fi

# Screensaver und DPMS deaktivieren (verhindert schwarzen Bildschirm bei VNC)
xset s off -dpms 2>/dev/null || true
pkill -f cinnamon-screensaver 2>/dev/null || true
# gsettings als root wirkt NICHT auf die jarvis-Session (falsches dconf-Profil).
# Stattdessen systemweite dconf-Defaults: Sperre/Screensaver fuer ALLE Benutzer aus.
if command -v dconf >/dev/null 2>&1; then
    mkdir -p /etc/dconf/profile /etc/dconf/db/local.d
    grep -q "^system-db:local" /etc/dconf/profile/user 2>/dev/null || \
        printf "user-db:user\nsystem-db:local\n" > /etc/dconf/profile/user
    cat > /etc/dconf/db/local.d/00-jarvis-nolock <<'DCONF'
[org/cinnamon/desktop/screensaver]
lock-enabled=false
idle-activation-enabled=false
[org/cinnamon/desktop/session]
idle-delay=uint32 0
DCONF
    dconf update 2>/dev/null || true
fi

fi  # IS_ROOT (Teil 1)

# 0. Bereinigung alter Locks
if [ "$IS_ROOT" = "1" ] && [ "$DISPLAY" == ":10" ]; then
    rm -f /tmp/.X10-lock
    rm -rf /tmp/.X11-unix/X10
fi

# 1. Starte Xvfb nur falls :10 genutzt wird und nicht aktiv ist (nur Alt-Betrieb)
if [ "$IS_ROOT" = "1" ] && [ "$DISPLAY" == ":10" ]; then
    if ! pgrep -x "Xvfb" > /dev/null; then
        echo "Starte Xvfb auf :10..."
        Xvfb :10 -screen 0 1280x800x24 &
        sleep 2
    fi

    if ! pgrep -f "cinnamon-session" > /dev/null; then
        echo "Starte Cinnamon Desktop..."
        # dbus-Session fuer Cinnamon
        if [ -z "$DBUS_SESSION_BUS_ADDRESS" ]; then
            eval $(dbus-launch --sh-syntax)
            export DBUS_SESSION_BUS_ADDRESS
        fi
        XDG_SESSION_TYPE=x11 cinnamon-session &
        sleep 3
    fi
fi

# 2. Zertifikate sicherstellen (optional)
if [ -f "backend/security.py" ]; then
    ./venv/bin/python -c "from backend.security import ensure_certificates; ensure_certificates()" 2>/dev/null || true
fi

# Selbstheilung: Laeuft x11vnc (nur) auf dem leeren Xvfb :10, obwohl lightdm
# aktiviert ist, zieht dieser Hintergrund-Watcher auf das echte :0 um, sobald
# dessen X-Socket verfuegbar ist (heilt Boot-Races und lightdm-Neustarts ohne
# Service-Restart; bis ~10 Minuten).
_vnc_upgrade_watcher() {
    systemctl is-enabled lightdm >/dev/null 2>&1 || return 0
    (
        for _i in $(seq 1 150); do
            sleep 4
            [ -S "/tmp/.X11-unix/X0" ] || continue
            pkill -x x11vnc 2>/dev/null; sleep 1
            x11vnc -localhost -display :0 -auth guess -shared -forever -nopw -bg -quiet -rfbport 5900
            sleep 2
            if pgrep -x x11vnc >/dev/null; then
                pkill -x Xvfb 2>/dev/null   # leeres Fallback-Display aufraeumen
                echo "[VNC-Watcher] x11vnc auf :0 umgezogen."
                exit 0
            fi
            # :0 noch nicht bereit -> zurueck auf :10, weiter warten
            x11vnc -localhost -display :10 -rfbport 5900 -shared -forever -nopw -bg -quiet
        done
    ) &
    disown 2>/dev/null || true
}

# 3. Starte x11vnc (nur Alt-Betrieb; getrennt uebernimmt start_jarvis_root.sh)
if [ "$IS_ROOT" = "1" ] && ! pgrep -x "x11vnc" > /dev/null; then
    echo "Starte x11vnc für $DISPLAY..."

    if [ "$DISPLAY" == ":0" ]; then
        x11vnc -localhost -display :0 -auth guess -shared -forever -nopw -bg -quiet -rfbport 5900
    elif [ -n "$XAUTHORITY" ]; then
        x11vnc -localhost -display "$DISPLAY" -auth "$XAUTHORITY" -shared -forever -nopw -bg -quiet -rfbport 5900
    else
        x11vnc -localhost -display "$DISPLAY" -rfbport 5900 -shared -forever -nopw -bg -quiet
    fi

    sleep 3

    if ! pgrep -x "x11vnc" > /dev/null && [ "$DISPLAY" == ":0" ]; then
        echo "x11vnc konnte :0 nicht binden. Fallback auf :10..."
        export DISPLAY=:10
        Xvfb :10 -screen 0 1280x800x24 &
        sleep 2
        openbox --sm-disable &
        x11vnc -localhost -display :10 -rfbport 5900 -shared -forever -nopw -bg -quiet
        _vnc_upgrade_watcher
    elif [ "$DISPLAY" == ":10" ]; then
        # von vornherein auf Xvfb gelandet -> ebenfalls auf :0 lauern
        _vnc_upgrade_watcher
    fi
fi

# 4. Websockify ist nicht mehr nötig – VNC läuft über FastAPI WebSocket-Proxy (/ws/vnc)
# noVNC-Dateien werden über FastAPI /novnc/ serviert (Same-Origin, kein separates SSL)
echo "VNC-Proxy läuft über FastAPI (Port 443, /ws/vnc)"

# Legacy-websockify als optionaler Fallback (ohne SSL, nur localhost; nur Alt-Betrieb)
if [ "$IS_ROOT" = "1" ]; then
pkill -f "websockify.*6080" 2>/dev/null || true
NOVNC_DIR=""
for dir in /usr/share/novnc /usr/share/noVNC /snap/novnc/current/usr/share/novnc; do
    [ -d "$dir" ] && NOVNC_DIR="$dir" && break
done

if [ -n "$NOVNC_DIR" ]; then
    WSOCK_CMD=""
    if command -v /usr/bin/websockify &>/dev/null; then
        WSOCK_CMD="/usr/bin/websockify"
    elif command -v websockify &>/dev/null; then
        WSOCK_CMD="$(command -v websockify)"
    fi

    if [ -n "$WSOCK_CMD" ]; then
        "$WSOCK_CMD" --web="$NOVNC_DIR" 6080 localhost:5900 > /var/log/jarvis-websockify.log 2>&1 &
    else
        ./venv/bin/python -m websockify --web="$NOVNC_DIR" 6080 localhost:5900 > /var/log/jarvis-websockify.log 2>&1 &
    fi
    WSOCK_PID=$!
    sleep 1
    if kill -0 "$WSOCK_PID" 2>/dev/null; then
        echo "websockify Fallback gestartet (PID: $WSOCK_PID, Port 6080, kein SSL)"
    else
        echo "⚠ websockify konnte nicht gestartet werden – prüfe /var/log/jarvis-websockify.log"
    fi
fi
fi  # IS_ROOT (Teil 2)

# 5. Starte das Backend
#
# --ws-max-size: uvicorn deckelt eine WebSocket-Nachricht per Vorgabe auf 16 MB.
# Chat-Anhaenge kommen ueber genau diesen Weg und base64-kodiert an (Faktor 4/3),
# ein 50-MB-Anhang braucht also ~67 MB. Ohne diesen Wert bricht die VERBINDUNG ab,
# bevor der Server die Datei sieht - ohne Meldung an den Benutzer. Die Zahl muss
# ueber _ATTACH_MAX_BYTES in backend/main.py liegen.
# --timeout-graceful-shutdown: OHNE diesen Wert wartet uvicorn beim Beenden
# darauf, dass offene Verbindungen von selbst schliessen – und jeder geoeffnete
# Browser-Tab (Portal, Chat, /settings, VNC) haelt einen WebSocket offen.
# Gemessen auf DEV am 2026-08-05: Stop OHNE offene Verbindung 0,4 s, mit EINER
# offenen WS-Verbindung 16,1 s. Weil systemd dem Dienst nur TimeoutStopSec Zeit
# laesst, wurde er in 28 von 154 Stops per SIGKILL abgeraeumt – und damit BEVOR
# der Shutdown-Hook lief (Anwesenheits-Buchhaltung, Sicherung der Lernnotizen
# aus dem Journal). Im Journal stand dann "Failed with result 'timeout'", was
# nach einem Dienstfehler aussieht und echte Fehler verdeckt.
# Der Wert muss kleiner bleiben als TimeoutStopSec in der Unit (30 s), damit
# nach dem Verbindungs-Teardown noch Zeit fuer die Shutdown-Hooks bleibt.
# 5 s und nicht mehr: laenger zu warten bringt NICHTS, weil ein laufender
# Agent-Auftrag mit dem Prozess ohnehin endet – Aufträge dauern Minuten, nicht
# Sekunden. Ein groesserer Wert verlaengert nur jeden Deploy-Neustart.
echo "Starte Backend (HTTPS)..."
exec ./venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 443 \
    --ssl-keyfile ./certs/server.key --ssl-certfile ./certs/server.crt \
    --timeout-graceful-shutdown 5 \
    --ws-max-size 100000000
