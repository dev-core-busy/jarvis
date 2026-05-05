#!/bin/bash
# Jarvis Start-Skript (VNC & Xvfb Recovery Fix)

JARVIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$JARVIS_DIR"

# 1. Display-Erkennung (Priorität: LightDM :1, dann :0, dann :10)
if [ -z "$DISPLAY" ] || [ "$DISPLAY" == ":10" ]; then
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
    if [ -f "/var/run/lightdm/root/:0" ]; then
        export XAUTHORITY="/var/run/lightdm/root/:0"
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

# Jarvis-Ports vor Tailscale ts-input-DROP freischalten (443, 80, 6080)
for PORT in 443 80 6080; do
    iptables -C INPUT -p tcp --dport $PORT -j ACCEPT 2>/dev/null || \
        iptables -I INPUT 1 -p tcp --dport $PORT -j ACCEPT
done

# Screensaver und DPMS deaktivieren (verhindert schwarzen Bildschirm bei VNC)
xset s off -dpms 2>/dev/null || true
pkill -f cinnamon-screensaver 2>/dev/null || true
gsettings set org.cinnamon.desktop.screensaver idle-activation-enabled false 2>/dev/null || true
gsettings set org.cinnamon.desktop.screensaver lock-enabled false 2>/dev/null || true

# 0. Bereinigung alter Locks
if [ "$DISPLAY" == ":10" ]; then
    rm -f /tmp/.X10-lock
    rm -rf /tmp/.X11-unix/X10
fi

# 1. Starte Xvfb nur falls :10 genutzt wird und nicht aktiv ist
if [ "$DISPLAY" == ":10" ]; then
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

# 3. Starte x11vnc
if ! pgrep -x "x11vnc" > /dev/null; then
    echo "Starte x11vnc für $DISPLAY..."

    if [ "$DISPLAY" == ":0" ]; then
        x11vnc -display :0 -auth guess -shared -forever -nopw -bg -quiet -rfbport 5900
    elif [ -n "$XAUTHORITY" ]; then
        x11vnc -display "$DISPLAY" -auth "$XAUTHORITY" -shared -forever -nopw -bg -quiet -rfbport 5900
    else
        x11vnc -display "$DISPLAY" -rfbport 5900 -shared -forever -nopw -bg -quiet
    fi

    sleep 3

    if ! pgrep -x "x11vnc" > /dev/null && [ "$DISPLAY" == ":0" ]; then
        echo "x11vnc konnte :0 nicht binden. Fallback auf :10..."
        export DISPLAY=:10
        Xvfb :10 -screen 0 1280x800x24 &
        sleep 2
        openbox --sm-disable &
        x11vnc -display :10 -rfbport 5900 -shared -forever -nopw -bg -quiet
    fi
fi

# 4. Websockify ist nicht mehr nötig – VNC läuft über FastAPI WebSocket-Proxy (/ws/vnc)
# noVNC-Dateien werden über FastAPI /novnc/ serviert (Same-Origin, kein separates SSL)
pkill -f "websockify.*6080" 2>/dev/null || true
echo "VNC-Proxy läuft über FastAPI (Port 443, /ws/vnc)"

# Legacy-websockify als optionaler Fallback (ohne SSL, nur localhost)
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

# 5. Starte das Backend
echo "Starte Backend (HTTPS)..."
exec ./venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 443 --ssl-keyfile ./certs/server.key --ssl-certfile ./certs/server.crt
