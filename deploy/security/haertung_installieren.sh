#!/bin/bash
# systemd-Haertung (BSI M1) + Rotation des Broker-Audits (BSI M2) – als root.
#
# Aufruf: bash haertung_installieren.sh [JARVIS_DIR]
#   laeuft bei jedem Broker-Start (start_jarvis_root.sh, aus der root-eigenen
#   Kopie) und aus setup_broker.sh. Idempotent: schreibt nur, was sich aendert,
#   und laedt systemd nur dann neu.
#
# WARUM DROP-INS UND NICHT DIE UNIT-DATEIEN: die Units liegen auf Bestandsservern
# seit der Migration unveraendert in /etc/systemd/system – ein geaenderter
# deploy/security/jarvis.service erreicht dort nie einen Server. Ein Drop-in
# (jarvis.service.d/50-haertung.conf) legt sich ueber jede vorhandene Unit, und
# weil der Broker ihn bei jedem Start aus seiner root-eigenen Kopie schreibt,
# kommt eine Aenderung mit dem naechsten Update ueberall an.
#
# Abschalten (Notfall): HAERTUNG=aus in /etc/jarvis/broker.conf – die Drop-ins
# werden dann entfernt. Wirksam wird jede Aenderung erst mit dem naechsten
# Neustart des jeweiligen Dienstes.
#
# WAS BEWUSST FEHLT (auf DEV gemessen, 2026-10-05, systemd 257):
#   NoNewPrivileges      – die lokale Anmeldung prueft das Kennwort ueber
#                          PAM -> unix_chkpwd (setgid shadow). Mit NNP liefert
#                          es 9 (shadow nicht lesbar) statt 7: Konto "jarvis"
#                          kaeme nicht mehr herein. sudo ist fuer den
#                          Dienstbenutzer ohnehin nicht eingerichtet, und
#                          CapabilityBoundingSet nimmt einem setuid-Programm
#                          die Root-Faehigkeiten trotzdem.
#   ProtectKernelTunables, ProtectKernelLogs
#                        – bwrap kann darunter kein /proc mehr einhaengen
#                          ("Can't mount proc on /proc"): MCP-Isolation und
#                          Shell-Sandbox (BSI H10) fielen aus.
#   RestrictSUIDSGID     – bwrap scheitert ("Can't open source /").
#   ProtectHostname      – einzeln harmlos, aber ZUSAMMEN mit dem Mount-Namensraum
#                          aus ProtectSystem legt systemd /proc/sys/kernel/hostname
#                          read-only darueber, und bwrap --proc scheitert wieder
#                          ("Can't mount proc"). Erst im laufenden Dienst gesehen –
#                          die Einzelproben waren gruen. Gemessen wird deshalb
#                          immer der GANZE Drop-in (tests/live_bsi_m1_m2_dev.py).
#   PrivateTmp           – Backend, Broker und Sandbox-Laeufe teilen /tmp
#                          (Lauf-Verzeichnisse, Anhaenge, X11-Socket); ein
#                          privates /tmp truege jede Uebergabe ab.
#   RestrictNamespaces, MemoryDenyWriteExecute
#                        – bwrap braucht Namensraeume, Node/Chromium JIT.
#   PrivateDevices, ProtectClock (setzt eine Geraeteliste), ProtectProc
#                        – Vision/Audio-Geraete bzw. die Prozessuebersicht.
# Der Broker ist die Root-Komponente mit Root-Shell (shell_root, Freigabe
# per TOTP) und startet Xvfb/x11vnc/websockify sowie die Sandbox-Laeufe –
# er bekommt nur, was keine seiner Aufgaben einschraenkt. Kein UMask: er legt
# Verzeichnisse fuer das Backend und die Sandbox-Benutzer an, die diese lesen
# muessen (os.makedirs(mode=...) wird von der umask beschnitten).
set -u

JARVIS_DIR="${1:-${JARVIS_DIR:-/opt/jarvis}}"
UNIT_DIR="${JARVIS_UNIT_DIR:-/etc/systemd/system}"
LOGROTATE_DIR="${JARVIS_LOGROTATE_DIR:-/etc/logrotate.d}"
BROKER_CONF="${JARVIS_BROKER_CONF:-/etc/jarvis/broker.conf}"
AUDIT_DATEI="${JARVIS_BROKER_AUDIT:-/var/log/jarvis-broker-audit.jsonl}"

if [ "$(id -u)" != "0" ] && [ -z "${JARVIS_HAERTUNG_TEST:-}" ]; then
    echo "haertung_installieren.sh: muss als root laufen" >&2
    exit 1
fi

geaendert=0

# schreibe <ziel> <inhalt>: nur bei Abweichung, 0644 root
schreibe() {
    local ziel="$1" inhalt="$2"
    if [ -f "$ziel" ] && [ "$(cat "$ziel")" = "$inhalt" ]; then
        return 0
    fi
    mkdir -p "$(dirname "$ziel")"
    printf '%s\n' "$inhalt" > "$ziel.tmp" && chmod 0644 "$ziel.tmp" && mv "$ziel.tmp" "$ziel"
    echo "[Haertung] geschrieben: $ziel"
    geaendert=1
}

entferne() {
    if [ -f "$1" ]; then
        rm -f "$1"
        echo "[Haertung] entfernt: $1"
        geaendert=1
    fi
}

# ── Hauptschluessel fuer Geheimnisse (BSI M5) ──────────────────────────────
# Verpackt die Modulschluessel in data/ (.mailkey, .sapkey, …) und die
# Geheimfelder in settings.json (backend/geheimnis_tresor.py). Er liegt
# root-eigen AUSSERHALB von data/ – wer data/ kopiert, hat das Chiffrat, aber
# nicht den Schluessel. Der Dienstbenutzer liest die Datei NICHT selbst:
# systemd reicht ihm eine Kopie per LoadCredential (nur sein Prozess sieht sie).
#
# ⚠ UNABHAENGIG VON HAERTUNG=aus. Der Notschalter nimmt die Haertung zurueck,
# nicht den Zugang zu den Geheimnissen – ohne den Drop-in liefe der Dienst
# weiter, koennte aber kein gespeichertes Kennwort mehr oeffnen.
# ⚠ NIE UEBERSCHREIBEN: ein neuer Schluessel entwertet jedes verpackte
# Kennwort. Angelegt wird nur, wenn die Datei fehlt oder leer ist.
# ⚠ SICHERUNG: die Datei gehoert in jede Sicherung von data/ – getrennt
# aufbewahrt. Ein Restore von data/ OHNE sie heisst: alle Kennwoerter neu
# eintragen.
GEHEIMNIS_DATEI="${JARVIS_GEHEIMNIS_DATEI:-/etc/jarvis/geheimnis.key}"
# Ein Testlauf legt NIE einen echten Schluessel in /etc/jarvis an.
if [ -n "${JARVIS_HAERTUNG_TEST:-}" ] && [ -z "${JARVIS_GEHEIMNIS_DATEI:-}" ]; then
    GEHEIMNIS_DATEI="$(dirname "$UNIT_DIR")/geheimnis.key"
fi
GEHEIMNIS_DROPIN="$UNIT_DIR/jarvis.service.d/40-geheimnis.conf"
if [ ! -s "$GEHEIMNIS_DATEI" ]; then
    mkdir -p "$(dirname "$GEHEIMNIS_DATEI")"
    # Fernet-Format: 32 Zufallsbytes, url-sicheres Base64 (44 Zeichen)
    ( umask 077; head -c 32 /dev/urandom | base64 | tr '+/' '-_' > "$GEHEIMNIS_DATEI.tmp" ) \
        && chmod 0600 "$GEHEIMNIS_DATEI.tmp" && mv "$GEHEIMNIS_DATEI.tmp" "$GEHEIMNIS_DATEI" \
        && echo "[Geheimnis] Hauptschluessel angelegt: $GEHEIMNIS_DATEI – in die Sicherung aufnehmen!"
fi
if [ -s "$GEHEIMNIS_DATEI" ]; then
    if [ -z "${JARVIS_HAERTUNG_TEST:-}" ]; then
        chown root:root "$GEHEIMNIS_DATEI" 2>/dev/null
    fi
    chmod 0600 "$GEHEIMNIS_DATEI"
    schreibe "$GEHEIMNIS_DROPIN" "# BSI M5 – geschrieben von deploy/security/haertung_installieren.sh
# (bei jedem Broker-Start, unabhaengig von HAERTUNG=aus). Hauptschluessel fuer
# die Geheimnisse des Dienstes; Begruendung in backend/geheimnis_tresor.py.
[Service]
LoadCredential=geheimnis:$GEHEIMNIS_DATEI"
else
    echo "[Geheimnis] $GEHEIMNIS_DATEI fehlt und liess sich nicht anlegen – Geheimnisse bleiben unverpackt" >&2
    entferne "$GEHEIMNIS_DROPIN"
fi

modus="an"
if [ -f "$BROKER_CONF" ] && grep -qiE '^[[:space:]]*HAERTUNG[[:space:]]*=[[:space:]]*"?aus' "$BROKER_CONF"; then
    modus="aus"
fi

BACKEND_DROPIN="$UNIT_DIR/jarvis.service.d/50-haertung.conf"
BROKER_DROPIN="$UNIT_DIR/jarvis-broker.service.d/50-haertung.conf"

if [ "$modus" = "aus" ]; then
    echo "[Haertung] HAERTUNG=aus in $BROKER_CONF – Drop-ins werden entfernt." >&2
    entferne "$BACKEND_DROPIN"
    entferne "$BROKER_DROPIN"
else
    # Dienstbenutzer + dessen Home aus der Unit (Alt-Betrieb als root: keine
    # Backend-Haertung – CapabilityBoundingSet wuerde dort alles brechen)
    svc_user="$(sed -n 's/^User=//p' "$UNIT_DIR/jarvis.service" 2>/dev/null | head -1)"
    if [ -n "$svc_user" ] && [ "$svc_user" != "root" ]; then
        svc_home="$(getent passwd "$svc_user" 2>/dev/null | cut -d: -f6)"
        [ -n "$svc_home" ] || svc_home="/home/$svc_user"
        schreibe "$BACKEND_DROPIN" "# BSI M1 – geschrieben von deploy/security/haertung_installieren.sh
# (bei jedem Broker-Start). Nicht von Hand aendern; Begruendung der Auswahl
# und der ausgelassenen Optionen steht im Skript.
[Service]
ProtectSystem=strict
ReadWritePaths=$JARVIS_DIR -$svc_home /tmp /var/tmp -/dev/shm -/mnt -/media
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
LockPersonality=yes
RestrictRealtime=yes
SystemCallArchitectures=native
SystemCallFilter=~@clock @cpu-emulation @module @obsolete @raw-io @reboot @swap"
    else
        entferne "$BACKEND_DROPIN"
    fi

    schreibe "$BROKER_DROPIN" "# BSI M1 – geschrieben von deploy/security/haertung_installieren.sh
# (bei jedem Broker-Start). Nur, was keine Broker-Aufgabe einschraenkt.
[Service]
LockPersonality=yes
RestrictRealtime=yes
SystemCallArchitectures=native
SystemCallFilter=~@cpu-emulation @obsolete"
fi

# Rotation des Broker-Audits (BSI M2). NUR nach Alter: woechentlich drehen,
# nach 365 Tagen loeschen – "rotate" ist bewusst so hoch, dass die Stueckzahl
# nie vor dem Alter greift. delaycompress: die juengste Vorgaengerdatei bleibt
# lesbar (audit_tail liest sie mit, wenn die aktuelle Datei zu kurz ist).
schreibe "$LOGROTATE_DIR/jarvis-broker-audit" "# BSI M2 – geschrieben von deploy/security/haertung_installieren.sh
$AUDIT_DATEI {
    weekly
    maxage 365
    rotate 1000
    missingok
    notifempty
    compress
    delaycompress
    create 0600 root root
}"

# SSH nur per Schluessel (BSI M7). Die ERSTE Umstellung macht ein Mensch
# (ssh_haertung.sh --test / --anwenden, Aussperr-Gefahr); erst danach steht
# SSH_HAERTUNG=an in broker.conf, und jeder Broker-Start haelt den Drop-in auf
# dem Stand des Skripts. Ohne den Eintrag: nur ein Hinweis im Journal.
SSH_SKRIPT="$(dirname "${BASH_SOURCE[0]}")/ssh_haertung.sh"
if [ -f "$SSH_SKRIPT" ] && { [ -z "${JARVIS_HAERTUNG_TEST:-}" ] || [ -n "${JARVIS_SSH_TEST:-}" ]; }; then
    JARVIS_BROKER_CONF="$BROKER_CONF" bash "$SSH_SKRIPT" --erneuern || true
fi

# ── Dienstbenutzer ohne Systemprotokolle (BSI M8) ───────────────────────────
# jarvis stand in adm und systemd-journal (frueher von setup_broker.sh gesetzt)
# und las damit JEDES Systemprotokoll – fremde Dienste, Anmeldungen, sudo.
# Die Einsicht in die eigenen Dienste laeuft ueber die Broker-Op journal_lesen
# (backend/broker/journal.py). Eine Mitgliedschaft wirkt erst beim naechsten
# Prozessstart; laeuft das Backend noch MIT einer dieser Gruppen, wird es
# einmal nachgestartet (gleiches Muster wie beim Hauptschluessel unten).
# Notausgang wie die uebrige Haertung: HAERTUNG=aus laesst die Gruppen stehen.
M8_GRUPPEN="${JARVIS_M8_GRUPPEN:-adm systemd-journal}"
GPASSWD="${JARVIS_GPASSWD:-gpasswd}"
ID_BEFEHL="${JARVIS_ID:-id}"
m8_user="$(sed -n 's/^User=//p' "$UNIT_DIR/jarvis.service" 2>/dev/null | head -1)"
m8_nachstart=0
# Ein Testlauf fasst echte Gruppen NIE an – nur mit ausdruecklicher Attrappe.
m8_aktiv=1
if [ -n "${JARVIS_HAERTUNG_TEST:-}" ] && [ -z "${JARVIS_GPASSWD:-}" ]; then
    m8_aktiv=0
fi
if [ "$m8_aktiv" = "1" ] && [ "$modus" = "an" ] && [ -n "$m8_user" ] && [ "$m8_user" != "root" ]; then
    for grp in $M8_GRUPPEN; do
        if "$ID_BEFEHL" -nG "$m8_user" 2>/dev/null | tr ' ' '\n' | grep -qx "$grp"; then
            if "$GPASSWD" -d "$m8_user" "$grp" >/dev/null 2>&1; then
                echo "[Haertung] $m8_user aus Gruppe $grp entfernt (BSI M8)"
            else
                echo "[Haertung] $m8_user liess sich nicht aus $grp entfernen" >&2
            fi
        fi
        gid="$(${JARVIS_GETENT:-getent} group "$grp" 2>/dev/null | cut -d: -f3)"
        pid="$(${JARVIS_SYSTEMCTL:-systemctl} show -p MainPID --value jarvis.service 2>/dev/null)"
        if [ -n "$gid" ] && [ -n "$pid" ] && [ "$pid" != "0" ] \
                && grep -qE "^Groups:.*(^|[[:space:]])$gid([[:space:]]|$)" \
                   "${JARVIS_PROC_ROOT:-/proc}/$pid/status" 2>/dev/null; then
            m8_nachstart=1
        fi
    done
fi

if [ "$geaendert" = "1" ] && [ -z "${JARVIS_HAERTUNG_TEST:-}" ]; then
    systemctl daemon-reload
    echo "[Haertung] systemd neu geladen – wirksam ab dem naechsten Neustart von jarvis.service / jarvis-broker.service."
fi

# ── Backend ohne Hauptschluessel? Einmal nachstarten (BSI M5) ───────────────
# VORFALL ECHT 2026-10-05 22:53: beim Update starteten Broker und Backend
# GLEICHZEITIG. Der Broker schrieb 40-geheimnis.conf erst waehrend seines
# Starts – das Backend lief da schon, OHNE LoadCredential. Der Broker (root,
# liest die Datei direkt) hatte settings.json und .secret_key aber bereits
# verpackt: das Backend sah 12 Minuten lang nur verpackte LLM-Schluessel und
# Tokens, und jede Sitzung war ungueltig. Gegenmittel: laeuft jarvis.service,
# obwohl der Drop-in da ist, ohne Credential, wird er EINMAL neu gestartet –
# --no-block, weil er per After= auf diesen Broker wartet.
SYSTEMCTL="${JARVIS_SYSTEMCTL:-systemctl}"
CRED_DATEI="${JARVIS_CRED_ROOT:-/run/credentials}/jarvis.service/geheimnis"
if [ -f "$GEHEIMNIS_DROPIN" ] && { [ -z "${JARVIS_HAERTUNG_TEST:-}" ] || [ -n "${JARVIS_SYSTEMCTL:-}" ]; }; then
    if "$SYSTEMCTL" is-active --quiet jarvis.service && [ ! -e "$CRED_DATEI" ]; then
        echo "[Geheimnis] jarvis.service laeuft OHNE Hauptschluessel (gestartet vor dem Drop-in) – wird neu gestartet." >&2
        "$SYSTEMCTL" try-restart --no-block jarvis.service || true
        m8_nachstart=0
    fi
fi
# BSI M8: Backend laeuft noch mit adm/systemd-journal -> einmal nachstarten.
if [ "$m8_nachstart" = "1" ] && { [ -z "${JARVIS_HAERTUNG_TEST:-}" ] || [ -n "${JARVIS_SYSTEMCTL:-}" ]; }; then
    echo "[Haertung] jarvis.service laeuft noch mit Gruppe adm/systemd-journal – wird neu gestartet (BSI M8)." >&2
    "$SYSTEMCTL" try-restart --no-block jarvis.service || true
fi
exit 0
