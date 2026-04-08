#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# Jarvis Docker Entrypoint
# Startet: Xvfb → Desktop (Cinnamon oder Openbox) → x11vnc → noVNC → Jarvis
# ──────────────────────────────────────────────────────────────────────────────
set -e

DISPLAY_NUM=":1"
VNC_PORT=5900
NOVNC_PORT=6080
JARVIS_PORT=443
CERT_DIR="/app/certs"

log() { echo "[Jarvis] $*"; }

# ── Container-Shutdown-Befehle bereitstellen ────────────────────────────────
for cmd in shutdown poweroff halt; do
    printf '#!/bin/sh\necho "[Jarvis] Container wird beendet..."\nkill -SIGTERM 1\n' > "/usr/local/bin/$cmd"
    chmod +x "/usr/local/bin/$cmd"
done
printf '#!/bin/sh\necho "[Jarvis] Container wird neugestartet..."\nkill -SIGTERM 1\n' > /usr/local/bin/reboot
chmod +x /usr/local/bin/reboot


# ── 1. SSL-Zertifikat ──────────────────────────────────────────────────────
if [[ ! -f "$CERT_DIR/server.crt" ]]; then
    log "Erstelle selbstsigniertes SSL-Zertifikat..."
    cd /app
    /venv/bin/python -c "from backend.security import ensure_certificates; ensure_certificates()"
    log "SSL-Zertifikat erstellt."
fi

# ── 2. Xvfb (virtueller Framebuffer) ───────────────────────────────────────
rm -f /tmp/.X1-lock /tmp/.X11-unix/X1 2>/dev/null || true

log "Starte Xvfb auf $DISPLAY_NUM..."
Xvfb "$DISPLAY_NUM" -screen 0 1280x800x24 -ac +extension GLX +render -noreset &
XVFB_PID=$!
sleep 1

if ! kill -0 "$XVFB_PID" 2>/dev/null; then
    log "FEHLER: Xvfb konnte nicht gestartet werden – zweiter Versuch..."
    rm -f /tmp/.X1-lock /tmp/.X11-unix/X1 2>/dev/null || true
    Xvfb "$DISPLAY_NUM" -screen 0 1280x800x24 -ac +extension GLX +render -noreset &
    XVFB_PID=$!
    sleep 1
fi

export DISPLAY="$DISPLAY_NUM"
export HOME="/root"

# ── 3. D-Bus + Desktop ─────────────────────────────────────────────────────
log "Starte D-Bus..."
eval "$(dbus-launch --sh-syntax)" || true
export DBUS_SESSION_BUS_ADDRESS

# Wallpaper setzen
if command -v cinnamon-session &>/dev/null; then
    # ── Cinnamon Desktop (vollwertig, nach Upgrade) ──
    log "Starte Cinnamon Desktop..."
    mkdir -p /root/.config/cinnamon
    dconf write /org/cinnamon/desktop/background/picture-uri "'file:///usr/share/backgrounds/jarvis.jpg'" 2>/dev/null || true
    gsettings set org.cinnamon.desktop.background picture-uri "file:///usr/share/backgrounds/jarvis.jpg" 2>/dev/null || true
    XDG_SESSION_TYPE=x11 cinnamon-session &
    sleep 3
else
    # ── Openbox (leichtgewichtig, Standard im Docker-Image) ──
    log "Starte Openbox Desktop (Cinnamon nicht installiert)..."
    mkdir -p /root/.config/openbox

    # Openbox Konfiguration: Rechtsklick-Menue, Keybindings
    cat > /root/.config/openbox/rc.xml << 'OBXML'
<?xml version="1.0" encoding="UTF-8"?>
<openbox_config xmlns="http://openbox.org/3.4/rc">
  <theme><name>Clearlooks</name></theme>
  <desktops><number>1</number></desktops>
  <keyboard>
    <keybind key="A-F4"><action name="Close"/></keybind>
    <keybind key="A-Tab"><action name="NextWindow"/></keybind>
  </keyboard>
  <mouse>
    <context name="Root">
      <mousebind button="Right" action="Press">
        <action name="ShowMenu"><menu>root-menu</menu></action>
      </mousebind>
    </context>
  </mouse>
  <menu>
    <file>menu.xml</file>
  </menu>
</openbox_config>
OBXML

    cat > /root/.config/openbox/menu.xml << 'OBMENU'
<?xml version="1.0" encoding="UTF-8"?>
<openbox_menu xmlns="http://openbox.org/3.4/menu">
  <menu id="root-menu" label="Jarvis">
    <item label="Terminal"><action name="Execute"><execute>xterm</execute></action></item>
    <item label="Chromium"><action name="Execute"><execute>chromium --no-sandbox</execute></action></item>
    <separator/>
    <item label="Cinnamon installieren"><action name="Execute"><execute>xterm -e /usr/local/bin/install-cinnamon.sh</execute></action></item>
  </menu>
</openbox_menu>
OBMENU

    openbox-session &
    sleep 1

    # Wallpaper mit feh setzen
    if [[ -f /usr/share/backgrounds/jarvis.jpg ]]; then
        feh --bg-fill /usr/share/backgrounds/jarvis.jpg 2>/dev/null || true
    fi
fi

# ── 4. x11vnc ──────────────────────────────────────────────────────────────
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

# ── 5. websockify / noVNC ────────────────────────────────────────────────
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

# ── 6. WhatsApp-Bridge (Node.js + Baileys) ─────────────────────────────────
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
    log "HINWEIS: WhatsApp-Bridge nicht gefunden oder Node.js fehlt."
fi

# ── 7. Jarvis FastAPI ──────────────────────────────────────────────────────
log "Starte Jarvis auf Port $JARVIS_PORT (HTTPS)..."
cd /app
exec /venv/bin/uvicorn backend.main:app \
    --host 0.0.0.0 \
    --port "$JARVIS_PORT" \
    --ssl-keyfile  "$CERT_DIR/server.key" \
    --ssl-certfile "$CERT_DIR/server.crt" \
    --workers 1
