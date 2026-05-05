#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Jarvis AI Desktop Agent – Installer & Updater
# Copyright (C) 2026 Andreas Bender · AGPL-3.0
# https://jarvis-ai.info  |  https://github.com/dev-core-busy/jarvis
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Interaktive Dialoge unterdruecken (davfs2, etc.) ─────────────────────
export DEBIAN_FRONTEND=noninteractive

# ── Update-Erkennung ────────────────────────────────────────────────────────
# Automatisch: wenn /opt/jarvis oder ~/jarvis mit .git existiert → Update-Modus
UPDATE_MODE=0
INSTALL_DIR="${JARVIS_DIR:-}"
if [[ -n "$INSTALL_DIR" && -d "$INSTALL_DIR/.git" ]]; then
    UPDATE_MODE=1
elif [[ -d "/opt/jarvis/.git" ]]; then
    INSTALL_DIR="/opt/jarvis"
    UPDATE_MODE=1
elif [[ -d "$HOME/jarvis/.git" ]]; then
    INSTALL_DIR="$HOME/jarvis"
    UPDATE_MODE=1
fi

# ── Farben ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[Jarvis]${RESET} $*"; }
success() { echo -e "${GREEN}[✓]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[!]${RESET} $*"; }
error()   { echo -e "${RED}[✗]${RESET} $*"; exit 1; }
optional(){ echo -e "${YELLOW}[~]${RESET} $* ${YELLOW}(optional)${RESET}"; }

# ── Fortschrittsanzeige ────────────────────────────────────────────────────
TOTAL_STEPS=10
CURRENT_STEP=0
INSTALL_START=$(date +%s)

# Geschaetzte Dauer pro Schritt in Sekunden
#   1=OS-Erkennung, 2=Basis, 3=Python/Node, 4=Desktop/VNC, 5=Chrome,
#   6=Git clone/pull, 7=pip install, 8=WhatsApp Bridge, 9=Benutzer/Config, 10=systemd
if [[ $UPDATE_MODE -eq 1 ]]; then
    # Update: System-Pakete ueberspringen, nur git pull + pip upgrade
    STEP_ESTIMATES=(0 2 5 5 5 5 10 120 10 3 5)
else
    # Erstinstallation: volle Dauer
    STEP_ESTIMATES=(0 3 45 40 240 45 15 900 20 5 10)
fi
STEP_NAMES=("" "Betriebssystem" "Basis-Abhaengigkeiten" "Python & Node.js"
             "Desktop & VNC" "Chrome/Chromium" "Jarvis klonen"
             "Python-Pakete" "WhatsApp Bridge" "Konfiguration" "Autostart")
# Tatsaechliche Dauer pro Schritt (wird waehrend Installation gefuellt)
declare -a STEP_ACTUAL=()

# Gesamtschaetzung berechnen
_total_estimate() {
    local sum=0
    for ((i=1; i<=TOTAL_STEPS; i++)); do sum=$((sum + STEP_ESTIMATES[i])); done
    echo $sum
}

# Verbleibende Zeit schaetzen
_eta() {
    local now=$(date +%s)
    local elapsed=$((now - INSTALL_START))
    local remaining=0
    # Bereits abgeschlossene Schritte: tatsaechliche Dauer bekannt
    # Noch offene Schritte: Schaetzung verwenden
    for ((i=CURRENT_STEP+1; i<=TOTAL_STEPS; i++)); do
        remaining=$((remaining + STEP_ESTIMATES[i]))
    done
    echo $remaining
}

# Formatiert Sekunden zu lesbarem String
_fmt_time() {
    local secs=$1
    if [[ $secs -lt 5 ]]; then
        echo "<5s"
    elif [[ $secs -lt 60 ]]; then
        echo "~${secs}s"
    else
        local m=$((secs / 60))
        local s=$((secs % 60))
        if [[ $s -eq 0 ]]; then
            echo "~${m} Min"
        else
            echo "~${m} Min ${s}s"
        fi
    fi
}

progress_bar() {
    local current=$1
    local total=$2
    local label="$3"
    local step_est="${4:-0}"
    local bar_width=40
    local filled=$(( current * bar_width / total ))
    local empty=$(( bar_width - filled ))
    local bar=""
    for ((i=0; i<filled; i++)); do bar+="█"; done
    for ((i=0; i<empty; i++)); do bar+="░"; done
    local pct=$(( current * 100 / total ))
    local elapsed=$(( $(date +%s) - INSTALL_START ))
    local elapsed_str=$(printf "%d:%02d" $((elapsed/60)) $((elapsed%60)))
    local eta=$(_eta)
    local eta_str=$(_fmt_time $eta)

    # Fortschrittszeile
    echo ""
    echo -e "${BOLD}${CYAN}  [${bar}] ${pct}%  (${current}/${total})${RESET}"
    echo -e "  ${BOLD}▸ ${label}${RESET}  ${DIM}│ Schritt: $(_fmt_time $step_est) │ Vergangen: ${elapsed_str} │ Verbleibend: ${eta_str}${RESET}"
}

step() {
    # Vorherigen Schritt als erledigt markieren + tatsaechliche Dauer speichern
    if [[ $CURRENT_STEP -gt 0 ]]; then
        local now=$(date +%s)
        local prev_start=${STEP_START:-$INSTALL_START}
        STEP_ACTUAL[$CURRENT_STEP]=$((now - prev_start))
    fi
    CURRENT_STEP=$((CURRENT_STEP + 1))
    STEP_START=$(date +%s)
    local est=${STEP_ESTIMATES[$CURRENT_STEP]:-0}
    progress_bar "$CURRENT_STEP" "$TOTAL_STEPS" "$1" "$est"
}

# Spinner fuer lang laufende Befehle (mit Schaetzung)
spinner() {
    local pid=$1
    local label="${2:-Bitte warten}"
    local est_secs="${3:-0}"
    local spin_chars='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
    local i=0
    local start=$(date +%s)
    local cols=$(tput cols 2>/dev/null || echo 80)

    while kill -0 "$pid" 2>/dev/null; do
        local elapsed=$(( $(date +%s) - start ))
        local elapsed_str=$(printf "%d:%02d" $((elapsed/60)) $((elapsed%60)))
        local char="${spin_chars:i++%${#spin_chars}:1}"

        # Mini-Fortschrittsbalken innerhalb des Spinners
        if [[ $est_secs -gt 0 ]]; then
            local sub_pct=$((elapsed * 100 / est_secs))
            [[ $sub_pct -gt 99 ]] && sub_pct=99
            local sub_width=20
            local sub_filled=$((sub_pct * sub_width / 100))
            local sub_empty=$((sub_width - sub_filled))
            local sub_bar=""
            for ((j=0; j<sub_filled; j++)); do sub_bar+="▓"; done
            for ((j=0; j<sub_empty; j++)); do sub_bar+="░"; done
            printf "\r  ${CYAN}${char}${RESET} ${label} ${DIM}[${sub_bar}] ${elapsed_str}${RESET}  " >&2
        else
            printf "\r  ${CYAN}${char}${RESET} ${label} ${DIM}[${elapsed_str}]${RESET}  " >&2
        fi
        sleep 0.1
    done
    printf "\r\033[K" >&2
    wait "$pid"
    return $?
}

# Wrapper: Befehl mit Spinner ausfuehren (mit optionaler Schaetzung)
run_with_spinner() {
    local label="$1"
    local est="${2:-0}"
    shift 2
    "$@" >/dev/null 2>&1 &
    local pid=$!
    spinner "$pid" "$label" "$est"
    return $?
}

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

if [[ $UPDATE_MODE -eq 1 ]]; then
    echo -e "  ${GREEN}${BOLD}🔄 UPDATE-MODUS${RESET} – bestehende Installation erkannt: ${CYAN}$INSTALL_DIR${RESET}
  ${DIM}Geschaetzte Update-Dauer: $(_fmt_time $(_total_estimate))${RESET}
  ${DIM}(System-Pakete werden uebersprungen, nur Code + Python-Pakete aktualisiert)${RESET}
"
else
    echo -e "  ${DIM}Geschaetzte Installationsdauer: $(_fmt_time $(_total_estimate))${RESET}
  ${DIM}(abhaengig von Internetgeschwindigkeit und Hardware)${RESET}
"
fi

# ── Root-Check ───────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    warn "Nicht als root – versuche sudo für Paketinstallation."
    SUDO="sudo"
else
    SUDO=""
fi

# ══════════════════════════════════════════════════════════════════════════════
# Schritt 1: OS-Erkennung
# ══════════════════════════════════════════════════════════════════════════════
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
        success "$name bereits vorhanden"
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
# Schritt 2: Basis-Abhängigkeiten
# ══════════════════════════════════════════════════════════════════════════════
step "Basis-Abhaengigkeiten"

if [[ $UPDATE_MODE -eq 1 ]]; then
    success "Update-Modus – System-Pakete uebersprungen"
else
    install_pkg git git
    install_pkg curl curl
    install_pkg ffmpeg ffmpeg

    # Build-Tools (nötig für Python-Pakete mit C-Erweiterungen)
    if [[ "$PKG_MGR" == "apt-get" ]]; then
        if run_with_spinner "Build-Tools & Dev-Header installieren" 30 \
            $SUDO apt-get install -y build-essential python3-dev libssl-dev libffi-dev libpam0g-dev cmake libboost-all-dev; then
            success "Build-Tools installiert"
        else
            warn "Build-Tools konnten nicht installiert werden – manche pip-Pakete könnten fehlschlagen."
        fi
    elif [[ "$PKG_MGR" == "dnf" || "$PKG_MGR" == "yum" ]]; then
        run_with_spinner "Build-Tools installieren" 30 \
            $SUDO $INSTALL gcc gcc-c++ python3-devel openssl-devel libffi-devel cmake boost-devel || true
    elif [[ "$PKG_MGR" == "pacman" ]]; then
        run_with_spinner "Build-Tools installieren" 20 \
            $SUDO pacman -S --noconfirm base-devel python-pip || true
    fi
fi

# ══════════════════════════════════════════════════════════════════════════════
# Schritt 3: Python & Node.js
# ══════════════════════════════════════════════════════════════════════════════
step "Python & Node.js einrichten"

if [[ $UPDATE_MODE -eq 1 ]]; then
    success "Update-Modus – Python $(python3 --version 2>&1 | awk '{print $2}'), Node $(node --version 2>/dev/null || echo 'n/a') vorhanden"
else
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

    # python3-venv
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
fi

# ══════════════════════════════════════════════════════════════════════════════
# Schritt 4: Desktop / VNC (Cinnamon + X11/VNC)
# ══════════════════════════════════════════════════════════════════════════════
step "Desktop-Umgebung & VNC"

if [[ $UPDATE_MODE -eq 1 ]]; then
    success "Update-Modus – Desktop-Pakete uebersprungen"
elif [[ "$PKG_MGR" == "apt-get" ]]; then
    if run_with_spinner "Cinnamon Desktop + X11/VNC-Pakete installieren" 300 \
        $SUDO apt-get install -y \
            xvfb x11vnc \
            cinnamon-core cinnamon-session dbus-x11 at-spi2-core \
            xdotool wmctrl scrot \
            python3-websockify novnc \
            xauth x11-utils xterm \
            cifs-utils nfs-common davfs2; then
        success "Cinnamon Desktop + X11/VNC-Pakete installiert"
    else
        warn "Einige Desktop/X11-Pakete konnten nicht installiert werden."
    fi

    # Fallback falls python3-websockify nicht verfuegbar
    if ! command -v websockify &>/dev/null; then
        $SUDO apt-get install -y websockify >/dev/null 2>&1 || \
        pip install websockify >/dev/null 2>&1 || \
        warn "websockify nicht installiert – noVNC Desktop-Vorschau nicht verfuegbar."
    fi
elif [[ "$PKG_MGR" == "dnf" || "$PKG_MGR" == "yum" ]]; then
    run_with_spinner "X11/VNC-Pakete installieren" 120 \
        $SUDO $INSTALL xorg-x11-server-Xvfb x11vnc openbox xdotool wmctrl scrot python3-websockify || true
    success "X11-Pakete installiert (ggf. unvollstaendig – bitte manuell pruefen)"
elif [[ "$PKG_MGR" == "pacman" ]]; then
    run_with_spinner "X11/VNC-Pakete installieren" 60 \
        $SUDO pacman -S --noconfirm xorg-server-xvfb x11vnc openbox xdotool wmctrl scrot python-websockify || true
    success "X11-Pakete installiert"
else
    warn "X11-Pakete bitte manuell installieren: xvfb x11vnc openbox xdotool wmctrl scrot websockify"
fi

# ══════════════════════════════════════════════════════════════════════════════
# Schritt 5: Chrome / Chromium
# ══════════════════════════════════════════════════════════════════════════════
step "Chrome / Chromium"

if [[ $UPDATE_MODE -eq 1 ]]; then
    success "Update-Modus – Browser uebersprungen"
elif command -v google-chrome &>/dev/null || command -v chromium &>/dev/null || command -v chromium-browser &>/dev/null; then
    CHROME_CMD="$(command -v google-chrome 2>/dev/null || command -v chromium 2>/dev/null || command -v chromium-browser 2>/dev/null)"
    success "Browser vorhanden: $CHROME_CMD"
else
    if [[ "$PKG_MGR" == "apt-get" ]]; then
        info "Versuche Google Chrome zu installieren ..."
        if curl -fsSL https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
               -o /tmp/chrome.deb 2>/dev/null; then
            if run_with_spinner "Google Chrome installieren" 30 \
                $SUDO apt-get install -y /tmp/chrome.deb; then
                success "Google Chrome installiert"
            else
                warn "Chrome-DEB fehlgeschlagen – installiere Chromium aus Repos ..."
                $SUDO apt-get install -y chromium chromium-browser 2>/dev/null \
                    || $SUDO apt-get install -y chromium >/dev/null 2>&1 \
                    || warn "Chromium nicht gefunden – Browser-Automatisierung (CDP) nicht verfügbar."
            fi
            rm -f /tmp/chrome.deb
        else
            info "Chrome-Download nicht möglich – installiere Chromium ..."
            $SUDO apt-get install -y chromium chromium-browser 2>/dev/null \
                || $SUDO apt-get install -y chromium >/dev/null 2>&1 \
                || warn "Chromium nicht installiert – Browser-Automatisierung (CDP) nicht verfügbar."
        fi
    elif [[ "$PKG_MGR" == "dnf" || "$PKG_MGR" == "yum" ]]; then
        run_with_spinner "Chromium installieren" 30 \
            $SUDO $INSTALL chromium && success "Chromium installiert" \
            || warn "Chromium nicht installiert – Browser-Automatisierung (CDP) nicht verfuegbar."
    elif [[ "$PKG_MGR" == "pacman" ]]; then
        run_with_spinner "Chromium installieren" 20 \
            $SUDO pacman -S --noconfirm chromium && success "Chromium installiert" \
            || warn "Chromium nicht installiert – Browser-Automatisierung (CDP) nicht verfügbar."
    else
        warn "Bitte Chrome oder Chromium manuell installieren für Browser-Automatisierung (CDP)."
    fi
fi

# ══════════════════════════════════════════════════════════════════════════════
# Schritt 6: Jarvis klonen
# ══════════════════════════════════════════════════════════════════════════════
step "Jarvis klonen"

INSTALL_DIR="${JARVIS_DIR:-$HOME/jarvis}"

if [[ -d "$INSTALL_DIR/.git" ]]; then
    warn "Verzeichnis $INSTALL_DIR existiert bereits – führe git pull durch."
    git -C "$INSTALL_DIR" pull --ff-only
else
    git clone https://github.com/dev-core-busy/jarvis.git "$INSTALL_DIR"
fi
success "Jarvis in: $INSTALL_DIR"

# Daten-Verzeichnisse anlegen
mkdir -p "$INSTALL_DIR/data/logs" \
         "$INSTALL_DIR/data/knowledge" \
         "$INSTALL_DIR/data/google_auth" \
         "$INSTALL_DIR/data/workflows"
success "Daten-Verzeichnisse angelegt"

# ══════════════════════════════════════════════════════════════════════════════
# Schritt 7: Python-Pakete (pip install)
# ══════════════════════════════════════════════════════════════════════════════
step "Python-Pakete installieren"

cd "$INSTALL_DIR"

if [[ $UPDATE_MODE -eq 1 && -d "venv" ]]; then
    source venv/bin/activate
    success "Bestehendes venv aktiviert"
else
    python3 -m venv venv
    source venv/bin/activate
fi

run_with_spinner "pip aktualisieren" 10 pip install --upgrade pip wheel || true

# Cache leeren und TMPDIR auf echte Disk legen (PyTorch etc. sprengen sonst /tmp bei tmpfs)
pip cache purge >/dev/null 2>&1 || true
mkdir -p /var/tmp/pip
export TMPDIR=/var/tmp/pip

if [[ $UPDATE_MODE -eq 1 ]]; then
    # ── Update: nur requirements.txt upgraden ────────────────────────────────
    info "Aktualisiere Python-Pakete ..."
    if run_with_spinner "Python-Pakete aktualisieren" 90 \
        pip install --no-cache-dir -q --upgrade -r requirements.txt; then
        success "Python-Pakete aktualisiert"
    else
        warn "Upgrade fehlgeschlagen – zeige Fehlerausgabe:"
        pip install --no-cache-dir --upgrade -r requirements.txt || warn "Einige Pakete konnten nicht aktualisiert werden."
    fi
else
    # ── Erstinstallation: 4 Phasen ──────────────────────────────────────────
    # Phase 1: Kern-Pakete direkt aus requirements.txt (ohne langsame/optionale Pakete)
    # Ausgeschlossen: face-recognition/opencv (kompiliert), chromadb, sentence-transformers, faster-whisper
    info "Installiere Kern-Abhängigkeiten aus requirements.txt ..."
    CORE_REQS=$(grep -v -E "^\s*#|^\s*$|face-recognition|opencv|chromadb|sentence-transformers|faster-whisper" requirements.txt | tr '\n' ' ')
    if run_with_spinner "Kern-Pakete installieren" 120 \
        bash -c "pip install --no-cache-dir -q $CORE_REQS"; then
        success "Kern-Pakete installiert"
    else
        warn "Stiller Durchlauf fehlgeschlagen – zeige Fehlerausgabe:"
        pip install --no-cache-dir -q $CORE_REQS || error "Python-Pakete konnten nicht installiert werden! Abhängigkeiten prüfen (build-essential, python3-dev, libssl-dev, cmake, libboost-all-dev)."
    fi

    # Phase 2: face-recognition wird nach Servicestart im Hintergrund installiert (dauert 10-20 Min)

    # Phase 3: ChromaDB + Sentence-Transformers (Vektor-Datenbank)
    info "Installiere ChromaDB + Sentence-Transformers ..."
    if run_with_spinner "Vektor-Datenbank installieren" 120 \
        pip install --no-cache-dir -q "chromadb>=0.4.0,<1.0" "sentence-transformers>=2.2.0,<4.0"; then
        success "Vektor-Datenbank installiert (Wissenssuche aktiv)"
    else
        optional "ChromaDB/Sentence-Transformers konnte nicht installiert werden – Wissenssuche nutzt TF-IDF Fallback."
    fi

    # Phase 4: faster-whisper (optional)
    if run_with_spinner "faster-whisper installieren (Sprach-Transkription)" 60 \
        pip install --no-cache-dir -q faster-whisper "numpy<2.1"; then
        success "faster-whisper installiert (Sprach-Transkription aktiv)"
    else
        optional "faster-whisper konnte nicht installiert werden – Sprach-Transkription nicht verfügbar."
    fi
fi

# ══════════════════════════════════════════════════════════════════════════════
# Schritt 8: WhatsApp Bridge
# ══════════════════════════════════════════════════════════════════════════════
step "WhatsApp Bridge"

WA_DIR="$INSTALL_DIR/services/whatsapp-bridge"

if [[ -d "$WA_DIR" ]] && command -v npm &>/dev/null; then
    if run_with_spinner "Node.js-Abhaengigkeiten installieren" 15 \
        bash -c "cd '$WA_DIR' && npm install --silent 2>/dev/null"; then
        success "WhatsApp Bridge Abhängigkeiten installiert"
    else
        warn "npm install in $WA_DIR fehlgeschlagen – WhatsApp Bridge ggf. nicht funktionsfähig."
    fi
elif ! command -v npm &>/dev/null; then
    warn "npm nicht gefunden – WhatsApp Bridge Abhängigkeiten nicht installiert."
else
    warn "WhatsApp Bridge Verzeichnis nicht gefunden: $WA_DIR"
fi

# ══════════════════════════════════════════════════════════════════════════════
# Schritt 9: System-Benutzer & Konfiguration
# ══════════════════════════════════════════════════════════════════════════════
step "System-Benutzer & Konfiguration"

# Jarvis-Benutzer anlegen (PAM-Login)
if id jarvis &>/dev/null; then
    success "Benutzer 'jarvis' bereits vorhanden"
else
    $SUDO useradd -m -s /bin/bash jarvis >/dev/null 2>&1
    echo "jarvis:jarvis" | $SUDO chpasswd
    success "Benutzer 'jarvis' angelegt (Web-Login: jarvis / jarvis)"
fi

# .env konfigurieren
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

# ══════════════════════════════════════════════════════════════════════════════
# Schritt 10: Autostart & Abschluss
# ══════════════════════════════════════════════════════════════════════════════
step "Autostart einrichten (systemd)"

CURRENT_USER="${SUDO_USER:-$(whoami)}"
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

    if [[ $UPDATE_MODE -eq 1 ]]; then
        info "Starte Services neu ..."
        $SUDO systemctl restart jarvis.service 2>/dev/null || true
        [[ "${WA_SERVICE_OK:-0}" == "1" ]] && $SUDO systemctl restart whatsapp-bridge.service 2>/dev/null || true
    else
        $SUDO systemctl start jarvis.service 2>/dev/null || true
    fi

    # face-recognition via eigenem systemd-Service installieren (reboot-sicher, wiederholt bis Erfolg)
    if [[ $UPDATE_MODE -eq 0 ]]; then
        # Installations-Skript schreiben
        $SUDO tee "$INSTALL_DIR/vision-install.sh" >/dev/null << VISION_SH
#!/bin/bash
INSTALL_DIR="$INSTALL_DIR"
VENV="\$INSTALL_DIR/venv/bin/python3"
PIP="\$INSTALL_DIR/venv/bin/pip"

if "\$VENV" -c "import face_recognition" 2>/dev/null; then
    echo "face-recognition bereits installiert."
    systemctl disable jarvis-vision-install.service 2>/dev/null || true
    exit 0
fi

echo "Installiere face-recognition + opencv (dauert 10-20 Min) ..."
if "\$PIP" install -q --no-cache-dir "face-recognition>=1.3.0" "opencv-python-headless>=4.8.0"; then
    echo "face-recognition erfolgreich installiert."
    systemctl disable jarvis-vision-install.service 2>/dev/null || true
else
    echo "Installation fehlgeschlagen – wird beim naechsten Start erneut versucht."
    exit 1
fi
VISION_SH
        $SUDO chmod +x "$INSTALL_DIR/vision-install.sh"

        # systemd-Service schreiben
        $SUDO tee /etc/systemd/system/jarvis-vision-install.service >/dev/null << VISION_UNIT
[Unit]
Description=Jarvis Vision-Abhaengigkeiten (face-recognition/dlib)
After=network-online.target jarvis.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=$INSTALL_DIR/vision-install.sh
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
VISION_UNIT

        $SUDO systemctl daemon-reload
        $SUDO systemctl enable jarvis-vision-install.service >/dev/null 2>&1
        $SUDO systemctl start jarvis-vision-install.service >/dev/null 2>&1 &
        info "Gesichtserkennung wird im Hintergrund kompiliert – reboot-sicher (Log: journalctl -u jarvis-vision-install)"
    fi

    # Status prüfen
    sleep 3
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

# ── Letzten Schritt abschliessen ──────────────────────────────────────────────
if [[ $CURRENT_STEP -gt 0 ]]; then
    STEP_ACTUAL[$CURRENT_STEP]=$(( $(date +%s) - ${STEP_START:-$INSTALL_START} ))
fi

# ── Installationsdauer berechnen ─────────────────────────────────────────────
INSTALL_END=$(date +%s)
INSTALL_DURATION=$(( INSTALL_END - INSTALL_START ))
INSTALL_MIN=$(( INSTALL_DURATION / 60 ))
INSTALL_SEC=$(( INSTALL_DURATION % 60 ))
DURATION_STR="${INSTALL_MIN} Min ${INSTALL_SEC} Sek"

# ── Schrittweise Zusammenfassung ─────────────────────────────────────────────
echo -e "\n${BOLD}${CYAN}  [████████████████████████████████████████] 100%  Installation abgeschlossen!${RESET}\n"
echo -e "${BOLD}  Installationsbericht:${RESET}"
echo -e "  ${DIM}─────────────────────────────────────────────────────────${RESET}"
printf "  ${BOLD}%-4s %-28s %10s %10s${RESET}\n" "#" "Schritt" "Geschaetzt" "Tatsaechl."
echo -e "  ${DIM}─────────────────────────────────────────────────────────${RESET}"
for ((i=1; i<=TOTAL_STEPS; i++)); do
    local_est=${STEP_ESTIMATES[$i]:-0}
    local_act=${STEP_ACTUAL[$i]:-0}
    local_name=${STEP_NAMES[$i]:-"Schritt $i"}
    # Farbkodierung: gruen wenn schneller, gelb wenn langsamer
    if [[ $local_act -le $local_est ]]; then
        color="${GREEN}"
    else
        color="${YELLOW}"
    fi
    printf "  %-4s %-28s %10s ${color}%10s${RESET}\n" \
        "$i." "$local_name" "$(_fmt_time $local_est)" "$(_fmt_time $local_act)"
done
echo -e "  ${DIM}─────────────────────────────────────────────────────────${RESET}"
printf "  ${BOLD}%-4s %-28s %10s %10s${RESET}\n" "" "GESAMT" "$(_fmt_time $(_total_estimate))" "${DURATION_STR}"
echo -e "  ${DIM}─────────────────────────────────────────────────────────${RESET}"

# ── Firewall-Hinweis ──────────────────────────────────────────────────────────
echo -e "
${YELLOW}Falls eine Firewall aktiv ist, folgende Ports freigeben:${RESET}
  ${BOLD}443${RESET}   – Jarvis Web-Interface (HTTPS)
  ${BOLD}80${RESET}    – HTTP → HTTPS Redirect
  ${BOLD}6080${RESET}  – noVNC Desktop-Streaming (HTTPS/WSS)

  Beispiel (ufw):
    ${CYAN}ufw allow 443/tcp${RESET}
    ${CYAN}ufw allow 80/tcp${RESET}
    ${CYAN}ufw allow 6080/tcp${RESET}
"

# ── Fertig ─────────────────────────────────────────────────────────────────────
SERVER_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
[[ -z "$SERVER_IP" ]] && SERVER_IP=$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1); exit}')
[[ -z "$SERVER_IP" ]] && SERVER_IP="<server-ip>"

WA_NOTE=""
if [[ "${WA_SERVICE_OK:-0}" == "1" ]]; then
    WA_NOTE="  ${CYAN}systemctl start whatsapp-bridge.service${RESET}   # WhatsApp Bridge starten"$'\n'
    WA_NOTE+="  ${CYAN}systemctl status whatsapp-bridge.service${RESET}  # WhatsApp Bridge Status"$'\n'
fi

echo -e "
$(if [[ $UPDATE_MODE -eq 1 ]]; then
echo "${GREEN}${BOLD}╔══════════════════════════════════════════════════════════╗
║            🔄  JARVIS erfolgreich aktualisiert!          ║
╚══════════════════════════════════════════════════════════╝${RESET}"
else
echo "${GREEN}${BOLD}╔══════════════════════════════════════════════════════════╗
║            🤖  JARVIS erfolgreich installiert!           ║
╚══════════════════════════════════════════════════════════╝${RESET}"
fi)

  ${DIM}Installation abgeschlossen in ${BOLD}${DURATION_STR}${RESET}

${BOLD}Status:${RESET}
  ${AUTOSTART_MSG}
  ${CYAN}systemctl status jarvis.service${RESET}

${BOLD}Jetzt im Browser öffnen:${RESET}
  ${CYAN}https://${SERVER_IP}${RESET}   ${YELLOW}← im Browser öffnen${RESET}
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
