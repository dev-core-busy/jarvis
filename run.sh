#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# Jarvis – Startskript
# ═══════════════════════════════════════════════════════════════════
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Farben
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${CYAN}"
echo "     ╔═══════════════════════════════╗"
echo "     ║        J A R V I S            ║"
echo "     ║    KI Linux Agent v1.0        ║"
echo "     ╚═══════════════════════════════╝"
echo -e "${NC}"

# ─── .env prüfen ─────────────────────────────────────────────────
if [ ! -f .env ]; then
    echo -e "${RED}❌ .env Datei fehlt!${NC}"
    echo "   Erstelle eine .env Datei mit mindestens GEMINI_API_KEY="
    exit 1
fi

# ─── Python Virtual Environment ─────────────────────────────────
if [ ! -d "venv" ]; then
    echo -e "${BLUE}📦 Erstelle virtuelle Python-Umgebung...${NC}"
    python3 -m venv venv
fi

echo -e "${BLUE}🔄 Aktiviere virtuelle Umgebung...${NC}"
source venv/bin/activate

# ─── Dependencies installieren ───────────────────────────────────
echo -e "${BLUE}📦 Installiere Python-Abhängigkeiten...${NC}"
pip install -q -r requirements.txt

# ─── Systemtools prüfen ──────────────────────────────────────────
echo -e "${BLUE}🔍 Prüfe Systemtools...${NC}"

if ! command -v xdotool &> /dev/null; then
    echo -e "${YELLOW}⚠️  xdotool nicht gefunden. Installiere...${NC}"
    sudo apt-get install -y xdotool 2>/dev/null || echo -e "${RED}   Bitte manuell installieren: sudo apt install xdotool${NC}"
fi

if ! command -v scrot &> /dev/null; then
    echo -e "${YELLOW}⚠️  scrot nicht gefunden. Installiere...${NC}"
    sudo apt-get install -y scrot 2>/dev/null || echo -e "${RED}   Bitte manuell installieren: sudo apt install scrot${NC}"
fi

# ─── VNC / Desktop-Vorschau ─────────────────────────────────────
source .env 2>/dev/null

VNC_PORT="${VNC_PORT:-5900}"
WEBSOCKIFY_PORT="${WEBSOCKIFY_PORT:-6080}"
SERVER_PORT="${SERVER_PORT:-443}"

# Display automatisch erkennen
XDISPLAY="${DISPLAY:-:0}"
echo -e "${BLUE}🖥️  Erkanntes Display: ${XDISPLAY}${NC}"

# x11vnc starten (falls nicht bereits aktiv)
if ! pgrep -x "x11vnc" > /dev/null 2>&1; then
    echo -e "${BLUE}🖥️  Starte x11vnc auf Port ${VNC_PORT} (Display ${XDISPLAY})...${NC}"
    x11vnc -display "$XDISPLAY" -auth guess -rfbport "$VNC_PORT" -shared -forever -nopw -bg -quiet 2>/dev/null || {
        # Fallback: versuche ohne -auth guess
        x11vnc -display "$XDISPLAY" -rfbport "$VNC_PORT" -shared -forever -nopw -bg -quiet 2>/dev/null || {
            echo -e "${YELLOW}⚠️  x11vnc konnte nicht gestartet werden.${NC}"
            echo -e "${YELLOW}   Tipp: Starte das Skript als der Benutzer, der am Desktop angemeldet ist.${NC}"
        }
    }
    # Kurz warten und prüfen ob x11vnc wirklich läuft
    sleep 1
    if pgrep -x "x11vnc" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ x11vnc gestartet${NC}"
    fi
else
    echo -e "${GREEN}✅ x11vnc läuft bereits${NC}"
fi

# noVNC-Pfad ermitteln
NOVNC_DIR=""
for dir in /usr/share/novnc /usr/share/noVNC /snap/novnc/current/usr/share/novnc; do
    if [ -d "$dir" ]; then
        NOVNC_DIR="$dir"
        break
    fi
done

# websockify starten (noVNC Bridge)
WEBSOCKIFY_PID=""
if ! pgrep -f "websockify.*${WEBSOCKIFY_PORT}" > /dev/null 2>&1; then
    if [ -n "$NOVNC_DIR" ]; then
        echo -e "${BLUE}🌐 Starte websockify (Port ${WEBSOCKIFY_PORT} → VNC ${VNC_PORT})...${NC}"
        echo -e "${BLUE}   noVNC Verzeichnis: ${NOVNC_DIR}${NC}"
        # System-websockify bevorzugen, dann venv-websockify
        if command -v /usr/bin/websockify &> /dev/null; then
            /usr/bin/websockify --web="$NOVNC_DIR" "$WEBSOCKIFY_PORT" "localhost:${VNC_PORT}" > /dev/null 2>&1 &
        else
            python -m websockify --web="$NOVNC_DIR" "$WEBSOCKIFY_PORT" "localhost:${VNC_PORT}" > /dev/null 2>&1 &
        fi
        WEBSOCKIFY_PID=$!
        sleep 1
        if kill -0 "$WEBSOCKIFY_PID" 2>/dev/null; then
            echo -e "${GREEN}✅ websockify gestartet (PID: $WEBSOCKIFY_PID)${NC}"
        else
            echo -e "${YELLOW}⚠️  websockify konnte nicht gestartet werden.${NC}"
            WEBSOCKIFY_PID=""
        fi
    else
        echo -e "${YELLOW}⚠️  noVNC nicht gefunden. Desktop-Vorschau deaktiviert.${NC}"
        echo -e "${YELLOW}   Installiere mit: sudo apt install novnc${NC}"
    fi
else
    echo -e "${GREEN}✅ websockify läuft bereits${NC}"
fi

# ─── Skills-Verzeichnis erstellen ────────────────────────────────
mkdir -p skills

# ─── Cleanup bei Beendigung ──────────────────────────────────────
cleanup() {
    echo -e "\n${RED}⏹  Jarvis wird beendet...${NC}"
    [ -n "$WEBSOCKIFY_PID" ] && kill "$WEBSOCKIFY_PID" 2>/dev/null
    # x11vnc ebenfalls beenden
    pkill -f "x11vnc.*${VNC_PORT}" 2>/dev/null
    exit 0
}
trap cleanup INT TERM

# ─── Jarvis Backend starten ─────────────────────────────────────
echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════${NC}"
echo -e "${GREEN}🚀 Jarvis wird gestartet...${NC}"
PORT_SUFFIX=""; [ "$SERVER_PORT" != "443" ] && PORT_SUFFIX=":${SERVER_PORT}"
echo -e "${GREEN}🌐 Öffne im Browser: ${CYAN}https://$(hostname -I | awk '{print $1}')${PORT_SUFFIX}${NC}"
echo -e "${GREEN}🔑 Standard-Passwort: jarvis${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════${NC}"
echo ""

python -m uvicorn backend.main:app --host 0.0.0.0 --port "$SERVER_PORT" --ssl-keyfile ./certs/server.key --ssl-certfile ./certs/server.crt --reload
