#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# Jarvis Docker Entrypoint
# Startet: Xvfb → Openbox → x11vnc → websockify/noVNC → Jarvis FastAPI
# ──────────────────────────────────────────────────────────────────────────────
set -e

DISPLAY_NUM=":1"
VNC_PORT=5900
NOVNC_PORT=6080
JARVIS_PORT=8000
CERT_DIR="/app/certs"

log() { echo "[Jarvis] $*"; }

# ── 1. SSL-Zertifikat ─────────────────────────────────────────────────────────
# security.py erwartet: server.crt, server.key, jarvis.cer
if [[ ! -f "$CERT_DIR/server.crt" ]]; then
    log "Erstelle selbstsigniertes SSL-Zertifikat..."
    openssl req -x509 -newkey rsa:2048 -nodes \
        -keyout "$CERT_DIR/server.key" \
        -out    "$CERT_DIR/server.crt" \
        -days 3650 \
        -subj "/C=DE/ST=Berlin/L=Berlin/O=Jarvis/CN=jarvis"
    # DER-Format für Windows-Download
    openssl x509 -in "$CERT_DIR/server.crt" -outform DER -out "$CERT_DIR/jarvis.cer"
    log "SSL-Zertifikat erstellt."
fi

# ── 2. Xvfb (virtueller Framebuffer) ─────────────────────────────────────────
log "Starte Xvfb auf $DISPLAY_NUM..."
Xvfb "$DISPLAY_NUM" -screen 0 1280x800x24 -ac +extension GLX +render -noreset &
XVFB_PID=$!
sleep 1

export DISPLAY="$DISPLAY_NUM"

# ── 3. Openbox Fenstermanager ─────────────────────────────────────────────────
log "Starte Openbox..."
openbox &
sleep 1

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

# ── 5. websockify / noVNC ─────────────────────────────────────────────────────
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

# ── 6. Jarvis FastAPI ─────────────────────────────────────────────────────────
log "Starte Jarvis auf Port $JARVIS_PORT (HTTPS)..."
cd /app
exec /venv/bin/uvicorn backend.main:app \
    --host 0.0.0.0 \
    --port "$JARVIS_PORT" \
    --ssl-keyfile  "$CERT_DIR/server.key" \
    --ssl-certfile "$CERT_DIR/server.crt" \
    --workers 1
