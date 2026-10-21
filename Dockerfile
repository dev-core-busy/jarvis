# ──────────────────────────────────────────────────────────────────────────────
# Jarvis AI Desktop Agent – Docker Image
# Basis: Debian Trixie Slim – dieselbe Linie wie DEV und ECHT (Debian 13). Mit
# bookworm lief das Image auf einer anderen Python-/Bibliotheksbasis als die
# Server, ein Befund im Image sagte also nichts ueber den Betrieb (2026-10-21).
# Schneller Start mit Openbox, optionales Cinnamon-Upgrade beim ersten Start
# ──────────────────────────────────────────────────────────────────────────────
FROM debian:trixie-slim

LABEL org.opencontainers.image.title="Jarvis AI Desktop Agent" \
      org.opencontainers.image.description="Autonomer KI-Agent mit Web-UI, VNC-Desktop und WhatsApp-Integration" \
      org.opencontainers.image.source="https://github.com/dev-core-busy/jarvis" \
      org.opencontainers.image.licenses="Elastic-2.0" \
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

# ── Node.js (fuer WhatsApp-Bridge / Baileys v7) ─────────────────────────────
# Ueber DASSELBE Skript wie auf den Servern: Linie (ZIEL), Signaturschluessel
# gegen festgeschriebenen Fingerabdruck, Pin auf NodeSource. Vorher lief hier
# `curl … setup_24.x | bash -` – ein Netz-Skript als root, ungeprueft, und eine
# zweite Stelle fuer die Node-Linie, die mit dem Skript auseinanderlaufen kann.
# apt-get update VORHER: das Skript laedt selbst nur die NodeSource-Liste neu.
# JARVIS_DIR zeigt auf einen leeren Pfad – die Bridge liegt in diesem Schritt
# noch nicht im Image, ihre Module baut der npm-Schritt weiter unten.
COPY deploy/security/node_aktualisieren.sh /tmp/node_aktualisieren.sh
RUN apt-get update \
    && JARVIS_DIR=/nicht-vorhanden bash /tmp/node_aktualisieren.sh \
    && rm -f /tmp/node_aktualisieren.sh \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# ── Python venv + Abhaengigkeiten ────────────────────────────────────────────
WORKDIR /app
COPY requirements.txt .

# torch VOR requirements.txt aus dem CPU-Index: sentence-transformers zieht sonst
# das CUDA-Rad samt ~6 GB NVIDIA-Paketen in ein Image ohne GPU (siehe Hinweis in
# requirements.txt). Die Fassung steht dort EINMAL und wird hier gelesen – fehlt
# sie, bricht der Bau ab, statt still das CUDA-Rad zu holen.
# numpy ebenfalls vorab: "numpy<2.1" (VM ohne SSE4.2) hat fuer Python 3.13 KEIN
# fertiges Rad und wird aus dem Quelltext gebaut – wie auf DEV und ECHT auch
# (dort Tag linux_x86_64). Ohne Begrenzung startet meson einen Compiler je Kern;
# in einer Bau-VM mit 2 GB und 12 Kernen brach das mit "Killed signal" ab
# (2026-10-21). -j2 haelt den Bau unabhaengig vom Bau-Rechner.
RUN set -e; \
    python3 -m venv /venv; \
    /venv/bin/pip install --upgrade pip; \
    /venv/bin/pip install --no-cache-dir 'setuptools<75'; \
    TORCH="$(grep -oE '"torch==[0-9.]+\+cpu"' requirements.txt | head -1 | tr -d '"')"; \
    [ -n "$TORCH" ] || { echo "torch-Fassung (+cpu) in requirements.txt nicht gefunden" >&2; exit 1; }; \
    /venv/bin/pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "$TORCH"; \
    NUMPY="$(grep -oE '^numpy[<>=!~][^ #]*' requirements.txt | head -1)"; \
    [ -n "$NUMPY" ] || { echo "numpy-Zeile in requirements.txt nicht gefunden" >&2; exit 1; }; \
    /venv/bin/pip install --no-cache-dir -Ccompile-args=-j2 "$NUMPY"; \
    /venv/bin/pip install --no-cache-dir -r requirements.txt

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
EXPOSE 80 443

# ── Volumes fuer persistente Daten ───────────────────────────────────────────
VOLUME ["/app/data", "/app/certs"]

# ── Umgebungsvariablen (Defaults) ────────────────────────────────────────────
ENV JARVIS_DOCKER=1 \
    DISPLAY=:1 \
    PYTHONUNBUFFERED=1

ENTRYPOINT ["/entrypoint.sh"]
