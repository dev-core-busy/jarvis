#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# Jarvis Docker Entrypoint
# Startet: Xvfb → XFCE4 → x11vnc → websockify/noVNC → Jarvis FastAPI
# ──────────────────────────────────────────────────────────────────────────────
set -e

DISPLAY_NUM=":1"
VNC_PORT=5900
NOVNC_PORT=6080
JARVIS_PORT=8000
CERT_DIR="/app/certs"

log() { echo "[Jarvis] $*"; }

# ── 1. SSL-Zertifikat (via security.py – inkl. SAN für Windows) ──────────────
if [[ ! -f "$CERT_DIR/server.crt" ]]; then
    log "Erstelle selbstsigniertes SSL-Zertifikat..."
    cd /app
    /venv/bin/python -c "from backend.security import ensure_certificates; ensure_certificates()"
    log "SSL-Zertifikat erstellt."
fi

# ── 2. Xvfb (virtueller Framebuffer) ─────────────────────────────────────────
log "Starte Xvfb auf $DISPLAY_NUM..."
Xvfb "$DISPLAY_NUM" -screen 0 1280x800x24 -ac +extension GLX +render -noreset &
XVFB_PID=$!
sleep 1

export DISPLAY="$DISPLAY_NUM"
export HOME="/root"

# ── 3. D-Bus + XFCE4 Desktop ────────────────────────────────────────────────
log "Starte D-Bus..."
eval "$(dbus-launch --sh-syntax)" || true
export DBUS_SESSION_BUS_ADDRESS

# XFCE4 Wallpaper konfigurieren
mkdir -p /root/.config/xfce4/xfconf/xfce-perchannel-xml
cat > /root/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml << 'XFCEEOF'
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-desktop" version="1.0">
  <property name="backdrop" type="empty">
    <property name="screen0" type="empty">
      <property name="monitorscreen" type="empty">
        <property name="workspace0" type="empty">
          <property name="last-image" type="string" value="/usr/share/backgrounds/jarvis.jpg"/>
          <property name="image-style" type="int" value="5"/>
        </property>
      </property>
      <property name="monitorVNC-0" type="empty">
        <property name="workspace0" type="empty">
          <property name="last-image" type="string" value="/usr/share/backgrounds/jarvis.jpg"/>
          <property name="image-style" type="int" value="5"/>
        </property>
      </property>
    </property>
  </property>
</channel>
XFCEEOF

log "Starte XFCE4 Desktop..."
startxfce4 &
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
