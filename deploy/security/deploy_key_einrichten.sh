#!/bin/bash
# Deploy Keys fuer das PRIVATE GitHub-Repository einrichten (als root).
#
# WARUM (2026-09-30): das Repository ist privat. Beide Update-Wege holten
# anonym per https und scheitern seitdem still:
#   1. App-Update (update_manager.py, als `jarvis`): git fetch/pull im Baum
#   2. Broker-Kopie (broker_installieren.sh, als root, Befund K1): root holt
#      den Broker-Code SELBST – gerade nicht aus dem Baum von `jarvis`
#
# Deshalb ZWEI Schluessel, je Identitaet einer: der von root liegt in
# /root/.ssh und ist fuer `jarvis` unlesbar – sonst koennte `jarvis` bestimmen,
# was root als Broker-Code holt (derselbe Weg zu root wie K1). Beide sind bei
# GitHub als Deploy Key NUR LESEND an dieses eine Repository gebunden, laufen
# nicht ab und haengen an keinem Personenkonto.
#
# Der Host-Schluessel von GitHub steht hier FEST (ed25519, Fingerabdruck
# SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU, gleich auf Port 22 und
# ssh.github.com:443) – kein Vertrauen beim ersten Kontakt.
#
# Aufruf (root, aus einer root-eigenen Kopie – z. B.
# /usr/local/lib/jarvis-broker/deploy/security/ oder nach /root kopiert):
#   deploy_key_einrichten.sh [--name NAME] [--jarvis-dir DIR] [--port443]
#                                                             einrichten
#   NAME benennt den Server in Schluessel-Kommentar und GitHub-Titel
#   (jarvis-broker@NAME, jarvis-update@NAME), z. B. jarvis-dev / jarvis-echt.
#   Vorgabe: hostname -s – der sagt auf DEV "jarvis" und unterscheidet nichts.
#   deploy_key_einrichten.sh --pruefen [--jarvis-dir DIR]     nur pruefen
# Idempotent: vorhandene Schluessel bleiben, Konfiguration wird ersetzt.
# Exit: 0 = ok · 1 = Fehler · 2 = falscher Aufruf · 4 = Schluessel noch nicht
#       bei GitHub eingetragen (nur --pruefen)

set -u

REPO="git@github.com:dev-core-busy/jarvis.git"
JARVIS_DIR="/opt/jarvis"
SERVICE_USER="jarvis"
KONF="${JARVIS_BROKER_KONF:-/etc/jarvis/broker.conf}"
KNOWN="${JARVIS_BROKER_KNOWN_HOSTS:-/etc/jarvis/github_known_hosts}"
ROOT_KEY="${JARVIS_BROKER_DEPLOY_KEY:-/root/.ssh/jarvis_broker_deploy}"
GITHUB_HOSTKEY="github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"
PORT443=0
PRUEFEN=0
NAME="$(hostname -s)"

meldung() { echo "[Deploy-Key] $*"; }
fehler()  { echo "[Deploy-Key] FEHLER: $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --jarvis-dir) JARVIS_DIR="${2:-}"; shift 2 ;;
        --port443)    PORT443=1; shift ;;
        --name)       NAME="${2:-}"; shift 2 ;;
        --pruefen)    PRUEFEN=1; shift ;;
        *) echo "Unbekanntes Argument: $1" >&2; exit 2 ;;
    esac
done
[[ "$JARVIS_DIR" =~ ^/[A-Za-z0-9._/-]+$ ]] || { echo "--jarvis-dir ungueltig" >&2; exit 2; }
[[ "$NAME" =~ ^[A-Za-z0-9._-]{1,40}$ ]] || { echo "--name ungueltig" >&2; exit 2; }
[ "$(id -u)" = "0" ] || { echo "Nur als root." >&2; exit 2; }

# Als root ausgefuehrt, darf dieses Skript nicht aus einem Ort kommen, den ein
# anderer aendern kann – sonst ist es selbst der Weg zu root (K1).
SELF="$(readlink -f "$0")"
for p in "$SELF" "$(dirname "$SELF")"; do
    if [ "$(stat -c '%u' "$p")" != "0" ] || [ $(( 0$(stat -c '%a' "$p") & 022 )) -ne 0 ]; then
        fehler "$p gehoert nicht root oder ist fremd beschreibbar. Aus der root-eigenen Kopie starten (/usr/local/lib/jarvis-broker/deploy/security/) oder vorher nach /root kopieren."
    fi
done

JH="$(getent passwd "$SERVICE_USER" | cut -d: -f6)"
[ -n "$JH" ] && [ -d "$JH" ] || fehler "Home von $SERVICE_USER nicht gefunden"

# Dieselben Optionen wie broker_installieren.sh (tests/test_deploy_key.py
# vergleicht beide).
root_ssh() {
    local s="ssh -F /dev/null -i $ROOT_KEY -o IdentitiesOnly=yes -o BatchMode=yes"
    s="$s -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$KNOWN -o GlobalKnownHostsFile=/dev/null"
    s="$s -o HostKeyAlias=github.com -o HostKeyAlgorithms=ssh-ed25519 -o ConnectTimeout=20"
    [ "$1" = "1" ] && s="$s -o HostName=ssh.github.com -o Port=443"
    echo "$s"
}

konf_wert() { grep -E "^$1=" "$KONF" 2>/dev/null | tail -1 | cut -d= -f2-; }

# ── Pruefen ────────────────────────────────────────────────────────────────
# Die AUSSAGEKRAEFTIGE Zeile einer git/ssh-Ausgabe. `tail -1` ist die
# schlechteste Wahl: bei einem gelungenen ls-remote steht dort die SHA. Am
# 2026-10-11 gemessen meldete der Fehlerzweig deshalb woertlich
#   "jarvis (Update): FEHLER - 41fe61f33ff4... refs/heads/master"
# also den ERFOLG als Fehler - richtig erkannt und nicht zu deuten. Genau
# dieselbe Falle wie die letzte Zeile eines Java-Stacktrace (Register).
fehlerzeile() {
    grep -m1 -E "not accessible|Permission denied|Host key verification|fatal:|Could not resolve|Connection (closed|refused|timed out)" <<<"$1" \
        || tail -1 <<<"$1"
}
# GELUNGEN IST NICHT GESUND: eine unlesbare Identitaet heisst, dass nicht
# core.sshCommand getragen hat, sondern die ~/.ssh/config als Rueckfall
# einsprang. Das ist ein Erfolg aus zweiter Reihe und endet, sobald die
# config fehlt - dann laeuft ein stiller fetch-Fehler in einen
# "reset --hard" gegen den ALTEN origin/master.
zweite_reihe() { grep -q "not accessible" <<<"$1"; }
# Die SHA aus der Ausgabe ziehen, statt ${R:0:10} zu nehmen: steht eine
# Warnung davor, ist der Praefix nicht die SHA.
sha10() { grep -oE "^[0-9a-f]{40}" <<<"$1" | head -1 | cut -c1-10; }

pruefe_abruf() {   # $1 = Beschriftung, $2 = Ausgabe von ls-remote
    local was="$1" R="$2"
    if grep -qE "^[0-9a-f]{40}[[:space:]]+refs/heads/master" <<<"$R"; then
        if zweite_reihe "$R"; then
            meldung "$was DEFEKT – $(fehlerzeile "$R")"
            meldung "$(printf '%*s' ${#was} '') Abruf gelang nur ueber ~/.ssh/config als Rueckfall;"
            meldung "$(printf '%*s' ${#was} '') core.sshCommand zeigt auf einen unlesbaren Schluessel."
            return 1
        fi
        meldung "$was OK  – master $(sha10 "$R")"
        return 0
    fi
    if grep -q "Permission denied (publickey)\|Repository not found" <<<"$R"; then
        meldung "$was Schluessel noch nicht bei GitHub eingetragen"
        return 4
    fi
    meldung "$was FEHLER – $(fehlerzeile "$R")"
    return 1
}

if [ "$PRUEFEN" = "1" ]; then
    RC=0
    P="$(konf_wert SSH_443)"; [ "$P" = "1" ] || P=0
    R="$(GIT_TERMINAL_PROMPT=0 GIT_SSH_COMMAND="$(root_ssh "$P")" timeout 60 \
         git ls-remote "$REPO" refs/heads/master 2>&1)"
    pruefe_abruf "root (Broker):  " "$R" || { r=$?; [ "$r" = 4 ] && [ "$RC" = 0 ] && RC=4 || RC=$r; }
    R="$(runuser -u "$SERVICE_USER" -- env GIT_TERMINAL_PROMPT=0 timeout 60 \
         git -C "$JARVIS_DIR" ls-remote origin refs/heads/master 2>&1)"
    pruefe_abruf "$SERVICE_USER (Update):" "$R" || { r=$?; [ "$r" = 4 ] && [ "$RC" = 0 ] && RC=4 || RC=$r; }
    exit $RC
fi

# ── root: Schluessel, Host-Anker, broker.conf ─────────────────────────────
command -v ssh-keygen >/dev/null || fehler "ssh-keygen fehlt"
# Nur anlegen, was fehlt – ein bestehendes /etc/jarvis (Policy, Audit) behaelt
# seine Rechte.
[ -d "$(dirname "$ROOT_KEY")" ] || install -d -m 0700 -o root -g root "$(dirname "$ROOT_KEY")"
[ -d "$(dirname "$KNOWN")" ] || install -d -m 0755 -o root -g root "$(dirname "$KNOWN")"
if [ ! -f "$ROOT_KEY" ]; then
    ssh-keygen -q -t ed25519 -N "" -C "jarvis-broker@$NAME" -f "$ROOT_KEY" \
        || fehler "Schluessel fuer root nicht erzeugbar"
fi
chown root:root "$ROOT_KEY" "$ROOT_KEY.pub"; chmod 0600 "$ROOT_KEY"; chmod 0644 "$ROOT_KEY.pub"

printf '%s\n' "$GITHUB_HOSTKEY" > "$KNOWN.tmp" && chown root:root "$KNOWN.tmp" \
    && chmod 0644 "$KNOWN.tmp" && mv "$KNOWN.tmp" "$KNOWN" || fehler "Host-Anker nicht schreibbar"

python3 - "$KONF" "$REPO" "$ROOT_KEY" "$PORT443" <<'PYEOF' || fehler "$KONF nicht schreibbar"
import os, sys
konf, repo, key, p443 = sys.argv[1:5]
alt = open(konf).read().splitlines() if os.path.exists(konf) else []
bleibt = [z for z in alt if not z.split("=", 1)[0] in ("REPO", "SCHLUESSEL", "SSH_443")]
neu = bleibt + ["REPO=" + repo, "SCHLUESSEL=" + key, "SSH_443=" + p443]
tmp = konf + ".tmp"
with open(tmp, "w") as f:
    f.write("\n".join(neu) + "\n")
os.chown(tmp, 0, 0)
os.chmod(tmp, 0o644)
os.replace(tmp, konf)
PYEOF

# ── Dienstbenutzer: eigener Schluessel, ssh-config, Remote ─────────────────
# ALLES als $SERVICE_USER – root schreibt nichts in dessen Home und ruft kein
# git in dessen Baum auf (.git/config gehoert ihm, siehe broker_installieren.sh).
runuser -u "$SERVICE_USER" -- bash -s -- "$JH" "$PORT443" "$REPO" "$JARVIS_DIR" "$GITHUB_HOSTKEY" "$NAME" <<'EOF' \
    || fehler "Einrichtung fuer $SERVICE_USER gescheitert"
set -eu
H="$1"; P443="$2"; REPO="$3"; DIR="$4"; HOSTKEY="$5"; NAME="$6"
umask 077
mkdir -p "$H/.ssh"; chmod 0700 "$H/.ssh"
K="$H/.ssh/jarvis_deploy"
[ -f "$K" ] || ssh-keygen -q -t ed25519 -N "" -C "jarvis-update@$NAME" -f "$K"
printf '%s\n' "$HOSTKEY" > "$H/.ssh/github_known_hosts"
CFG="$H/.ssh/config"; [ -f "$CFG" ] || : > "$CFG"; chmod 0600 "$CFG"
python3 - "$CFG" "$K" "$H/.ssh/github_known_hosts" "$P443" <<'PY'
import re, sys
cfg, key, kh, p443 = sys.argv[1:5]
a = "# >>> jarvis-deploy-key (deploy_key_einrichten.sh)"
b = "# <<< jarvis-deploy-key"
s = open(cfg).read()
s = re.sub(re.escape(a) + r".*?" + re.escape(b) + r"\n?", "", s, flags=re.S)
block = [a, "Host github.com",
         "    HostName " + ("ssh.github.com" if p443 == "1" else "github.com"),
         "    Port " + ("443" if p443 == "1" else "22"),
         "    User git", "    IdentityFile " + key, "    IdentitiesOnly yes",
         "    BatchMode yes", "    StrictHostKeyChecking yes",
         "    UserKnownHostsFile " + kh, "    HostKeyAlias github.com",
         "    HostKeyAlgorithms ssh-ed25519", b, ""]
# VORNE einfuegen: in der ssh-config gewinnt der ERSTE passende Wert.
open(cfg, "w").write("\n".join(block) + s)
PY
git -C "$DIR" remote set-url origin "$REPO"
# ⚠ DIESE Config gehoert dem Update-Weg des DIENSTBENUTZERS, nicht root.
# Bis zum 2026-10-11 stand in /opt/jarvis/.git/config von Hand
#   core.sshCommand = ssh -i /root/.ssh/jarvis_broker_deploy -o IdentitiesOnly=yes
# also der Schluessel von ROOT - fuer den Dienstbenutzer absichtlich unlesbar
# (siehe Kopf: sonst bestimmt `jarvis`, was root als Broker-Code holt, K1).
# Jeder "runuser -u jarvis -- git fetch" schrieb deshalb "Identity file ...
# not accessible: Permission denied" und gelang TROTZDEM, weil die
# ~/.ssh/config einsprang: ein Erfolg aus zweiter Reihe, zweimal im c+p
# gesehen. Das traegt nicht - und ein stiller fetch-Fehler laesst den
# folgenden "reset --hard" gegen den ALTEN origin/master laufen, was wie ein
# Erfolg aussieht (genau der Vorfall, der core.sshCommand herbrachte).
# Hier steht deshalb der Schluessel des Dienstbenutzers, samt festgenagelten
# Hostkey. Das ist KEIN Weg zu root: der privilegierte Abruf (Broker-Code)
# laeuft ueber root_ssh() mit `-F /dev/null` und liest diese Datei nie - und
# genau so muss es bleiben, denn .git/config ist fuer `jarvis` schreibbar.
git -C "$DIR" config core.sshCommand \
    "ssh -i $K -o IdentitiesOnly=yes -o UserKnownHostsFile=$H/.ssh/github_known_hosts -o StrictHostKeyChecking=yes"
EOF

meldung "eingerichtet (Port $([ "$PORT443" = 1 ] && echo '443 ueber ssh.github.com' || echo 22))."
echo
echo "Jetzt bei GitHub eintragen: Repository -> Settings -> Deploy keys -> Add deploy key"
echo "(\"Allow write access\" NICHT anhaken). Zwei Eintraege:"
echo
echo "  Titel: jarvis-broker@$NAME  (root, Broker-Kopie)"
echo "  $(cat "$ROOT_KEY.pub")"
echo
echo "  Titel: jarvis-update@$NAME  ($SERVICE_USER, App-Update)"
echo "  $(cat "$JH/.ssh/jarvis_deploy.pub")"
echo
echo "Danach: $SELF --pruefen"
exit 0
