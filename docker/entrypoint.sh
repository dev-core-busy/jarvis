#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# Jarvis Docker Entrypoint
# Startet: Xvfb → Cinnamon → x11vnc → websockify/noVNC → Jarvis FastAPI
# ──────────────────────────────────────────────────────────────────────────────
set -e

DISPLAY_NUM=":1"
VNC_PORT=5900
NOVNC_PORT=6080
JARVIS_PORT=443
CERT_DIR="/app/certs"

log() { echo "[Jarvis] $*"; }

# ── Container-Shutdown-Befehle bereitstellen ──────────────────────────────────
# Leitet shutdown/poweroff/halt an kill -SIGTERM 1 weiter → stoppt den Container
for cmd in shutdown poweroff halt; do
    printf '#!/bin/sh\necho "[Jarvis] Container wird beendet..."\nkill -SIGTERM 1\n' > "/usr/local/bin/$cmd"
    chmod +x "/usr/local/bin/$cmd"
done
printf '#!/bin/sh\necho "[Jarvis] Container wird neugestartet..."\nkill -SIGTERM 1\n' > /usr/local/bin/reboot
chmod +x /usr/local/bin/reboot


# ── 1. SSL-Zertifikat (via security.py – inkl. SAN für Windows) ──────────────
if [[ ! -f "$CERT_DIR/server.crt" ]]; then
    log "Erstelle selbstsigniertes SSL-Zertifikat..."
    cd /app
    /venv/bin/python -c "from backend.security import ensure_certificates; ensure_certificates()"
    log "SSL-Zertifikat erstellt."
fi

# ── 2. Xvfb (virtueller Framebuffer) ─────────────────────────────────────────
# Stale Lock-Dateien von vorherigem Container-Run entfernen
rm -f /tmp/.X1-lock /tmp/.X11-unix/X1 2>/dev/null || true

log "Starte Xvfb auf $DISPLAY_NUM..."
Xvfb "$DISPLAY_NUM" -screen 0 1280x800x24 -ac +extension GLX +render -noreset &
XVFB_PID=$!
sleep 1

# Pruefen ob Xvfb laeuft
if ! kill -0 "$XVFB_PID" 2>/dev/null; then
    log "FEHLER: Xvfb konnte nicht gestartet werden – zweiter Versuch..."
    rm -f /tmp/.X1-lock /tmp/.X11-unix/X1 2>/dev/null || true
    Xvfb "$DISPLAY_NUM" -screen 0 1280x800x24 -ac +extension GLX +render -noreset &
    XVFB_PID=$!
    sleep 1
fi

export DISPLAY="$DISPLAY_NUM"
export HOME="/root"

# ── 3. D-Bus + Cinnamon Desktop ──────────────────────────────────────────────
log "Starte D-Bus..."
eval "$(dbus-launch --sh-syntax)" || true
export DBUS_SESSION_BUS_ADDRESS

# Wallpaper fuer Cinnamon konfigurieren
mkdir -p /root/.config/cinnamon
dconf write /org/cinnamon/desktop/background/picture-uri "'file:///usr/share/backgrounds/jarvis.jpg'" 2>/dev/null || true
gsettings set org.cinnamon.desktop.background picture-uri "file:///usr/share/backgrounds/jarvis.jpg" 2>/dev/null || true

log "Starte Cinnamon Desktop..."
XDG_SESSION_TYPE=x11 cinnamon-session &
sleep 3

# ── 4. x11vnc ─────────────────────────────────────────────────────────────────
log "Starte x11vnc auf Port $VNC_PORT..."
x11vnc -display "$DISPLAY_NUM" \
    -nopw \
    -listen 0.0.0.0 \
    -rfbport "$VNC_PORT" \
    -forever \
    -shared \
    -bg \
    -noxdamage \
    -logfile /dev/null || true

sleep 1

# ── 5. websockify / noVNC ───────────────────────────────────────────────────
NOVNC_DIR=""
for d in /usr/share/novnc /usr/share/novnc/utils /usr/local/share/novnc; do
    [[ -d "$d" ]] && NOVNC_DIR="$d" && break
done

if [[ -n "$NOVNC_DIR" ]]; then
    log "Starte websockify/noVNC auf Port $NOVNC_PORT → VNC $VNC_PORT..."
    websockify --web="$NOVNC_DIR" \
        --ssl-only \
        --cert="$CERT_DIR/server.crt" \
        --key="$CERT_DIR/server.key" \
        "$NOVNC_PORT" \
        "localhost:$VNC_PORT" &
else
    log "WARNUNG: noVNC nicht gefunden – VNC-Streaming deaktiviert."
fi

# ── 6. WhatsApp-Bridge (Node.js + Baileys) ──────────────────────────────────
WA_BRIDGE_DIR="/app/services/whatsapp-bridge"
if [[ -f "$WA_BRIDGE_DIR/index.js" ]] && command -v node &>/dev/null; then
    log "Starte WhatsApp-Bridge auf Port 3001..."
    cd "$WA_BRIDGE_DIR"
    export JARVIS_WEBHOOK="https://localhost/api/whatsapp/incoming"
    export NODE_TLS_REJECT_UNAUTHORIZED=0
    node index.js &
    WA_PID=$!
    sleep 1
    log "WhatsApp-Bridge gestartet (PID $WA_PID)."
else
    log "HINWEIS: WhatsApp-Bridge nicht gefunden oder Node.js fehlt – übersprungen."
fi

# ── 7. Jarvis FastAPI ───────────────────────────────────────────────────────
log "Starte Jarvis auf Port $JARVIS_PORT (HTTPS)..."
cd /app
exec /venv/bin/uvicorn backend.main:app \
    --host 0.0.0.0 \
    --port "$JARVIS_PORT" \
    --ssl-keyfile  "$CERT_DIR/server.key" \
    --ssl-certfile "$CERT_DIR/server.crt" \
    --workers 1
