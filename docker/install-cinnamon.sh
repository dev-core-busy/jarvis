#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# Cinnamon Desktop nachtraeglich installieren (Background-Task)
# Wird beim ersten Container-Start automatisch ausgefuehrt.
# Nach Installation: Container neu starten fuer Cinnamon-Desktop.
# ──────────────────────────────────────────────────────────────────────────────

MARKER="/app/data/.cinnamon-installed"
LOG="/app/data/logs/cinnamon-install.log"

# Bereits installiert?
if [[ -f "$MARKER" ]] && command -v cinnamon-session &>/dev/null; then
    echo "[Cinnamon] Bereits installiert."
    exit 0
fi

echo "[Cinnamon] Starte nachtraegliche Installation im Hintergrund..."
echo "[Cinnamon] Log: $LOG"
echo "[Cinnamon] Installation gestartet: $(date)" > "$LOG"

{
    export DEBIAN_FRONTEND=noninteractive

    echo "[Cinnamon] apt-get update..."
    apt-get update -qq

    echo "[Cinnamon] Installiere cinnamon-core + cinnamon-session..."
    apt-get install -y --no-install-recommends \
        cinnamon-core cinnamon-session 2>&1

    echo "[Cinnamon] Aufraeumen..."
    apt-get clean
    rm -rf /var/lib/apt/lists/*

    # Marker setzen
    touch "$MARKER"

    echo "[Cinnamon] Installation abgeschlossen: $(date)"
    echo "[Cinnamon] Bitte Container neu starten fuer Cinnamon-Desktop."
} >> "$LOG" 2>&1

echo "[Cinnamon] Fertig! Container-Neustart fuer Upgrade auf Cinnamon."
