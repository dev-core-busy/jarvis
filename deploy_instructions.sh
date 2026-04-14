#!/bin/bash
# Deployt data/instructions/*.md auf den Server.
# Platzhalter werden beim Kopieren durch echte Werte ersetzt.
# Sensible Werte stehen NUR hier (nicht im Repo).

set -e

SERVER_IP="191.100.144.1"
SSH_KEY_PATH="/c/users/bender/.ssh/id_rsa"
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
    # Beide Pfade
    $SCP "$tmp" "root@$SERVER_IP:/opt/jarvis/data/instructions/$fname"
    $SCP "$tmp" "root@$SERVER_IP:/home/jarvis/jarvis/data/instructions/$fname"
    echo "  ✓ $fname"
done

rm -rf "$TMPDIR"

$SSH "systemctl restart jarvis.service"
echo "Service neu gestartet."
echo "Fertig."
