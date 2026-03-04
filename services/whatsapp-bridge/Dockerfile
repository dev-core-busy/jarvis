# ──────────────────────────────────────────────────────────────────────────────
# Jarvis WhatsApp Bridge – Docker Image
# Node.js + Baileys v7
# ──────────────────────────────────────────────────────────────────────────────
FROM node:20-slim

LABEL org.opencontainers.image.title="Jarvis WhatsApp Bridge" \
      org.opencontainers.image.source="https://github.com/dev-core-busy/jarvis"

# Chromium-Abhängigkeiten für Baileys (QR-Code-Scan etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Abhängigkeiten zuerst (besseres Layer-Caching)
COPY services/whatsapp-bridge/package*.json ./
RUN npm ci --omit=dev

# App-Code
COPY services/whatsapp-bridge/index.js ./

# Session-Volume (WhatsApp QR-Code / Auth-Daten)
VOLUME ["/app/session"]

EXPOSE 3001

ENV NODE_ENV=production \
    PORT=3001

CMD ["node", "index.js"]
