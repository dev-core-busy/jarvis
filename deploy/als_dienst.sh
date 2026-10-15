#!/bin/bash
# Einen Befehl als Dienstbenutzer MIT dem Hauptschluessel ausfuehren (BSI M5).
#
# WARUM: seit BSI M5 sind data/.secret_key, die 2FA-Secrets, die Token in
# knowledge_sync.json und die Geheimfelder der settings.json mit dem
# Hauptschluessel /etc/jarvis/geheimnis.key verpackt. Der Dienst bekommt ihn per
# LoadCredential; ein Prozess, der nur per `runuser -u jarvis` laeuft, hat ihn
# NICHT – er sieht verpackte Werte, und ein Sitzungstoken, das er ausstellt,
# gilt im Dienst nicht (anderer Signierschluessel). Live-Proben und Werkzeuge,
# die Tokens ausstellen oder Geheimnisse brauchen, laufen deshalb hierueber.
#
# Aufruf (als root, auf dem Server):
#   bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_bsi_m5_dev.py
# Arbeitsverzeichnis ist /opt/jarvis; Exit-Code ist der des Befehls.
set -eu
JARVIS_DIR="${JARVIS_DIR:-/opt/jarvis}"
DIENST_USER="${DIENST_USER:-jarvis}"
SCHLUESSEL="${JARVIS_GEHEIMNIS_DATEI:-/etc/jarvis/geheimnis.key}"

if [ "$(id -u)" != "0" ]; then
    echo "als_dienst.sh: muss als root laufen" >&2
    exit 2
fi
if [ "$#" -eq 0 ]; then
    echo "Aufruf: als_dienst.sh <befehl> [argumente...]" >&2
    exit 2
fi
cred=()
if [ -s "$SCHLUESSEL" ]; then
    cred=(-p "LoadCredential=geheimnis:$SCHLUESSEL")
else
    echo "als_dienst.sh: $SCHLUESSEL fehlt – Befehl laeuft OHNE Hauptschluessel" >&2
fi
heim="$(getent passwd "$DIENST_USER" | cut -d: -f6)"
exec systemd-run --quiet --pipe --wait --collect \
    -p "User=$DIENST_USER" -p "Group=$DIENST_USER" -p "WorkingDirectory=$JARVIS_DIR" \
    "${cred[@]}" \
    -E "HOME=${heim:-/home/$DIENST_USER}" -E PYTHONDONTWRITEBYTECODE=1 -E PYTHONUNBUFFERED=1 \
    "$@"
