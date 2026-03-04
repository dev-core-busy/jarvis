# ──────────────────────────────────────────────────────────────────────────────
# Jarvis AI Desktop Agent – Docker Image
# Basis: Debian Bookworm Slim
# ──────────────────────────────────────────────────────────────────────────────
FROM debian:bookworm-slim

LABEL org.opencontainers.image.title="Jarvis AI Desktop Agent" \
      org.opencontainers.image.description="Autonomer KI-Agent mit Web-UI, VNC-Desktop und WhatsApp-Integration" \
      org.opencontainers.image.source="https://github.com/dev-core-busy/jarvis" \
      org.opencontainers.image.licenses="AGPL-3.0" \
      org.opencontainers.image.authors="Andreas Bender"

# ── System-Pakete ──────────────────────────────────────────────────────────────
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    # Python
    python3 python3-venv python3-pip \
    # Build-Tools (für python-pam Kompilierung)
    build-essential libpam0g-dev \
    # X11 / virtueller Desktop (XFCE4)
    xvfb x11vnc xterm \
    xfce4 xfce4-terminal dbus-x11 at-spi2-core \
    # noVNC / websockify
    novnc websockify \
    # System-Tools
    curl wget ca-certificates procps \
    # SSL
    openssl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# ── Python venv + Abhängigkeiten ───────────────────────────────────────────────
WORKDIR /app
COPY requirements.txt .

RUN python3 -m venv /venv \
    && /venv/bin/pip install --upgrade pip \
    && /venv/bin/pip install --no-cache-dir -r requirements.txt

ENV PATH="/venv/bin:$PATH"

# ── App-Code kopieren ──────────────────────────────────────────────────────────
COPY backend/    ./backend/
COPY frontend/   ./frontend/
COPY skills/     ./skills/
COPY data/       ./data/

# ── Daten-Volume vorbereiten ───────────────────────────────────────────────────
RUN mkdir -p /app/data/logs /app/data/knowledge /app/certs

# ── Wallpaper ────────────────────────────────────────────────────────────────
COPY docker/jarvis-wallpaper.jpg /usr/share/backgrounds/jarvis.jpg

# ── Docker-spezifischer Entrypoint ─────────────────────────────────────────
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# ── Ports ─────────────────────────────────────────────────────────────────────
EXPOSE 8000 6080

# ── Volumes für persistente Daten ─────────────────────────────────────────────
VOLUME ["/app/data", "/app/certs"]

# ── Umgebungsvariablen (Defaults) ──────────────────────────────────────────────
ENV JARVIS_DOCKER=1 \
    JARVIS_PASSWORD=jarvis \
    DISPLAY=:1 \
    PYTHONUNBUFFERED=1

ENTRYPOINT ["/entrypoint.sh"]
