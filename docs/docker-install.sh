#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# Jarvis per Docker installieren bzw. aktualisieren – und am Ende die
# Zugangsdaten ANZEIGEN.
#
#   curl -fsSL https://jarvis-ai.info/downloads/docker-install.sh | bash
#
# WARUM (2026-11-21): Die Anleitung lautete "docker compose up -d, Kennwort aus
# docker logs jarvis". Auf einem Rechner mit einer frueheren Installation kam
# dabei NICHTS: compose laedt kein neues Image, wenn lokal schon ein (altes)
# ":latest" liegt – die Fassung vom April kannte das Erstkennwort noch gar nicht.
# Und das Kennwort erscheint erst, wenn das Backend laeuft, also Sekunden bis
# Minuten nach "up -d". Deshalb: erst pull, dann warten, dann das Ergebnis
# selbst ausgeben – inklusive der Faelle "eigenes Kennwort schon vergeben" und
# "Kennwort per JARVIS_PASSWORD vorgegeben".
#
# Arbeitet im aktuellen Verzeichnis. Eine vorhandene docker-compose.yml bleibt
# unangetastet (eigene Anpassungen), sonst wird sie heruntergeladen.
# Exit 0 = Jarvis laeuft und die Zugangsdaten wurden genannt, 1 = Fehler.
# ──────────────────────────────────────────────────────────────────────────────
set -u

COMPOSE_URL="https://jarvis-ai.info/downloads/docker-compose.yml"
CONTAINER="${JARVIS_CONTAINER:-jarvis}"
# Erster Start (Zertifikat, Desktop, Backend) dauert auf schwacher Hardware
# deutlich – grosszuegig warten, ueberschreibbar.
WARTEZEIT="${JARVIS_WARTEZEIT:-600}"

if [ -t 1 ]; then
    G=$'\033[1;32m'; R=$'\033[1;31m'; Y=$'\033[1;33m'; C=$'\033[1;36m'; B=$'\033[1m'; N=$'\033[0m'
else
    G=""; R=""; Y=""; C=""; B=""; N=""
fi
info()   { echo "${C}[Jarvis]${N} $*"; }
fehler() { echo "${R}[Jarvis] FEHLER:${N} $*" >&2; exit 1; }

# ── Voraussetzungen ─────────────────────────────────────────────────────────
command -v docker >/dev/null 2>&1 || fehler "Docker ist nicht installiert (https://docs.docker.com/engine/install/)."
docker compose version >/dev/null 2>&1 || fehler "Docker Compose fehlt (Paket docker-compose-plugin)."
docker info >/dev/null 2>&1 || fehler "Kein Zugriff auf Docker – als root oder mit sudo ausführen."

# ── Verzeichnis + docker-compose.yml ───────────────────────────────────────
# WARUM nicht einfach das aktuelle Verzeichnis (2026-11-21): stand die Shell
# in einem inzwischen geloeschten Verzeichnis, scheiterte das Schreiben der
# Datei und das Skript meldete irrefuehrend "Download fehlgeschlagen".
# Liegt hier schon eine docker-compose.yml (bestehende Installation), bleibt
# es dabei; sonst immer ein festes Verzeichnis.
if [ -f docker-compose.yml ] && [ -w . ]; then
    ZIEL="$(pwd)"
    info "Vorhandene docker-compose.yml in $ZIEL wird verwendet."
else
    ZIEL="${JARVIS_DIR:-$HOME/jarvis}"
    mkdir -p "$ZIEL" || fehler "Verzeichnis $ZIEL kann nicht angelegt werden."
    cd "$ZIEL" || fehler "Wechsel nach $ZIEL nicht möglich."
    if [ -f docker-compose.yml ]; then
        info "Vorhandene docker-compose.yml in $ZIEL wird verwendet."
    else
        info "Lade docker-compose.yml nach $ZIEL ..."
        curl -fsSL "$COMPOSE_URL" -o docker-compose.yml.neu \
            || { rm -f docker-compose.yml.neu; fehler "Download von $COMPOSE_URL fehlgeschlagen (Netz/Proxy prüfen)."; }
        mv docker-compose.yml.neu docker-compose.yml || fehler "docker-compose.yml kann in $ZIEL nicht abgelegt werden."
    fi
fi

# ── Image holen – IMMER, sonst bleibt ein altes lokales :latest stehen ─────
info "Lade das aktuelle Jarvis-Image (beim ersten Mal ca. 1,4 GB) ..."
docker compose pull || fehler "docker compose pull fehlgeschlagen."

info "Starte Jarvis ..."
docker compose up -d || fehler "docker compose up -d fehlgeschlagen."

# ── Auf das Backend warten und den Zugang ermitteln ────────────────────────
# Laeuft IM Container (dort liegen Daten und Umgebung). Reihenfolge zaehlt:
# ein schon gespeichertes eigenes Kennwort schlaegt alles andere – die Datei
# .erstkennwort bleibt nach dem Wechsel liegen und waere dann falsch.
PRUEFUNG='
import json, os
from pathlib import Path
d = Path("/app/data")
try:
    st = json.loads((d / "auth_state.json").read_text())
    if (st.get("docker_password") or {}).get("jarvis"):
        print("EIGEN"); raise SystemExit
except (OSError, ValueError, AttributeError):
    pass
try:
    from backend.standard_zugang import ist_standardkennwort
except Exception:
    print("ALT"); raise SystemExit
if not ist_standardkennwort(os.environ.get("JARVIS_PASSWORD", "")):
    print("ENV"); raise SystemExit
f = d / ".erstkennwort"
w = f.read_text().strip() if f.exists() else ""
print("ERST " + w if w else "WARTEN")
'

info "Warte, bis Jarvis gestartet ist (bis zu ${WARTEZEIT} s) ..."
ergebnis="WARTEN"
start=$(date +%s)
while :; do
    zustand=$(docker inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null || echo "fehlt")
    if [ "$zustand" != "running" ] && [ "$zustand" != "restarting" ]; then
        docker logs --tail 30 "$CONTAINER" 2>&1 | sed 's/^/    /'
        fehler "Container '$CONTAINER' läuft nicht (Zustand: $zustand)."
    fi
    ergebnis=$(docker exec "$CONTAINER" /venv/bin/python -c "$PRUEFUNG" 2>/dev/null || echo "WARTEN")
    case "$ergebnis" in
        EIGEN|ENV|ALT|ERST\ *) break ;;
    esac
    if [ $(( $(date +%s) - start )) -ge "$WARTEZEIT" ]; then
        break
    fi
    printf '.'
    sleep 3
done
echo

ip=$(hostname -I 2>/dev/null | awk '{print $1}')
[ -n "$ip" ] || ip="<server-ip>"
linie="════════════════════════════════════════════════════════════════"

echo
echo "${G}${linie}${N}"
echo "${G}  Jarvis läuft${N}   ${B}https://${ip}${N}"
echo "  (Die Zertifikatswarnung im Browser bestätigen – selbstsigniert.)"
echo "  Installationsverzeichnis: ${ZIEL}"
echo
echo "  Benutzer:  ${B}jarvis${N}"
case "$ergebnis" in
    ERST\ *)
        echo "  Kennwort:  ${Y}${B}${ergebnis#ERST }${N}"
        echo
        echo "  Beim ersten Login muss das Kennwort geändert werden."
        echo "  Später erneut anzeigen:  docker exec $CONTAINER cat /app/data/.erstkennwort"
        ;;
    EIGEN)
        echo "  Kennwort:  ${Y}das bereits selbst vergebene Kennwort${N}"
        echo
        echo "  Auf diesem Rechner liegen Daten einer früheren Jarvis-Installation;"
        echo "  das dort vergebene Kennwort gilt weiter."
        echo "  Ganz neu beginnen (${R}LÖSCHT alle Jarvis-Daten${N}):"
        echo "      cd ${ZIEL} && docker compose down -v && curl -fsSL https://jarvis-ai.info/downloads/docker-install.sh | bash"
        ;;
    ENV)
        echo "  Kennwort:  ${Y}der Wert von JARVIS_PASSWORD${N} (aus .env bzw. Umgebung)"
        echo
        echo "  Beim ersten Login muss das Kennwort geändert werden."
        ;;
    ALT)
        echo "  ${R}Das gestartete Image ist veraltet und kennt kein Erstkennwort.${N}"
        echo "  Bitte 'docker compose pull && docker compose up -d' prüfen."
        ;;
    *)
        echo "  ${R}Jarvis ist nach ${WARTEZEIT} s noch nicht fertig gestartet.${N}"
        echo "  Kennwort anzeigen, sobald der Start abgeschlossen ist:"
        echo "      docker exec $CONTAINER cat /app/data/.erstkennwort"
        echo "  Startprotokoll:  docker logs -f $CONTAINER"
        ;;
esac
echo "${G}${linie}${N}"

case "$ergebnis" in
    ERST\ *|EIGEN|ENV) exit 0 ;;
    *) exit 1 ;;
esac
