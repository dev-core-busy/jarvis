#!/bin/bash
# Deployt data/instructions/*.md auf den Server.
# Platzhalter werden beim Kopieren durch echte Werte ersetzt.
# Interne Adressen und Schluesselpfade stehen NIE im Repo (BSI N6): das Ziel
# kommt aus JARVIS_DEV_SSH (Umgebung oder .env, siehe deploy/ziele.py und
# .env.example), der SSH-Schluessel aus JARVIS_SSH_KEY (Vorgabe ~/.ssh/id_rsa).

set -e

DEV_SSH="$(python3 "$(dirname "$0")/deploy/ziele.py" JARVIS_DEV_SSH)" || exit 2
SERVER_IP="${DEV_SSH#*@}"
SSH_KEY_PATH="${JARVIS_SSH_KEY:-$HOME/.ssh/id_rsa}"
SSH="ssh -i $SSH_KEY_PATH root@$SERVER_IP"
SCP="scp -i $SSH_KEY_PATH"

REPO_DIR="$(dirname "$0")"
SRC="$REPO_DIR/data/instructions"
TMPDIR=$(mktemp -d)

echo "Deploye data/instructions/ → $SERVER_IP ..."

for f in "$SRC"/*.md "$SRC"/*.md.disabled; do
    [ -f "$f" ] || continue
    fname=$(basename "$f")
    tmp="$TMPDIR/$fname"
    # Platzhalter ersetzen
    sed \
        -e "s|{{SERVER_IP}}|$SERVER_IP|g" \
        -e "s|{{SSH_KEY_PATH}}|$SSH_KEY_PATH|g" \
        "$f" > "$tmp"
    $SCP "$tmp" "root@$SERVER_IP:/opt/jarvis/data/instructions/$fname"
    echo "  ✓ $fname"
done

rm -rf "$TMPDIR"

$SSH "systemctl restart jarvis.service"
echo "Service neu gestartet."
echo "Fertig."
