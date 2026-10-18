#!/bin/bash
# Root-eigene Laufzeit des Root-Brokers installieren bzw. aktualisieren.
#
# WARUM (Befund K1, BSI-Abgleich 2026-09-29): der Broker lief als root aus
# /opt/jarvis – und /opt/jarvis gehoert dem Dienstbenutzer `jarvis`. Wer als
# jarvis backend/broker/*.py, das venv oder start_jarvis_root.sh aenderte, hatte
# nach dem naechsten Broker-Neustart root. Jetzt laeuft er aus $ZIEL (root:root,
# fuer niemanden sonst beschreibbar) mit dem System-Python.
#
# QUELLEN (in /etc/jarvis/broker.conf, root-eigen):
#   github  (Vorgabe) – root holt den Stand SELBST aus dem Repository. Der
#           Dienstbenutzer kann nur ausloesen, DASS aktualisiert wird, nicht
#           WAS: sein Arbeitsbaum ist nicht die Quelle.
#           Seit 2026-09-30 ist das Repository PRIVAT. Anonym per https geht
#           dann nichts mehr; der Weg ist ein Deploy Key (nur lesend, an dieses
#           eine Repository gebunden), eingerichtet mit deploy_key_einrichten.sh:
#             REPO=git@github.com:dev-core-busy/jarvis.git
#             SCHLUESSEL=/root/.ssh/jarvis_broker_deploy   (root, 0600)
#             SSH_443=0|1   (1 = ueber ssh.github.com:443, falls Port 22 zu ist)
#           Der Host-Schluessel von GitHub ist fest verankert ($KNOWN, root-eigen)
#           – kein Vertrauen beim ersten Kontakt, keine Rueckfrage.
#
# HERKUNFT (Befund H1, 2026-09-30): installiert wird nur ein Stand, dessen
# Spitze mit einem Schluessel aus $SIGNERS (root-eigen, gesetzt von
# signatur_einrichten.sh) signiert ist. Sonst bricht die Installation ab und die
# bestehende bleibt. Der Transport (SSH) sagt nur, dass es GitHub ist – nicht,
# WER den Stand dort hingelegt hat. Fehlt $SIGNERS ganz, wird installiert, aber
# jeder Lauf warnt (Bestand vor der Einrichtung).
#   lokal   – Kopie aus $JARVIS_DIR. Nur fuer Entwicklungsrechner (DEV): damit
#           ist die Trennung wieder so schwach wie vorher, und jeder Start sagt
#           das im Journal.
#
# Aufruf (root):
#   broker_installieren.sh [--quelle github|lokal] [--jarvis-dir DIR]
# Exit: 0 = neu installiert · 3 = bereits aktuell · 1 = Fehler (bestehende
#       Installation bleibt unangetastet) · 2 = falscher Aufruf
#
# ⚠ ALS ROOT WIRD IM ARBEITSBAUM KEIN git AUFGERUFEN. .git/config gehoert dem
#   Dienstbenutzer, und `core.fsmonitor`/`core.pager`/Hooks fuehren beliebige
#   Befehle aus – ein `git rev-parse` als root waere derselbe Weg zu root.

set -u

ZIEL="${JARVIS_BROKER_INSTALL_DIR:-/usr/local/lib/jarvis-broker}"
KONF="${JARVIS_BROKER_KONF:-/etc/jarvis/broker.conf}"
CACHE="${JARVIS_BROKER_CACHE:-/var/lib/jarvis-broker/quelle}"
KNOWN="${JARVIS_BROKER_KNOWN_HOSTS:-/etc/jarvis/github_known_hosts}"
SIGNERS="${JARVIS_BROKER_SIGNERS:-/etc/jarvis/allowed_signers}"
ADMIN_BIN="${JARVIS_BROKER_ADMIN_BIN:-/usr/local/sbin/jarvis-broker-admin}"

QUELLE="github"
REPO="https://github.com/dev-core-busy/jarvis.git"
BRANCH="master"
JARVIS_DIR="/opt/jarvis"
SCHLUESSEL=""
SSH_443="0"

meldung() { echo "[Broker-Installation] $*"; }
fehler()  { echo "[Broker-Installation] FEHLER: $*" >&2; exit 1; }

# Gewoehnliche Datei (kein Link), root-eigen, keine Rechtebits aus $2 gesetzt.
# Ein Schluessel oder Host-Anker, den ein anderer als root aendern kann, ist
# keiner: wer den Anker tauscht, liefert dem Broker seinen eigenen Code.
# (Einen Link lehnt schon die Rechtepruefung ab – stat ohne -L sieht den Link
# selbst, Modus 0777; das -L steht als Guertel davor.)
root_privat() {
    [ -f "$1" ] && [ ! -L "$1" ] && [ "$(stat -c '%u' "$1")" = "0" ] \
        && [ $(( 0$(stat -c '%a' "$1") & $2 )) -eq 0 ]
}

[ "$(id -u)" = "0" ] || { echo "Nur als root." >&2; exit 2; }

# ── Konfiguration: nur aus einer root-eigenen, fremd nicht beschreibbaren Datei,
# und nur bekannte Schluessel. `source` waere Codeausfuehrung.
if [ -f "$KONF" ]; then
    if [ "$(stat -c '%u' "$KONF")" = "0" ] && [ $(( 0$(stat -c '%a' "$KONF") & 022 )) -eq 0 ]; then
        while IFS='=' read -r k v; do
            v="${v%\"}"; v="${v#\"}"
            case "$k" in
                QUELLE)     [[ "$v" =~ ^(github|lokal)$ ]] && QUELLE="$v" ;;
                REPO)       [[ "$v" =~ ^(https://[A-Za-z0-9./_-]+|git@github\.com:[A-Za-z0-9._-]+/[A-Za-z0-9._-]+\.git)$ ]] && REPO="$v" ;;
                SCHLUESSEL) [[ "$v" =~ ^/[A-Za-z0-9._/-]+$ ]] && SCHLUESSEL="$v" ;;
                SSH_443)    [[ "$v" =~ ^[01]$ ]] && SSH_443="$v" ;;
                BRANCH)     [[ "$v" =~ ^[A-Za-z0-9._/-]+$ ]] && BRANCH="$v" ;;
                JARVIS_DIR) [[ "$v" =~ ^/[A-Za-z0-9._/-]+$ ]] && JARVIS_DIR="$v" ;;
            esac
        done < <(grep -E '^[A-Z0-9_]+=' "$KONF")
    else
        meldung "WARNUNG: $KONF ist nicht root-eigen oder fremd beschreibbar – ignoriert."
    fi
fi

while [ $# -gt 0 ]; do
    case "$1" in
        --quelle)     QUELLE="${2:-}"; shift 2 ;;
        --jarvis-dir) JARVIS_DIR="${2:-}"; shift 2 ;;
        *) echo "Unbekanntes Argument: $1" >&2; exit 2 ;;
    esac
done
[[ "$QUELLE" =~ ^(github|lokal)$ ]] || { echo "--quelle github|lokal" >&2; exit 2; }
PY="$(command -v python3 || true)"
[ -n "$PY" ] || fehler "python3 fehlt"

# ── Quelle bereitstellen ────────────────────────────────────────────────────
COMMIT=""
if [ "$QUELLE" = "github" ]; then
    export HOME=/root GIT_TERMINAL_PROMPT=0 GIT_CONFIG_NOSYSTEM=1
    if [[ "$REPO" == git@* ]]; then
        [ -n "$SCHLUESSEL" ] || fehler "REPO per SSH, aber kein SCHLUESSEL in $KONF – bestehende Installation bleibt."
        root_privat "$SCHLUESSEL" 077 \
            || fehler "Schluessel $SCHLUESSEL fehlt oder ist nicht root-eigen/privat (0600) – bestehende Installation bleibt."
        root_privat "$KNOWN" 022 \
            || fehler "Host-Anker $KNOWN fehlt oder ist fremd beschreibbar – bestehende Installation bleibt."
        # -F /dev/null: keine ssh_config (auch nicht /root/.ssh/config) redet mit.
        SSH="ssh -F /dev/null -i $SCHLUESSEL -o IdentitiesOnly=yes -o BatchMode=yes"
        SSH="$SSH -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$KNOWN -o GlobalKnownHostsFile=/dev/null"
        SSH="$SSH -o HostKeyAlias=github.com -o HostKeyAlgorithms=ssh-ed25519 -o ConnectTimeout=20"
        [ "$SSH_443" = "1" ] && SSH="$SSH -o HostName=ssh.github.com -o Port=443"
        export GIT_SSH_COMMAND="$SSH"
    fi
    mkdir -p -m 0700 "$(dirname "$CACHE")"
    # Ein Cache, der nicht root gehoert, ist keiner – neu holen.
    if [ -e "$CACHE" ] && [ "$(stat -c '%u' "$CACHE")" != "0" ]; then rm -rf "$CACHE"; fi
    if [ -d "$CACHE/.git" ]; then
        # Die Adresse steht im Cache selbst – ohne das holte ein Bestand nach dem
        # Umstieg https -> SSH weiter von der alten (und scheiterte).
        git -C "$CACHE" remote set-url origin "$REPO" \
            || fehler "Adresse im Cache nicht umstellbar – bestehende Installation bleibt."
        timeout 120 git -C "$CACHE" fetch -q --depth 1 origin "$BRANCH" \
            && git -C "$CACHE" reset -q --hard FETCH_HEAD \
            && git -C "$CACHE" clean -qfdx \
            || fehler "Abruf von $REPO ($BRANCH) gescheitert – bestehende Installation bleibt."
    else
        rm -rf "$CACHE"
        timeout 180 git clone -q --depth 1 --branch "$BRANCH" "$REPO" "$CACHE" \
            || fehler "Klonen von $REPO ($BRANCH) gescheitert – bestehende Installation bleibt."
    fi
    # Herkunft pruefen (H1) – an der Spitze, die gleich installiert wird. Die
    # Signatur deckt Baum und Vorgaenger ab; unsignierte Commits DARUNTER sind
    # damit mitverbuergt. ssh-keygen fest, nicht ueber PATH.
    if [ -e "$SIGNERS" ] || [ -L "$SIGNERS" ]; then
        root_privat "$SIGNERS" 022 \
            || fehler "Signatur-Anker $SIGNERS ist nicht root-eigen oder fremd beschreibbar – bestehende Installation bleibt."
        if ! git -C "$CACHE" -c gpg.ssh.allowedSignersFile="$SIGNERS" -c gpg.ssh.program=/usr/bin/ssh-keygen \
                verify-commit HEAD >/dev/null 2>&1; then
            fehler "Stand $(git -C "$CACHE" rev-parse --short HEAD 2>/dev/null) ist nicht mit einem zugelassenen Schluessel signiert (BSI H1) – bestehende Installation bleibt."
        fi
        meldung "Signatur geprueft ($(git -C "$CACHE" rev-parse --short HEAD 2>/dev/null))"
    else
        meldung "WARNUNG: kein Signatur-Anker $SIGNERS – Herkunft des Stands NICHT geprueft (BSI H1). Einrichten: signatur_einrichten.sh"
    fi
    COMMIT="$(git -C "$CACHE" rev-parse HEAD 2>/dev/null)"
    SRC="$CACHE"
else
    SRC="$JARVIS_DIR"
    meldung "WARNUNG: Quelle 'lokal' – der Broker-Code stammt aus $SRC, das dem Dienstbenutzer gehoert. Nur fuer Entwicklungsrechner."
fi
[ -f "$SRC/backend/broker/daemon.py" ] || fehler "Broker-Code fehlt in $SRC"
[ -f "$SRC/start_jarvis_root.sh" ] || fehler "start_jarvis_root.sh fehlt in $SRC"

# ── In ein NEUES Verzeichnis kopieren, pruefen, dann atomar tauschen ─────────
NEU="$ZIEL.neu.$$"
rm -rf "$NEU"
mkdir -m 0755 "$NEU" || fehler "kann $NEU nicht anlegen"
# Symbolische Links in der Quelle: ABBRUCH (Code-Review 2026-10-18). Bis dahin
# loeste `tar -h` sie auf – im Modus 'lokal' gehoert die Quelle dem
# Dienstbenutzer, ein Link backend/x -> /etc/shadow waere als INHALT kopiert und
# unten per chmod -R go=rX fuer alle lesbar gemacht worden. Ohne -h wuerde der
# Link selbst kopiert und zeigte in die beschreibbare Welt. Beides darf nicht
# sein; das Repo enthaelt keine Links.
LINKS=$(find "$SRC/backend" "$SRC/deploy" "$SRC/start_jarvis_root.sh" "$SRC/jarvis.service" \
        -type l 2>/dev/null | head -5)
if [ -n "$LINKS" ]; then
    rm -rf "$NEU"; fehler "Symbolische Links in der Quelle – Abbruch: $(echo $LINKS)"
fi
# Beide tar einzeln pruefen: ohne pipefail zaehlte nur der Exit des zweiten.
tar -C "$SRC" -cf - --exclude='__pycache__' --exclude='*.pyc' \
        backend deploy start_jarvis_root.sh jarvis.service 2>/dev/null \
     | tar -C "$NEU" -xf - --no-same-owner --no-same-permissions
TAR_RC=("${PIPESTATUS[@]}")
if [ "${TAR_RC[0]}" != "0" ] || [ "${TAR_RC[1]}" != "0" ]; then
    rm -rf "$NEU"; fehler "Kopieren aus $SRC gescheitert (tar: ${TAR_RC[*]})"
fi
chown -R root:root "$NEU"
chmod -R u=rwX,go=rX "$NEU"
chmod 0755 "$NEU/start_jarvis_root.sh"
find "$NEU/deploy" -name '*.sh' -exec chmod 0755 {} +

# Probe: laesst sich der Broker mit dem System-Python ueberhaupt laden?
# OHNE Bytecode: die .pyc-Dateien landeten sonst in $NEU und im Hash darunter –
# jeder Lauf hielte den Stand fuer neu (auf DEV gemessen, 2026-09-29).
if ! ( cd "$NEU" && env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin PYTHONDONTWRITEBYTECODE=1 JARVIS_PROJECT_ROOT="$JARVIS_DIR" \
        "$PY" -c 'import backend.broker.daemon, backend.broker.admin, backend.broker.ops' ) >/dev/null 2>&1; then
    FEHL="$(cd "$NEU" && env -i PATH=/usr/sbin:/usr/bin PYTHONDONTWRITEBYTECODE=1 JARVIS_PROJECT_ROOT="$JARVIS_DIR" "$PY" -c 'import backend.broker.daemon' 2>&1 | tail -3)"
    rm -rf "$NEU"; fehler "Neuer Stand laedt nicht mit $PY: $FEHL"
fi

HASH="$(cd "$NEU" && find . -type f ! -path '*/__pycache__/*' -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-16)"
ALT_HASH=""
[ -f "$ZIEL/STAND" ] && ALT_HASH="$("$PY" -c 'import json,sys;print(json.load(open(sys.argv[1])).get("hash",""))' "$ZIEL/STAND" 2>/dev/null)"
if [ -n "$ALT_HASH" ] && [ "$ALT_HASH" = "$HASH" ]; then
    rm -rf "$NEU"
    meldung "aktuell ($QUELLE${COMMIT:+ ${COMMIT:0:10}}, $HASH)"
    exit 3
fi

"$PY" - "$NEU/STAND" "$QUELLE" "$COMMIT" "$HASH" "$REPO" "$BRANCH" "$SRC" <<'PYEOF'
import json, sys, time
ziel, quelle, commit, h, repo, branch, src = sys.argv[1:8]
json.dump({"quelle": quelle, "commit": commit, "hash": h,
           "repo": repo if quelle == "github" else "", "branch": branch if quelle == "github" else "",
           "aus": src, "installiert": time.strftime("%Y-%m-%d %H:%M:%S")},
          open(ziel, "w"), ensure_ascii=False, indent=1)
PYEOF
chmod 0644 "$NEU/STAND"

rm -rf "$ZIEL.alt"
[ -d "$ZIEL" ] && mv "$ZIEL" "$ZIEL.alt"
mv "$NEU" "$ZIEL" || { [ -d "$ZIEL.alt" ] && mv "$ZIEL.alt" "$ZIEL"; fehler "Tausch gescheitert"; }
rm -rf "$ZIEL.alt"

# Root-Konsole fuer Freigaben (liegt ausserhalb von $ZIEL, zeigt hinein)
cat > "$ADMIN_BIN.tmp" <<EOF
#!/bin/sh
# Erzeugt von broker_installieren.sh – Freigaben der Root-Operationen verwalten.
cd "$ZIEL" || exit 1
exec "$PY" -m backend.broker.admin "\$@"
EOF
chown root:root "$ADMIN_BIN.tmp" && chmod 0755 "$ADMIN_BIN.tmp" && mv "$ADMIN_BIN.tmp" "$ADMIN_BIN"

meldung "installiert nach $ZIEL ($QUELLE${COMMIT:+ ${COMMIT:0:10}}, $HASH)"
exit 0
