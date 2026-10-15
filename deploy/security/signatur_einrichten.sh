#!/bin/bash
# Herkunftspruefung fuer Updates einrichten (BSI H1) – als root.
#
# WARUM (2026-09-30): der Transport per Deploy Key belegt nur, dass die
# Gegenstelle GitHub ist. WER den Stand dort hingelegt hat, prueft erst die
# Signatur: installiert bzw. gezogen wird nur eine Spitze, die mit einem
# Schluessel aus /etc/jarvis/allowed_signers signiert ist.
#   - Broker-Kopie (root):   broker_installieren.sh prueft vor dem Installieren
#   - App-Update (jarvis):   update_manager uebergibt merge.verifySignatures
#   - git pull von Hand bzw. der naechtliche Agent-Auftrag: dieselbe Pruefung
#     ueber die Repo-Konfiguration von $SERVICE_USER (dieses Skript setzt sie)
#
# DER FINGERABDRUCK IST PFLICHT. Beim ersten Einrichten stammt die Datei
# allowed_signers noch UNGEPRUEFT von GitHub – wer dort schreiben kann, koennte
# seinen eigenen Schluessel hineinlegen. Der Mensch bestaetigt deshalb den
# Fingerabdruck, den er kennt; weicht die Datei ab, passiert nichts.
#
# Aufruf (root, aus einer root-eigenen Kopie, z. B.
# /usr/local/lib/jarvis-broker/deploy/security/):
#   signatur_einrichten.sh --fingerabdruck SHA256:… [--fingerabdruck …]
#                          [--signers DATEI] [--jarvis-dir DIR]
#   signatur_einrichten.sh --pruefen [--jarvis-dir DIR]
# Exit: 0 = ok · 1 = Fehler · 2 = falscher Aufruf · 4 = Spitze nicht signiert
#       (nur --pruefen)

set -u

JARVIS_DIR="/opt/jarvis"
SERVICE_USER="${JARVIS_SERVICE_USER:-jarvis}"
ZIEL="${JARVIS_SIGNATUR_ANKER:-/etc/jarvis/allowed_signers}"
SIGNERS=""
PRUEFEN=0
FPS=()

meldung() { echo "[Signatur] $*"; }
fehler()  { echo "[Signatur] FEHLER: $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --fingerabdruck) FPS+=("${2:-}"); shift 2 ;;
        --signers)       SIGNERS="${2:-}"; shift 2 ;;
        --jarvis-dir)    JARVIS_DIR="${2:-}"; shift 2 ;;
        --pruefen)       PRUEFEN=1; shift ;;
        *) echo "Unbekanntes Argument: $1" >&2; exit 2 ;;
    esac
done
[[ "$JARVIS_DIR" =~ ^/[A-Za-z0-9._/-]+$ ]] || { echo "--jarvis-dir ungueltig" >&2; exit 2; }
[ "$(id -u)" = "0" ] || { echo "Nur als root." >&2; exit 2; }

SELF="$(readlink -f "$0")"
for p in "$SELF" "$(dirname "$SELF")"; do
    if [ "$(stat -c '%u' "$p")" != "0" ] || [ $(( 0$(stat -c '%a' "$p") & 022 )) -ne 0 ]; then
        fehler "$p gehoert nicht root oder ist fremd beschreibbar. Aus der root-eigenen Kopie starten (/usr/local/lib/jarvis-broker/deploy/security/) oder vorher nach /root kopieren."
    fi
done

GIT_SIG=(-c "gpg.ssh.allowedSignersFile=$ZIEL" -c gpg.ssh.program=/usr/bin/ssh-keygen)

# ── Pruefen ────────────────────────────────────────────────────────────────
if [ "$PRUEFEN" = "1" ]; then
    [ -f "$ZIEL" ] || fehler "kein Anker $ZIEL – erst einrichten"
    RC=0
    CACHE="${JARVIS_BROKER_CACHE:-/var/lib/jarvis-broker/quelle}"
    QUELLE="$(grep -E '^QUELLE=' "${JARVIS_BROKER_KONF:-/etc/jarvis/broker.conf}" 2>/dev/null | tail -1 | cut -d= -f2)"
    if [ "$QUELLE" = "lokal" ]; then
        # DEV: die Broker-Kopie kommt aus dem Arbeitsbaum, nicht von GitHub –
        # es gibt nichts zu pruefen, und ein alter Cache daneben sagt nichts.
        meldung "Broker-Kopie: Quelle lokal (Entwicklung) – keine Signaturpruefung"
    elif [ -d "$CACHE/.git" ]; then
        if git -C "$CACHE" "${GIT_SIG[@]}" verify-commit HEAD >/dev/null 2>&1; then
            meldung "Broker-Kopie ($(git -C "$CACHE" rev-parse --short HEAD)): signiert"
        else
            meldung "Broker-Kopie ($(git -C "$CACHE" rev-parse --short HEAD)): NICHT signiert – naechste Installation wird abgelehnt"; RC=4
        fi
    fi
    R="$(runuser -u "$SERVICE_USER" -- env GIT_TERMINAL_PROMPT=0 bash -c '
        cd "$1" && timeout 60 git fetch -q origin master 2>&1 || exit 3
        git -c "gpg.ssh.allowedSignersFile=$2" -c gpg.ssh.program=/usr/bin/ssh-keygen \
            verify-commit FETCH_HEAD >/dev/null 2>&1 && echo "signiert $(git rev-parse --short FETCH_HEAD)" \
            || echo "UNSIGNIERT $(git rev-parse --short FETCH_HEAD)"
        echo "verifySignatures=$(git config --get merge.verifySignatures)"' _ "$JARVIS_DIR" "$ZIEL" 2>&1)"
    meldung "GitHub master: $(head -1 <<<"$R")"
    meldung "Repo-Konfiguration $SERVICE_USER: $(tail -1 <<<"$R")"
    grep -q '^UNSIGNIERT' <<<"$R" && RC=4
    grep -q '^verifySignatures=true' <<<"$R" || RC=1
    exit $RC
fi

# ── Einrichten ─────────────────────────────────────────────────────────────
[ ${#FPS[@]} -gt 0 ] || fehler "--fingerabdruck SHA256:… fehlt – ohne bestaetigten Fingerabdruck wird nichts verankert."
[ -n "$SIGNERS" ] || SIGNERS="$(dirname "$SELF")/allowed_signers"
[ -f "$SIGNERS" ] || fehler "$SIGNERS fehlt"

# Jede Zeile ausser Kommentaren muss die erwartete Form haben – nichts, was
# ssh-keygen als Option deuten koennte (cert-authority, verify-time …).
TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
N=0
while IFS= read -r z; do
    [[ -z "$z" || "$z" == \#* ]] && continue
    [[ "$z" =~ ^[A-Za-z0-9._@-]+\ namespaces=\"git\"\ ssh-ed25519\ [A-Za-z0-9+/]+=*$ ]] \
        || fehler "unerwartete Zeile in $SIGNERS: ${z:0:60}"
    FP="$(ssh-keygen -lf <(cut -d' ' -f3,4 <<<"$z") 2>/dev/null | cut -d' ' -f2)"
    OK=0; for f in "${FPS[@]}"; do [ "$f" = "$FP" ] && OK=1; done
    [ "$OK" = 1 ] || fehler "Schluessel ${FP:-?} in $SIGNERS ist nicht bestaetigt (--fingerabdruck) – nichts verankert."
    printf '%s\n' "$z" >> "$TMP"; N=$((N + 1))
done < "$SIGNERS"
[ "$N" -gt 0 ] || fehler "keine Schluesselzeile in $SIGNERS"
for f in "${FPS[@]}"; do
    grep -q . "$TMP" && ssh-keygen -lf <(cut -d' ' -f3,4 "$TMP") | grep -qF " $f " \
        || fehler "bestaetigter Fingerabdruck $f kommt in $SIGNERS nicht vor"
done

[ -d "$(dirname "$ZIEL")" ] || install -d -m 0755 -o root -g root "$(dirname "$ZIEL")"
install -o root -g root -m 0644 "$TMP" "$ZIEL.tmp" && mv "$ZIEL.tmp" "$ZIEL" || fehler "$ZIEL nicht schreibbar"
meldung "verankert: $ZIEL ($N Schluessel)"

# Repo-Konfiguration des Dienstbenutzers: git pull von Hand und der naechtliche
# Agent-Auftrag pruefen damit ebenfalls (als $SERVICE_USER, nie git als root im
# Baum – .git/config gehoert ihm).
runuser -u "$SERVICE_USER" -- git -C "$JARVIS_DIR" config merge.verifySignatures true \
    && runuser -u "$SERVICE_USER" -- git -C "$JARVIS_DIR" config gpg.ssh.allowedSignersFile "$ZIEL" \
    && runuser -u "$SERVICE_USER" -- git -C "$JARVIS_DIR" config gpg.ssh.program /usr/bin/ssh-keygen \
    || fehler "Repo-Konfiguration von $SERVICE_USER nicht setzbar"
meldung "git pull in $JARVIS_DIR prueft jetzt die Signatur."
echo "Danach: $SELF --pruefen"
exit 0
