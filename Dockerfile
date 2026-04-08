# ──────────────────────────────────────────────────────────────────────────────
# Jarvis AI Desktop Agent – Docker Image
# Basis: Debian Bookworm Slim
# Schneller Start mit Openbox, optionales Cinnamon-Upgrade beim ersten Start
# ──────────────────────────────────────────────────────────────────────────────
FROM debian:bookworm-slim

LABEL org.opencontainers.image.title="Jarvis AI Desktop Agent" \
      org.opencontainers.image.description="Autonomer KI-Agent mit Web-UI, VNC-Desktop und WhatsApp-Integration" \
      org.opencontainers.image.source="https://github.com/dev-core-busy/jarvis" \
      org.opencontainers.image.licenses="AGPL-3.0" \
      org.opencontainers.image.authors="Andreas Bender"

# ── System-Pakete (Openbox statt Cinnamon fuer schnellen Build) ──────────────
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    # Python
    python3 python3-venv python3-pip \
    # Build-Tools (fuer python-pam + dlib/face_recognition Kompilierung)
    build-essential libpam0g-dev cmake libboost-all-dev \
    # X11 / Cinnamon Desktop
    xvfb x11vnc xterm \
    cinnamon-core cinnamon-session \
    dbus-x11 at-spi2-core feh \
    # Openbox als Fallback
    openbox \
    # Browser (fuer Desktop-Automation, CDP via --remote-debugging-port)
    chromium \
    # noVNC / websockify
    novnc websockify \
    # System-Tools
    curl wget ca-certificates procps xdotool gnupg \
    # SSL
    openssl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# ── Node.js 20 (fuer WhatsApp-Bridge / Baileys v7) ──────────────────────────
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# ── Python venv + Abhaengigkeiten ────────────────────────────────────────────
WORKDIR /app
COPY requirements.txt .

RUN python3 -m venv /venv \
    && /venv/bin/pip install --upgrade pip \
    && /venv/bin/pip install --no-cache-dir 'setuptools<75' \
    && /venv/bin/pip install --no-cache-dir -r requirements.txt

ENV PATH="/venv/bin:$PATH"

# ── App-Code kopieren ────────────────────────────────────────────────────────
COPY backend/    ./backend/
COPY frontend/   ./frontend/
COPY skills/     ./skills/
COPY data/       ./data/
COPY services/   ./services/

# ── WhatsApp-Bridge Node-Abhaengigkeiten installieren ────────────────────────
RUN cd /app/services/whatsapp-bridge && npm install --omit=dev

# ── Daten-Volume vorbereiten ─────────────────────────────────────────────────
RUN mkdir -p /app/data/logs /app/data/knowledge /app/data/vision/faces /app/certs

# ── Wallpaper ────────────────────────────────────────────────────────────────
COPY docker/jarvis-wallpaper.jpg /usr/share/backgrounds/jarvis.jpg

# ── Cinnamon-Upgrade-Skript (wird beim ersten Start ausgefuehrt) ─────────────
COPY docker/install-cinnamon.sh /usr/local/bin/install-cinnamon.sh
RUN chmod +x /usr/local/bin/install-cinnamon.sh

# ── Docker-spezifischer Entrypoint ──────────────────────────────────────────
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# ── Ports ────────────────────────────────────────────────────────────────────
EXPOSE 80 443 6080

# ── Volumes fuer persistente Daten ───────────────────────────────────────────
VOLUME ["/app/data", "/app/certs"]

# ── Umgebungsvariablen (Defaults) ────────────────────────────────────────────
ENV JARVIS_DOCKER=1 \
    JARVIS_PASSWORD=jarvis \
    DISPLAY=:1 \
    PYTHONUNBUFFERED=1

ENTRYPOINT ["/entrypoint.sh"]
