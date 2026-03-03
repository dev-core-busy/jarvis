#!/bin/bash
# Jarvis Start-Skript (VNC & Xvfb Recovery Fix)

JARVIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$JARVIS_DIR"

# 1. Display-Erkennung (Priorität :0)
if [ -z "$DISPLAY" ] || [ "$DISPLAY" == ":10" ]; then
    if [ -S "/tmp/.X11-unix/X0" ]; then
        export DISPLAY=:0
        echo "Physisches Display :0 erkannt."
    else
        export DISPLAY=:10
        echo "Nutze virtuelles Display :10 (Xvfb)."
    fi
fi

# XAUTHORITY ermitteln (für :0)
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

    if ! pgrep -x "openbox" > /dev/null; then
        echo "Starte Openbox..."
        openbox --sm-disable &
        sleep 1
    fi

    if ! pgrep -x "xterm" > /dev/null; then
        echo "Starte Initial-Terminal..."
        xterm -geometry 80x24+10+10 -e "echo 'Jarvis Desktop bereit.'; bash" &
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

# 4. Starte websockify
pkill -f "websockify.*6080" || true
echo "Starte websockify (HTTPS)..."
/usr/bin/websockify --web=/usr/share/novnc --cert=./certs/server.crt --key=./certs/server.key 6080 localhost:5900 > /var/log/jarvis-websockify.log 2>&1 &
sleep 1

# 5. Starte das Backend
echo "Starte Backend (HTTPS)..."
exec ./venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --ssl-keyfile ./certs/server.key --ssl-certfile ./certs/server.crt
