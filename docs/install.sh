#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Jarvis AI Desktop Agent – Installer
# Copyright (C) 2026 Andreas Bender · AGPL-3.0
# https://jarvis-ai.info  |  https://github.com/dev-core-busy/jarvis
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Farben ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[Jarvis]${RESET} $*"; }
success() { echo -e "${GREEN}[✓]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[!]${RESET} $*"; }
error()   { echo -e "${RED}[✗]${RESET} $*"; exit 1; }
step()    { echo -e "\n${BOLD}${CYAN}━━ $* ━━${RESET}"; }
optional(){ echo -e "${YELLOW}[~]${RESET} $* ${YELLOW}(optional)${RESET}"; }

# ── Banner ───────────────────────────────────────────────────────────────────
echo -e "
${CYAN}${BOLD}
     ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
     ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
     ██║███████║██████╔╝██║   ██║██║███████╗
██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
 ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝
${RESET}
  Autonomous AI Desktop Agent  |  v0.8  |  AGPL-3.0
  ${CYAN}https://jarvis-ai.info${RESET}
"

# ── Root-Check ───────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    warn "Nicht als root – versuche sudo für Paketinstallation."
    SUDO="sudo"
else
    SUDO=""
fi

# ── OS-Erkennung ─────────────────────────────────────────────────────────────
step "Betriebssystem erkennen"
if   command -v apt-get &>/dev/null; then PKG_MGR="apt-get"; INSTALL="apt-get install -y"
elif command -v dnf     &>/dev/null; then PKG_MGR="dnf";     INSTALL="dnf install -y"
elif command -v yum     &>/dev/null; then PKG_MGR="yum";     INSTALL="yum install -y"
elif command -v pacman  &>/dev/null; then PKG_MGR="pacman";  INSTALL="pacman -S --noconfirm"
elif command -v zypper  &>/dev/null; then PKG_MGR="zypper";  INSTALL="zypper install -y"
else error "Kein unterstützter Paketmanager gefunden (apt/dnf/yum/pacman/zypper)."
fi
success "Paketmanager: $PKG_MGR"

# ── Hilfsfunktion: Paket installieren ────────────────────────────────────────
install_pkg() {
    local pkg="$1"
    local name="${2:-$1}"
    if ! command -v "$name" &>/dev/null; then
        info "Installiere $pkg ..."
        $SUDO $INSTALL "$pkg" >/dev/null 2>&1 || warn "Konnte $pkg nicht automatisch installieren – bitte manuell nachinstallieren."
    else
        success "$name bereits vorhanden ($(command -v "$name"))"
    fi
}

# ── Basis-Abhängigkeiten ──────────────────────────────────────────────────────
step "Basis-Abhängigkeiten prüfen & installieren"

install_pkg git git
install_pkg curl curl

# Build-Tools (nötig für Python-Pakete mit C-Erweiterungen)
if [[ "$PKG_MGR" == "apt-get" ]]; then
    info "Installiere Build-Tools & Python-Dev-Header ..."
    $SUDO apt-get install -y build-essential python3-dev libssl-dev libffi-dev libpam0g-dev >/dev/null 2>&1 \
        && success "Build-Tools installiert" \
        || warn "Build-Tools konnten nicht installiert werden – manche pip-Pakete könnten fehlschlagen."
elif [[ "$PKG_MGR" == "dnf" || "$PKG_MGR" == "yum" ]]; then
    $SUDO $INSTALL gcc gcc-c++ python3-devel openssl-devel libffi-devel >/dev/null 2>&1 || true
elif [[ "$PKG_MGR" == "pacman" ]]; then
    $SUDO pacman -S --noconfirm base-devel python-pip >/dev/null 2>&1 || true
fi

# Python 3.10+
if command -v python3 &>/dev/null; then
    PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
    if [[ "$PY_MAJOR" -ge 3 && "$PY_MINOR" -ge 10 ]]; then
        success "Python $PY_VER vorhanden"
    else
        warn "Python $PY_VER zu alt (mind. 3.10 nötig)"
        if [[ "$PKG_MGR" == "apt-get" ]]; then
            $SUDO apt-get install -y python3.12 python3.12-venv >/dev/null 2>&1 || true
        fi
    fi
else
    info "Installiere Python 3 ..."
    if   [[ "$PKG_MGR" == "apt-get" ]]; then $SUDO apt-get install -y python3 python3-venv python3-pip >/dev/null 2>&1
    elif [[ "$PKG_MGR" == "dnf"     ]]; then $SUDO dnf install -y python3 python3-pip >/dev/null 2>&1
    elif [[ "$PKG_MGR" == "pacman"  ]]; then $SUDO pacman -S --noconfirm python python-pip >/dev/null 2>&1
    else $SUDO $INSTALL python3 >/dev/null 2>&1; fi
    success "Python 3 installiert"
fi

# python3-venv (wird immer benötigt – auch wenn python3 bereits vorhanden ist)
if [[ "$PKG_MGR" == "apt-get" ]]; then
    $SUDO apt-get install -y python3-venv >/dev/null 2>&1 || true
elif [[ "$PKG_MGR" == "dnf" || "$PKG_MGR" == "yum" ]]; then
    $SUDO $INSTALL python3-venv >/dev/null 2>&1 || true
fi

# pip
if ! command -v pip3 &>/dev/null && ! python3 -m pip --version &>/dev/null 2>&1; then
    info "Installiere pip ..."
    if [[ "$PKG_MGR" == "apt-get" ]]; then
        $SUDO apt-get install -y python3-pip >/dev/null 2>&1
    else
        curl -fsSL https://bootstrap.pypa.io/get-pip.py | python3 - >/dev/null 2>&1
    fi
    success "pip installiert"
else
    success "pip vorhanden"
fi

# Node.js (für WhatsApp Bridge)
if ! command -v node &>/dev/null; then
    info "Installiere Node.js (für WhatsApp Bridge) ..."
    if [[ "$PKG_MGR" == "apt-get" ]]; then
        curl -fsSL https://deb.nodesource.com/setup_20.x | $SUDO bash - >/dev/null 2>&1
        $SUDO apt-get install -y nodejs >/dev/null 2>&1
    elif [[ "$PKG_MGR" == "dnf" || "$PKG_MGR" == "yum" ]]; then
        curl -fsSL https://rpm.nodesource.com/setup_20.x | $SUDO bash - >/dev/null 2>&1
        $SUDO $INSTALL nodejs >/dev/null 2>&1
    elif [[ "$PKG_MGR" == "pacman" ]]; then
        $SUDO pacman -S --noconfirm nodejs npm >/dev/null 2>&1
    else
        warn "Node.js nicht installiert – WhatsApp Bridge nicht verfügbar."
    fi
    command -v node &>/dev/null && success "Node.js $(node --version) installiert" || warn "Node.js konnte nicht installiert werden"
else
    success "Node.js $(node --version) vorhanden"
fi

# ── Desktop / VNC / X11 Pakete ───────────────────────────────────────────────
step "Desktop-Steuerung & VNC einrichten"

if [[ "$PKG_MGR" == "apt-get" ]]; then
    info "Installiere X11/VNC/Desktop-Pakete ..."
    $SUDO apt-get install -y \
        xvfb x11vnc openbox \
        xdotool wmctrl scrot \
        websockify \
        xauth x11-utils \
        >/dev/null 2>&1 && success "X11/VNC/Desktop-Pakete installiert" \
        || warn "Einige X11-Pakete konnten nicht installiert werden."
elif [[ "$PKG_MGR" == "dnf" || "$PKG_MGR" == "yum" ]]; then
    $SUDO $INSTALL xorg-x11-server-Xvfb x11vnc openbox xdotool wmctrl scrot python3-websockify >/dev/null 2>&1 || true
    success "X11-Pakete installiert (ggf. unvollständig – bitte manuell prüfen)"
elif [[ "$PKG_MGR" == "pacman" ]]; then
    $SUDO pacman -S --noconfirm xorg-server-xvfb x11vnc openbox xdotool wmctrl scrot python-websockify >/dev/null 2>&1 || true
    success "X11-Pakete installiert"
else
    warn "X11-Pakete bitte manuell installieren: xvfb x11vnc openbox xdotool wmctrl scrot websockify"
fi

# ── Chrome / Chromium (für Browser-Automatisierung via CDP) ──────────────────
step "Chrome / Chromium installieren"

if command -v google-chrome &>/dev/null || command -v chromium &>/dev/null || command -v chromium-browser &>/dev/null; then
    CHROME_CMD="$(command -v google-chrome 2>/dev/null || command -v chromium 2>/dev/null || command -v chromium-browser 2>/dev/null)"
    success "Browser vorhanden: $CHROME_CMD"
else
    if [[ "$PKG_MGR" == "apt-get" ]]; then
        # Versuche zuerst Google Chrome (DEB), Fallback auf Chromium aus Paketquellen
        info "Versuche Google Chrome zu installieren ..."
        if curl -fsSL https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
               -o /tmp/chrome.deb 2>/dev/null; then
            $SUDO apt-get install -y /tmp/chrome.deb >/dev/null 2>&1 \
                && success "Google Chrome installiert" \
                || { warn "Chrome-DEB fehlgeschlagen – installiere Chromium aus Repos ...";
                     $SUDO apt-get install -y chromium chromium-browser 2>/dev/null \
                         || $SUDO apt-get install -y chromium >/dev/null 2>&1 \
                         || warn "Chromium nicht gefunden – Browser-Automatisierung (CDP) nicht verfügbar."; }
            rm -f /tmp/chrome.deb
        else
            info "Chrome-Download nicht möglich – installiere Chromium ..."
            $SUDO apt-get install -y chromium chromium-browser 2>/dev/null \
                || $SUDO apt-get install -y chromium >/dev/null 2>&1 \
                || warn "Chromium nicht installiert – Browser-Automatisierung (CDP) nicht verfügbar."
        fi
    elif [[ "$PKG_MGR" == "dnf" || "$PKG_MGR" == "yum" ]]; then
        $SUDO $INSTALL chromium >/dev/null 2>&1 && success "Chromium installiert" \
            || warn "Chromium nicht installiert – Browser-Automatisierung (CDP) nicht verfügbar."
    elif [[ "$PKG_MGR" == "pacman" ]]; then
        $SUDO pacman -S --noconfirm chromium >/dev/null 2>&1 && success "Chromium installiert" \
            || warn "Chromium nicht installiert – Browser-Automatisierung (CDP) nicht verfügbar."
    else
        warn "Bitte Chrome oder Chromium manuell installieren für Browser-Automatisierung (CDP)."
    fi
fi

# ── Jarvis klonen ─────────────────────────────────────────────────────────────
step "Jarvis klonen"
INSTALL_DIR="${JARVIS_DIR:-$HOME/jarvis}"

if [[ -d "$INSTALL_DIR/.git" ]]; then
    warn "Verzeichnis $INSTALL_DIR existiert bereits – führe git pull durch."
    git -C "$INSTALL_DIR" pull --ff-only
else
    git clone https://github.com/dev-core-busy/jarvis.git "$INSTALL_DIR"
fi
success "Jarvis in: $INSTALL_DIR"

# ── Daten-Verzeichnisse anlegen ───────────────────────────────────────────────
step "Daten-Verzeichnisse anlegen"
mkdir -p "$INSTALL_DIR/data/logs" \
         "$INSTALL_DIR/data/knowledge" \
         "$INSTALL_DIR/data/google_auth" \
         "$INSTALL_DIR/data/workflows"
success "Daten-Verzeichnisse angelegt"

# ── Python venv + Abhängigkeiten ──────────────────────────────────────────────
step "Python-Umgebung einrichten"
cd "$INSTALL_DIR"

python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip wheel >/dev/null 2>&1 || true
info "Installiere Python-Pakete (dauert ~1–2 min) ..."
# Erst still versuchen – bei Fehler Ausgabe anzeigen für Diagnose
if ! pip install -r requirements.txt >/dev/null 2>&1; then
    warn "Stiller Durchlauf fehlgeschlagen – zeige Fehlerausgabe:"
    pip install -r requirements.txt || error "Python-Pakete konnten nicht installiert werden! Abhängigkeiten prüfen (build-essential, python3-dev, libssl-dev)."
fi
success "Python-Pakete installiert"

# faster-whisper (optional – für WhatsApp Sprach-Transkription)
info "Installiere faster-whisper für Sprach-Transkription (optional) ..."
pip install faster-whisper "numpy<2.1" >/dev/null 2>&1 \
    && success "faster-whisper installiert (Sprach-Transkription aktiv)" \
    || optional "faster-whisper konnte nicht installiert werden – Sprach-Transkription nicht verfügbar."

# ── WhatsApp Bridge: npm install ─────────────────────────────────────────────
step "WhatsApp Bridge einrichten"
WA_DIR="$INSTALL_DIR/services/whatsapp-bridge"

if [[ -d "$WA_DIR" ]] && command -v npm &>/dev/null; then
    info "Installiere Node.js-Abhängigkeiten für WhatsApp Bridge ..."
    ( cd "$WA_DIR" && npm install --silent 2>/dev/null ) \
        && success "WhatsApp Bridge Abhängigkeiten installiert" \
        || warn "npm install in $WA_DIR fehlgeschlagen – WhatsApp Bridge ggf. nicht funktionsfähig."
elif ! command -v npm &>/dev/null; then
    warn "npm nicht gefunden – WhatsApp Bridge Abhängigkeiten nicht installiert."
else
    warn "WhatsApp Bridge Verzeichnis nicht gefunden: $WA_DIR"
fi

# ── .env konfigurieren ────────────────────────────────────────────────────────
step "Konfiguration"

if [[ ! -f "$INSTALL_DIR/.env" ]]; then
    cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
    success ".env aus Vorlage erstellt"
else
    success ".env bereits vorhanden"
fi

echo -e "
${CYAN}ℹ  Hinweis zu API-Keys:${RESET}
   LLM-Profile (API-Keys, Modelle, Provider) werden direkt im
   ${BOLD}Web-Interface${RESET} unter ${CYAN}Einstellungen → LLM-Profile${RESET} konfiguriert.
   Dort können auch mehrere Profile (Gemini, Claude, OpenRouter …)
   gleichzeitig hinterlegt und per Klick gewechselt werden.

   Die .env-Datei enthält nur Server-Einstellungen wie Port und Passwort.
"

# ── Autostart via systemd ──────────────────────────────────────────────────────
step "Autostart einrichten (systemd)"

CURRENT_USER="${SUDO_USER:-$(whoami)}"
# Explizit python3 verwenden – python-Symlink existiert nicht auf allen Systemen
PYTHON_BIN="$INSTALL_DIR/venv/bin/python3"

if command -v systemctl &>/dev/null; then

    # ── jarvis.service ────────────────────────────────────────────────────────
    SERVICE_FILE="/etc/systemd/system/jarvis.service"
    $SUDO tee "$SERVICE_FILE" >/dev/null << UNIT
[Unit]
Description=Jarvis AI Desktop Agent
Documentation=https://github.com/dev-core-busy/jarvis
After=network.target
Wants=network.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/start_jarvis.sh
Restart=on-failure
RestartSec=10
Environment=PYTHONUNBUFFERED=1
Environment=DISPLAY=:1

[Install]
WantedBy=multi-user.target
UNIT

    # ── whatsapp-bridge.service ───────────────────────────────────────────────
    NODE_BIN="$(command -v node 2>/dev/null || echo /usr/bin/node)"
    WA_SERVICE_FILE="/etc/systemd/system/whatsapp-bridge.service"

    if [[ -d "$WA_DIR" ]] && command -v node &>/dev/null; then
        $SUDO tee "$WA_SERVICE_FILE" >/dev/null << WA_UNIT
[Unit]
Description=Jarvis WhatsApp Bridge (Baileys)
Documentation=https://github.com/dev-core-busy/jarvis
After=network.target jarvis.service
Wants=network.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$WA_DIR
ExecStart=$NODE_BIN index.js
Restart=on-failure
RestartSec=10
Environment=NODE_ENV=production

[Install]
WantedBy=multi-user.target
WA_UNIT
        $SUDO systemctl enable whatsapp-bridge.service >/dev/null 2>&1
        success "whatsapp-bridge.service eingerichtet"
        WA_SERVICE_OK=1
    else
        warn "WhatsApp Bridge Service nicht eingerichtet (Node.js oder Verzeichnis fehlt)."
        WA_SERVICE_OK=0
    fi

    $SUDO systemctl daemon-reload
    $SUDO systemctl enable jarvis.service >/dev/null 2>&1
    $SUDO systemctl start  jarvis.service 2>/dev/null || true

    # Status prüfen
    sleep 2
    if systemctl is-active --quiet jarvis.service; then
        success "Jarvis läuft als systemd-Service (jarvis.service)"
        AUTOSTART_MSG="${GREEN}✓ Autostart aktiv${RESET} – Jarvis startet automatisch beim Systemstart."
    else
        warn "Service gestartet, aber noch nicht aktiv – prüfe: journalctl -u jarvis.service"
        AUTOSTART_MSG="${YELLOW}Autostart eingerichtet${RESET} – prüfe Status mit: systemctl status jarvis.service"
    fi

else
    warn "systemd nicht gefunden – kein Autostart eingerichtet."
    AUTOSTART_MSG="${YELLOW}Kein Autostart${RESET} – systemd nicht verfügbar auf diesem System."
    WA_SERVICE_OK=0
fi

# ── Firewall-Hinweis ──────────────────────────────────────────────────────────
step "Firewall-Hinweis"
echo -e "
${YELLOW}Falls eine Firewall aktiv ist, folgende Ports freigeben:${RESET}
  ${BOLD}8000${RESET}  – Jarvis Web-Interface (HTTPS)
  ${BOLD}6080${RESET}  – noVNC Desktop-Streaming (HTTPS/WSS)

  Beispiel (ufw):
    ${CYAN}ufw allow 8000/tcp${RESET}
    ${CYAN}ufw allow 6080/tcp${RESET}
"

# ── Fertig ─────────────────────────────────────────────────────────────────────
# Eigene IP(s) ermitteln – für Remote-SSH-Nutzer hilfreich
SERVER_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
# Falls hostname -I nicht verfügbar, via ip-Befehl
[[ -z "$SERVER_IP" ]] && SERVER_IP=$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1); exit}')
# Letzter Fallback
[[ -z "$SERVER_IP" ]] && SERVER_IP="<server-ip>"

WA_NOTE=""
if [[ "${WA_SERVICE_OK:-0}" == "1" ]]; then
    WA_NOTE="  ${CYAN}systemctl start whatsapp-bridge.service${RESET}   # WhatsApp Bridge starten"$'\n'
    WA_NOTE+="  ${CYAN}systemctl status whatsapp-bridge.service${RESET}  # WhatsApp Bridge Status"$'\n'
fi

echo -e "
${GREEN}${BOLD}╔══════════════════════════════════════════════════════════╗
║            🤖  JARVIS erfolgreich installiert!           ║
╚══════════════════════════════════════════════════════════╝${RESET}

${BOLD}Status:${RESET}
  $(eval echo -e "$AUTOSTART_MSG")
  ${CYAN}systemctl status jarvis.service${RESET}

${BOLD}Jetzt im Browser öffnen:${RESET}
  ${CYAN}https://localhost:8000${RESET}         ${YELLOW}← lokal auf diesem Rechner${RESET}
  ${CYAN}https://${SERVER_IP}:8000${RESET}   ${YELLOW}← im Netzwerk / von außen${RESET}
  Login: ${BOLD}jarvis / jarvis${RESET}
  ${YELLOW}(SSL-Warnung beim ersten Aufruf einfach bestätigen)${RESET}

${BOLD}API-Key einrichten:${RESET}
  Im Browser: ${CYAN}Einstellungen (⚙) → LLM-Profile → Profil hinzufügen${RESET}
  Unterstützte Anbieter: Gemini (kostenlos), OpenRouter, Claude, Ollama …

${BOLD}Nützliche Befehle:${RESET}
  ${CYAN}systemctl status  jarvis.service${RESET}   # Status
  ${CYAN}systemctl restart jarvis.service${RESET}   # Neustart
  ${CYAN}journalctl -u jarvis.service -f${RESET}    # Logs live verfolgen
  ${CYAN}systemctl disable jarvis.service${RESET}   # Autostart deaktivieren
$(echo -e "$WA_NOTE")
${BOLD}Dokumentation & GitHub:${RESET}
  ${CYAN}https://jarvis-ai.info${RESET}
  ${CYAN}https://github.com/dev-core-busy/jarvis${RESET}
"
