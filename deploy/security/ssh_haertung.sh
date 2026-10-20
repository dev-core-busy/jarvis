#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# SSH nur noch per Schluessel, root nicht (BSI M7) – als root.
#
# DER BEFUND (BSI-Abgleich ECHT, 2026-09-29): sshd bot publickey UND password an,
# Port 22 aus allen Netzen. Das Web-Kennwort eines lokalen Kontos ist zugleich
# sein Linux-Kennwort – ueber SSH liess es sich ohne Drossel und ohne 2FA raten.
# install.sh stellte bisher nur das Konto `jarvis` auf Schluessel um
# (50-jarvis-nur-schluessel.conf); alle anderen Konten blieben offen.
#
# WAS GESCHRIEBEN WIRD: ein Drop-in /etc/ssh/sshd_config.d/05-jarvis-haertung.conf
# mit PasswordAuthentication/KbdInteractiveAuthentication/PermitEmptyPasswords no
# und PermitRootLogin no (oder prohibit-password, siehe SSH_ROOT). Die "05" ist
# Absicht: sshd nimmt bei globalen Schluesselwoertern den ERSTEN Wert, und die
# Dateien werden in Namensreihenfolge eingelesen – ein spaeteres
# 50-cloud-init.conf mit "PasswordAuthentication yes" kaeme sonst zuerst.
#
# WARUM NICHT AUTOMATISCH BEIM BROKER-START (anders als M1): eine falsch
# gesetzte SSH-Sperre sperrt den Betreiber aus dem Server aus, und das merkt
# erst, wer sich das naechste Mal anmelden will. Die ERSTE Umstellung macht
# deshalb ein Mensch mit `--test` (Rueckfall-Timer) und danach `--anwenden`.
# Erst `--anwenden` setzt SSH_HAERTUNG=an in /etc/jarvis/broker.conf; ab dann
# haelt der Broker-Start (haertung_installieren.sh -> --erneuern) den Drop-in
# auf dem Stand dieses Skripts.
#
# AUSSPERR-SCHUTZ (vor jedem Schreiben): es muss ein Konto geben, das sich nach
# der Umstellung per Schluessel anmelden UND root werden kann (root selbst, falls
# SSH_ROOT=schluessel, oder ein Mitglied von sudo/wheel). Wer per sudo aufruft,
# braucht selbst einen Schluessel. Sonst Abbruch mit Exit 3 – `--erzwingen`
# uebergeht das, bewusst laut.
#
# Einstellungen in /etc/jarvis/broker.conf:
#   SSH_HAERTUNG=an|aus      gesetzt von --anwenden / --aus
#   SSH_ROOT=nein|schluessel nein (Vorgabe, BSI) = PermitRootLogin no;
#                            schluessel = prohibit-password (DEV: Deploy als root)
# Port 22 auf Admin-Netze begrenzen: SSH_NETZE in derselben Datei, umgesetzt von
# deploy/security/firewall.sh (Paketfilter, nicht sshd).
#
#   bash deploy/security/ssh_haertung.sh --status
#   bash deploy/security/ssh_haertung.sh --test [sekunden]   # mit Rueckfall-Timer
#   bash deploy/security/ssh_haertung.sh --anwenden [--erzwingen]
#   bash deploy/security/ssh_haertung.sh --aus
#   bash deploy/security/ssh_haertung.sh --erneuern           # Broker-Start
# ─────────────────────────────────────────────────────────────────────────────
set -u

# Pfade umlenkbar nur fuer den Waechter (tests/test_bsi_m6_m7.py)
SSHD_CONFIG="${JARVIS_SSHD_CONFIG:-/etc/ssh/sshd_config}"
DROPIN_DIR="${JARVIS_SSHD_DROPIN_DIR:-/etc/ssh/sshd_config.d}"
DROPIN="$DROPIN_DIR/05-jarvis-haertung.conf"
BROKER_CONF="${JARVIS_BROKER_CONF:-/etc/jarvis/broker.conf}"
PASSWD_DATEI="${JARVIS_PASSWD:-/etc/passwd}"
GROUP_DATEI="${JARVIS_GROUP:-/etc/group}"
TEST="${JARVIS_SSH_TEST:-}"
SSHD_BIN="$(command -v sshd 2>/dev/null || echo /usr/sbin/sshd)"

_ist_root() {
    [ -n "$TEST" ] && return 0
    [ "$(id -u)" = "0" ] || { echo "Bitte als root ausfuehren." >&2; exit 1; }
}

# _konf <schluessel> – Wert aus broker.conf (letzte Zeile gewinnt, ohne Anfuehrungszeichen)
_konf() {
    [ -f "$BROKER_CONF" ] || return 0
    sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$BROKER_CONF" | tail -1 | tr -d '"'"'" | tr -d '[:space:]'
}

# _konf_setzen <schluessel> <wert> – ersetzt die Zeile oder haengt sie an
_konf_setzen() {
    mkdir -p "$(dirname "$BROKER_CONF")"
    touch "$BROKER_CONF"
    if grep -qE "^[[:space:]]*$1[[:space:]]*=" "$BROKER_CONF"; then
        sed -i -E "s|^[[:space:]]*$1[[:space:]]*=.*|$1=$2|" "$BROKER_CONF"
    else
        printf '%s=%s\n' "$1" "$2" >> "$BROKER_CONF"
    fi
}

_root_modus() {
    case "$(_konf SSH_ROOT)" in
        schluessel) echo "prohibit-password" ;;
        *)          echo "no" ;;
    esac
}

_inhalt() {
    printf '%s\n' \
        "# BSI M7 – geschrieben von deploy/security/ssh_haertung.sh. Nicht von Hand" \
        "# aendern: der Broker-Start schreibt die Datei bei SSH_HAERTUNG=an neu." \
        "# Rueckweg: bash deploy/security/ssh_haertung.sh --aus" \
        "PasswordAuthentication no" \
        "KbdInteractiveAuthentication no" \
        "PermitEmptyPasswords no" \
        "PermitRootLogin $(_root_modus)"
}

# _schluessel_anzahl <home> – Zeilen mit Schluessel in den ueblichen Dateien
_schluessel_anzahl() {
    local home="$1" n=0 f
    for f in "$home/.ssh/authorized_keys" "$home/.ssh/authorized_keys2"; do
        [ -f "$f" ] || continue
        n=$(( n + $(grep -cvE '^[[:space:]]*(#|$)' "$f" 2>/dev/null || true) ))
    done
    echo "$n"
}

_home_von() { awk -F: -v u="$1" '$1==u {print $6}' "$PASSWD_DATEI"; }
_shell_von() { awk -F: -v u="$1" '$1==u {print $7}' "$PASSWD_DATEI"; }

# Mitglieder von sudo/wheel (Zusatzgruppen + primaere Gruppe)
_admins() {
    local gid
    awk -F: '$1=="sudo" || $1=="wheel" {print $4}' "$GROUP_DATEI" | tr ',' '\n'
    for gid in $(awk -F: '$1=="sudo" || $1=="wheel" {print $3}' "$GROUP_DATEI"); do
        awk -F: -v g="$gid" '$4==g {print $1}' "$PASSWD_DATEI"
    done
}

# Wer kommt nach der Umstellung noch herein und kann root werden? Gibt die Konten
# aus; Rueckgabe 0 = mindestens eines, sonst 1.
_zugang_nach_umstellung() {
    local u home shell gefunden=1
    if [ "$(_root_modus)" != "no" ]; then
        home="$(_home_von root)"
        if [ -n "$home" ] && [ "$(_schluessel_anzahl "$home")" -gt 0 ]; then
            echo "root"; gefunden=0
        fi
    fi
    for u in $(_admins | sort -u); do
        [ -n "$u" ] || continue
        home="$(_home_von "$u")"; shell="$(_shell_von "$u")"
        case "$shell" in */nologin|*/false|"") continue ;; esac
        [ -n "$home" ] || continue
        if [ "$(_schluessel_anzahl "$home")" -gt 0 ]; then
            echo "$u"; gefunden=0
        fi
    done
    return $gefunden
}

# Aussperr-Schutz. $1 = 1 -> trotzdem weiter (--erzwingen)
_aussperr_schutz() {
    local erzwingen="${1:-0}" konten fehler=""
    konten="$(_zugang_nach_umstellung)" || fehler="kein Konto mit Schluessel, das root werden kann (root bei SSH_ROOT=schluessel, sonst sudo/wheel)"
    if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
        local h; h="$(_home_von "$SUDO_USER")"
        if [ -z "$h" ] || [ "$(_schluessel_anzahl "$h")" -eq 0 ]; then
            fehler="${fehler:+$fehler; }aufrufendes Konto '$SUDO_USER' hat keinen Schluessel"
        fi
    fi
    if [ -z "$fehler" ]; then
        echo "[SSH] Zugang nach der Umstellung: $(echo "$konten" | tr '\n' ' ')"
        return 0
    fi
    if [ "$erzwingen" = "1" ]; then
        echo "[SSH] WARNUNG (--erzwingen): $fehler" >&2
        return 0
    fi
    echo "[SSH] ABBRUCH: $fehler – erst einen Schluessel hinterlegen (~/.ssh/authorized_keys)." >&2
    return 3
}

_include_vorhanden() {
    grep -qE "^[[:space:]]*Include[[:space:]]+${DROPIN_DIR//./\\.}/" "$SSHD_CONFIG" 2>/dev/null
}

_neu_laden() {
    [ -n "$TEST" ] && return 0
    systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true
}

# Schreibt den Drop-in (nur bei Abweichung), prueft ihn mit sshd -t und laedt
# sshd neu. Lehnt sshd ab, wird der vorige Stand wiederhergestellt.
_schreiben() {
    local neu alt=""
    if ! _include_vorhanden; then
        echo "[SSH] ABBRUCH: $SSHD_CONFIG bindet $DROPIN_DIR nicht ein – bitte von Hand umstellen." >&2
        return 4
    fi
    neu="$(_inhalt)"
    if [ -f "$DROPIN" ]; then
        alt="$(cat "$DROPIN")"
        [ "$alt" = "$neu" ] && { echo "[SSH] Drop-in unveraendert: $DROPIN"; return 0; }
    fi
    mkdir -p "$DROPIN_DIR"
    printf '%s\n' "$neu" > "$DROPIN.tmp" && chmod 0644 "$DROPIN.tmp" && mv "$DROPIN.tmp" "$DROPIN"
    if [ -z "$TEST" ] && ! "$SSHD_BIN" -t -f "$SSHD_CONFIG" 2>/dev/null; then
        if [ -n "$alt" ]; then printf '%s\n' "$alt" > "$DROPIN"; else rm -f "$DROPIN"; fi
        echo "[SSH] ABBRUCH: sshd -t lehnt die Einstellung ab – zurueckgenommen." >&2
        return 5
    fi
    _neu_laden
    echo "[SSH] geschrieben: $DROPIN (PermitRootLogin $(_root_modus))"
}

_entfernen() {
    if [ -f "$DROPIN" ]; then
        rm -f "$DROPIN"
        _neu_laden
        echo "[SSH] entfernt: $DROPIN"
    fi
}

# Maschinenlesbar fuer die Oberflaeche (backend/broker/fernzugang.py):
#   KONTO <name> <kann-root:root|sudo> <anzahl-schluessel>
#   FP <name> <ssh-keygen -l Zeile>
# Dieselben Konten wie der Aussperr-Schutz (root + sudo/wheel mit Login-Shell);
# ob root ZAEHLT, haengt an SSH_ROOT und entscheidet der Aufrufer.
konten() {
    local u home shell f
    for u in root $(_admins | sort -u); do
        [ -n "$u" ] || continue
        home="$(_home_von "$u")"; shell="$(_shell_von "$u")"
        [ -n "$home" ] || continue
        case "$shell" in */nologin|*/false|"") continue ;; esac
        echo "KONTO $u $([ "$u" = root ] && echo root || echo sudo) $(_schluessel_anzahl "$home")"
        for f in "$home/.ssh/authorized_keys" "$home/.ssh/authorized_keys2"; do
            [ -f "$f" ] || continue
            ssh-keygen -lf "$f" 2>/dev/null | sed "s/^/FP $u /"
        done
    done
}

status() {
    echo "── sshd (wirksam) ───────────────────────────────────────"
    if [ -x "$SSHD_BIN" ] && [ -z "$TEST" ]; then
        "$SSHD_BIN" -T 2>/dev/null \
            | grep -iE '^(passwordauthentication|kbdinteractiveauthentication|permitrootlogin|permitemptypasswords|pubkeyauthentication) ' \
            | sed 's/^/  /'
    fi
    echo "── Drop-in ──────────────────────────────────────────────"
    if [ -f "$DROPIN" ]; then echo "  $DROPIN vorhanden"; else echo "  $DROPIN fehlt"; fi
    echo "  SSH_HAERTUNG=$(_konf SSH_HAERTUNG)  SSH_ROOT=$(_konf SSH_ROOT)  SSH_NETZE=$(_konf SSH_NETZE)"
    echo "── Konten mit Schluessel, die root werden koennen ───────"
    _zugang_nach_umstellung | sed 's/^/  /' || echo "  (keines – Umstellung wuerde aussperren)"
}

ERZWINGEN=0
for a in "$@"; do [ "$a" = "--erzwingen" ] && ERZWINGEN=1; done

case "${1:---status}" in
    --status)
        status
        ;;
    --konten)
        konten
        ;;
    --test)
        _ist_root
        SEK="${2:-300}"
        case "$SEK" in ''|*[!0-9]*) SEK=300 ;; esac
        _aussperr_schutz "$ERZWINGEN" || exit $?
        # Der Rueckfall ENTFERNT den Drop-in. Steht die Haertung schon, waere ein
        # Test also ein Weg, sie nach Ablauf der Frist still abzuschalten.
        if [ "$(_konf SSH_HAERTUNG)" = "an" ]; then
            echo "[SSH] ABBRUCH: Haertung ist bereits aktiv – zum Aendern erst --aus." >&2
            exit 6
        fi
        if [ -z "$TEST" ]; then
            # Rueckfall-Timer VOR der Aenderung – wie in firewall.sh. Ein noch
            # laufender Test wird ersetzt (gleicher Unit-Name, sonst scheitert
            # systemd-run). OHNE Timer KEIN Test: das waere eine Umstellung ohne Netz.
            systemctl stop ssh-rollback.timer >/dev/null 2>&1
            systemctl reset-failed ssh-rollback.service ssh-rollback.timer >/dev/null 2>&1
            if ! systemd-run --on-active="$SEK" --unit=ssh-rollback --description="SSH-Haertung Rueckfall" \
                /bin/sh -c "rm -f '$DROPIN'; systemctl reload ssh || systemctl reload sshd" >/dev/null 2>&1; then
                echo "[SSH] ABBRUCH: Rueckfall-Timer konnte nicht gesetzt werden – nichts geaendert." >&2
                exit 6
            fi
            echo "[SSH] Rueckfall-Timer aktiv: in ${SEK}s zurueck (Abbruch: systemctl stop ssh-rollback.timer)"
        fi
        _schreiben || exit $?
        echo
        echo "Jetzt in einer NEUEN Sitzung pruefen (die laufende bleibt bestehen):"
        echo "  ssh -o PreferredAuthentications=password <konto>@<host>   -> muss scheitern"
        echo "  ssh <konto>@<host>                                        -> per Schluessel herein"
        echo "Wenn alles laeuft:  bash $0 --anwenden"
        ;;
    --anwenden)
        _ist_root
        _aussperr_schutz "$ERZWINGEN" || exit $?
        [ -z "$TEST" ] && systemctl stop ssh-rollback.timer 2>/dev/null
        _schreiben || exit $?
        _konf_setzen SSH_HAERTUNG an
        echo "[SSH] SSH_HAERTUNG=an in $BROKER_CONF – der Broker-Start haelt den Drop-in aktuell."
        ;;
    --aus)
        _ist_root
        [ -z "$TEST" ] && systemctl stop ssh-rollback.timer >/dev/null 2>&1
        _entfernen
        _konf_setzen SSH_HAERTUNG aus
        ;;
    --erneuern)
        _ist_root
        case "$(_konf SSH_HAERTUNG)" in
            an)
                # Ein spaeter entfernter Schluessel darf beim Neustart nicht zum
                # Aussperren fuehren: dann bleibt der vorhandene Stand stehen.
                if _aussperr_schutz 0 >/dev/null; then
                    _schreiben
                else
                    echo "[SSH] WARNUNG: Aussperr-Schutz greift – Drop-in nicht erneuert." >&2
                fi
                ;;
            aus)
                _entfernen
                ;;
            *)
                if [ -z "$TEST" ] && "$SSHD_BIN" -T 2>/dev/null | grep -qi '^passwordauthentication yes'; then
                    echo "[SSH] HINWEIS: SSH erlaubt Kennwort-Anmeldung (BSI M7) – deploy/security/ssh_haertung.sh --test" >&2
                fi
                ;;
        esac
        ;;
    *)
        echo "Aufruf: $0 [--status|--konten|--test [sekunden]|--anwenden [--erzwingen]|--aus|--erneuern]"
        exit 1
        ;;
esac
