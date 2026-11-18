#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Systemhaertung B1-B8 der Checkliste "hardening" (Confluence, Seite 342048622)
# – als root.
#
#   bash system_haertung.sh --pruefen     nur melden, nichts aendern
#                                         Exit 0 = alles umgesetzt, 1 = Abweichung
#   bash system_haertung.sh --anwenden    Pakete + Konfiguration, idempotent
#   bash system_haertung.sh --aide-init   AIDE-Vergleichsstand als eigene Unit
#                                         starten (dauert 15-20 Minuten)
#
# WAS ES TUT (je Massnahme der Liste):
#   B1  sudo protokolliert nach /var/log/sudo.log
#   B2  needrestart – nur AUFLISTEN, nie selbst neu starten
#   B3  nicht benoetigte Kernel-Module gesperrt
#   B4  Kernel-Werte (/etc/sysctl.d/90-haertung.conf)
#   B5  keine Speicherabbilder (Limits, coredump.conf, LimitCORE fuer jarvis)
#   B6  auditd mit Regeln auf Anmeldung, Rechte, Units und den Hauptschluessel
#   B7  AIDE mit Ausnahmen fuer Netzfreigaben, Pseudo-Dateisysteme und Caches
#   B8  lynis installiert (der Lauf und seine Bewertung sind Handarbeit)
#
# WAS ES BEWUSST NICHT TUT – jeweils gemessen am 18.11.2026:
#   * Kein Eingriff in apt: Remove-Unused-Dependencies verwaltet Jarvis selbst
#     (/etc/apt/apt.conf.d/52jarvis-unattended, backend/apt_upgrades.py). Ein
#     Aufraeumen wuerde Abhaengigkeiten des Agenten entfernen (cmake/boost,
#     ffmpeg, X/VNC, LibreOffice-Teile). Eine eigene Datei, die das ueberstimmt,
#     waere zudem wirkungslos – die Jarvis-Datei wird spaeter gelesen.
#   * Kein kernel.modules_disabled (Checkliste 66): Netzfreigaben laden das
#     cifs-Modul erst beim Einhaengen.
#   * Keine IPv6-Abschaltung: eigene Massnahme (D8), erst klaeren, ob
#     Verzeichnis, DNS oder Exchange IPv6 brauchen.
#   * Kein Neustart von jarvis.service: LimitCORE=0 wirkt erst mit dem
#     naechsten Neustart, und den bestimmt der Betreiber.
#   * Kein aideinit im --anwenden: der Lauf dauert 15-20 Minuten und gehoert
#     in eine eigene, gedrosselte Unit (--aide-init).
#
# SUDOERS: die Datei wird VOR dem Einspielen mit visudo -cf geprueft. Faellt
# die Pruefung durch, wird nichts eingespielt (Exit 3) – eine kaputte Datei in
# /etc/sudoers.d sperrt sudo fuer alle.
#
# TESTMODUS (tests/test_system_haertung.py): JARVIS_HAERTUNG_TEST=1 und
# JARVIS_SYS_WURZEL=<sandkasten>. Alle Zielpfade liegen dann unter der Wurzel;
# Pakete, sysctl --system, augenrules, daemon-reload und Dienste bleiben
# unberuehrt.
set -u

MODUS="${1:-}"
TEST="${JARVIS_HAERTUNG_TEST:-}"
W="${JARVIS_SYS_WURZEL:-}"

if [ -n "$TEST" ] && [ -z "$W" ]; then
    echo "system_haertung.sh: Testmodus ohne JARVIS_SYS_WURZEL – Abbruch" >&2
    exit 2
fi
if [ -z "$TEST" ]; then
    W=""
    if [ "$(id -u)" != "0" ]; then
        echo "system_haertung.sh: muss als root laufen" >&2
        exit 2
    fi
fi

PAKETE="needrestart auditd audispd-plugins aide aide-common lynis"

# ── Inhalte ──────────────────────────────────────────────────────────────────
SUDOERS='# Haertung B1 (Checkliste 37, 75) - deploy/security/system_haertung.sh
Defaults use_pty
Defaults logfile="/var/log/sudo.log"
Defaults timestamp_timeout=5
Defaults passwd_tries=3'

NEEDRESTART='# Haertung B2 (Checkliste 69) - deploy/security/system_haertung.sh
# Nur AUFLISTEN, was neu gestartet werden muss - nie selbst neu starten.
# Ein automatischer Neustart von jarvis.service nach einem unbeaufsichtigten
# Update waere eine Betriebsunterbrechung, die niemand ausgeloest hat.
$nrconf{restart} = '"'"'l'"'"';'

MODULE="cramfs freevxfs hfs hfsplus jffs2 udf usb-storage firewire-core bluetooth dccp sctp rds tipc"
MODPROBE="# Haertung B3 (Checkliste 63) - deploy/security/system_haertung.sh"
for m in $MODULE; do
    MODPROBE="$MODPROBE
install $m /bin/false
blacklist $m"
done

SYSCTL='# Haertung B4 (Checkliste 62) - deploy/security/system_haertung.sh
# OHNE IPv6-Abschaltung (eigene Massnahme D8) und OHNE kernel.modules_disabled
# (Checkliste 66: Netzfreigaben laden das cifs-Modul nach).

# Kernel
kernel.kptr_restrict = 2
kernel.dmesg_restrict = 1
kernel.unprivileged_bpf_disabled = 1
kernel.yama.ptrace_scope = 2
kernel.kexec_load_disabled = 1
kernel.sysrq = 0
kernel.randomize_va_space = 2
kernel.perf_event_paranoid = 3
net.core.bpf_jit_harden = 2
dev.tty.ldisc_autoload = 0

# Dateisystem
fs.suid_dumpable = 0
fs.protected_hardlinks = 1
fs.protected_symlinks = 1
fs.protected_fifos = 2
fs.protected_regular = 2

# Netz
net.ipv4.ip_forward = 0
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv4.conf.all.secure_redirects = 0
net.ipv4.conf.default.secure_redirects = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.default.send_redirects = 0
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.default.accept_source_route = 0
net.ipv4.conf.all.log_martians = 1
net.ipv4.conf.default.log_martians = 1
net.ipv4.icmp_echo_ignore_broadcasts = 1
net.ipv4.tcp_syncookies = 1
net.ipv6.conf.all.accept_redirects = 0
net.ipv6.conf.default.accept_redirects = 0'

LIMITS='# Haertung B5 (Checkliste 64) - deploy/security/system_haertung.sh
# "*" gilt bei pam_limits NICHT fuer root - deshalb root eigens.
# Spaeter gelesen als 10-coredump-debian.conf und damit massgeblich.
*       soft    core    0
*       hard    core    0
root    soft    core    0
root    hard    core    0'

COREDUMP='# Haertung B5 (Checkliste 64) - deploy/security/system_haertung.sh
# Wirkt erst, wenn systemd-coredump installiert ist (gemessen: nicht der Fall,
# core_pattern "core") - tragend sind die Limits und LimitCORE=0.
[Coredump]
Storage=none
ProcessSizeMax=0'

DROPIN='# Haertung B5 (Checkliste 64, 103) - deploy/security/system_haertung.sh
# Eigener Drop-in: haertung_installieren.sh raeumt nur seine eigenen ab.
# Wirksam erst mit dem naechsten Neustart von jarvis.service.
[Service]
LimitCORE=0'

AUDIT='## Haertung B6 (Checkliste 72, 73, 74) - deploy/security/system_haertung.sh
## Pruefbefehl ausserhalb eines Terminals: ausearch --input-logs -k <schluessel>
## (ohne --input-logs liest ausearch von stdin und meldet still "keine Treffer").

## Aenderungen an Anmeldung und Rechten
-w /etc/ssh/sshd_config -p wa -k sshd
-w /etc/ssh/sshd_config.d/ -p wa -k sshd
-w /etc/sudoers -p wa -k sudoers
-w /etc/sudoers.d/ -p wa -k sudoers

## Firewall, Units, Konfiguration des Dienstes
-w /etc/nftables.conf -p wa -k firewall
-w /etc/systemd/system/ -p wa -k systemd-units
-w /etc/jarvis/ -p wa -k jarvis-konfig

## Zugriffe auf den Hauptschluessel der Geheimnisse (auch LESEN)
-w /etc/jarvis/geheimnis.key -p rwa -k geheimnis

## Jeder Befehl, den eine angemeldete PERSON als root ausfuehrt.
## Dienste haben auid=unset und fallen heraus - sonst laeuft das Log voll.
-a always,exit -F arch=b64 -S execve -F euid=0 -F auid>=1000 -F auid!=unset -k root-cmd
-a always,exit -F arch=b32 -S execve -F euid=0 -F auid>=1000 -F auid!=unset -k root-cmd'

AIDE='# Haertung B7 (Checkliste 76) - deploy/security/system_haertung.sh
# Ohne diese Zeilen prueft die Debian-Vorgabe ("/ ... Full") ALLES unterhalb
# von / - auch die eingehaengten Netzfreigaben unter /mnt (CIFS) mit
# sha256+sha512, und das taeglich. Ausgenommen wird, was sich im Betrieb
# laufend aendert oder nicht auf diesem Rechner liegt. Der CODE unter
# /opt/jarvis bleibt erfasst: nach jedem Deploy "aideinit -y -f".
!/mnt
!/media
!/opt/jarvis/data
!/opt/jarvis/\.git
!/opt/jarvis/.*/__pycache__
!/home/jarvis

# Pseudo- und FUSE-Dateisysteme: ein Lesezugriff kann BLOCKIEREN (gemessen:
# aide --init hing 30 Minuten an /run/vmblock-fuse/dev). /run/user traegt gvfs
# und das Dokumentenportal der Desktop-Sitzung. SentinelOne haengt tracefs und
# bpf unter /opt/sentinelone ein - die Programmdateien des Agenten bleiben
# erfasst, nur die Einhaengepunkte nicht.
!/run/vmblock-fuse
!/run/user
!/opt/sentinelone/mount
!/opt/sentinelone/ebpfs

# Caches (Pip, Modelle) - aendern sich laufend
!/root/\.cache

# Desktop-Rauschen: der AppStream-Katalog wird laufend neu geschrieben
# (gemessen: 3.699 von 3.729 Aenderungen eines Pruefstands, nur ctime).
!/var/lib/swcatalog
!/var/cache/swcatalog
!/var/lib/PackageKit
!/var/lib/tailscale

# Das Broker-Audit waechst im Betrieb. "Log" erlaubt Wachsen und meldet ein
# Kuerzen oder Ersetzen - genau das, was bei einem Pruefprotokoll auffallen muss.
/var/log/jarvis-broker-audit\.jsonl$ f Log

# Nutzungszaehler des Root-Brokers (seit Commit 4b4796ab getrennt von der
# Freigabeliste): aendern sich im Betrieb laufend und werden deshalb als
# wechselnde Datei gefuehrt - Rechte und Eigentuemer bleiben geprueft, der
# Inhalt nicht. Die Freigabeliste /etc/jarvis/broker-policy.json bleibt VOLL
# geprueft; genau dafuer wurden die Zaehler herausgeloest.
/var/lib/jarvis-broker$ d VarDir
/var/lib/jarvis-broker/zaehler\.json$ f VarFile
!/var/lib/jarvis-broker/zaehler\.tmp$'

# ── Ziele: Pfad | Modus | Inhalt-Variable ────────────────────────────────────
ZIELE="
etc/sudoers.d/10-haertung|0440|SUDOERS
etc/needrestart/conf.d/50-haertung.conf|0644|NEEDRESTART
etc/modprobe.d/haertung.conf|0644|MODPROBE
etc/sysctl.d/90-haertung.conf|0644|SYSCTL
etc/security/limits.d/90-nocore.conf|0644|LIMITS
etc/systemd/coredump.conf.d/90-haertung.conf|0644|COREDUMP
etc/systemd/system/jarvis.service.d/70-coredump.conf|0644|DROPIN
etc/audit/rules.d/50-haertung.rules|0640|AUDIT
etc/aide/aide.conf.d/95_jarvis_ausnahmen|0644|AIDE
"

abweichungen=0
geaendert=""

# pruefe_datei <ziel> <modus> <inhalt>: meldet ok/fehlt/weicht ab
pruefe_datei() {
    local ziel="$1" modus="$2" inhalt="$3"
    if [ ! -f "$ziel" ]; then
        echo "  FEHLT       $ziel"
        abweichungen=$((abweichungen + 1))
    elif [ "$(cat "$ziel")" != "$inhalt" ]; then
        echo "  WEICHT AB   $ziel"
        abweichungen=$((abweichungen + 1))
    elif [ "$(stat -c %a "$ziel")" != "${modus#0}" ]; then
        echo "  MODUS       $ziel ($(stat -c %a "$ziel") statt ${modus#0})"
        abweichungen=$((abweichungen + 1))
    else
        echo "  ok          $ziel"
    fi
}

# schreibe <ziel> <modus> <inhalt> <name>: nur bei Abweichung, atomar
schreibe() {
    local ziel="$1" modus="$2" inhalt="$3" name="$4"
    if [ -f "$ziel" ] && [ "$(cat "$ziel")" = "$inhalt" ] \
       && [ "$(stat -c %a "$ziel")" = "${modus#0}" ]; then
        echo "  unveraendert $ziel"
        return 0
    fi
    mkdir -p "$(dirname "$ziel")"
    local tmp
    tmp="$(mktemp "$(dirname "$ziel")/.haertung.XXXXXX")" || return 1
    printf '%s\n' "$inhalt" > "$tmp"
    chmod "$modus" "$tmp"
    if [ "$name" = "SUDOERS" ] && command -v visudo >/dev/null 2>&1; then
        if ! visudo -cf "$tmp" >/dev/null 2>&1; then
            rm -f "$tmp"
            echo "FEHLER: sudoers-Pruefung (visudo -cf) fehlgeschlagen - nichts eingespielt" >&2
            exit 3
        fi
    fi
    [ -z "$TEST" ] && chown root:root "$tmp"
    mv -f "$tmp" "$ziel"
    echo "  geschrieben  $ziel"
    geaendert="$geaendert $name"
}

dateien() {
    local aktion="$1"
    local zeile pfad modus var
    while IFS= read -r zeile; do
        [ -z "$zeile" ] && continue
        pfad="${zeile%%|*}"; zeile="${zeile#*|}"
        modus="${zeile%%|*}"; var="${zeile#*|}"
        if [ "$aktion" = "pruefen" ]; then
            pruefe_datei "$W/$pfad" "$modus" "${!var}"
        else
            schreibe "$W/$pfad" "$modus" "${!var}" "$var"
        fi
    done <<< "$ZIELE"
}

system_pruefen() {
    [ -n "$TEST" ] && return 0
    local p
    for p in $PAKETE; do
        if ! dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q "ok installed"; then
            echo "  FEHLT       Paket $p"; abweichungen=$((abweichungen + 1))
        fi
    done
    systemctl is-active --quiet auditd || { echo "  AUS         auditd"; abweichungen=$((abweichungen + 1)); }
    systemctl is-enabled --quiet dailyaidecheck.timer 2>/dev/null \
        || { echo "  AUS         dailyaidecheck.timer"; abweichungen=$((abweichungen + 1)); }
    [ -s /var/lib/aide/aide.db ] \
        || { echo "  FEHLT       AIDE-Vergleichsstand (--aide-init)"; abweichungen=$((abweichungen + 1)); }
    # Laufende Kernel-Werte gegen die Datei
    local k v ist
    while IFS='=' read -r k v; do
        k="$(echo "$k" | tr -d ' ')"; v="$(echo "$v" | tr -d ' ')"
        case "$k" in ''|\#*) continue ;; esac
        ist="$(sysctl -n "$k" 2>/dev/null | tr -d ' ')"
        if [ "$ist" != "$v" ]; then
            echo "  SYSCTL      $k = $ist (soll $v)"; abweichungen=$((abweichungen + 1))
        fi
    done <<< "$SYSCTL"
}

anwenden_system() {
    [ -n "$TEST" ] && return 0
    case " $geaendert " in *" SYSCTL "*)
        if sysctl --system 2>&1 | grep -iE "error|invalid|unknown"; then
            echo "WARNUNG: sysctl --system meldet Fehler (siehe oben)" >&2
        fi ;;
    esac
    case " $geaendert " in *" AUDIT "*) augenrules --load >/dev/null 2>&1 || echo "WARNUNG: augenrules --load fehlgeschlagen" >&2 ;; esac
    case " $geaendert " in *" DROPIN "*)
        systemctl daemon-reload
        echo "  HINWEIS: LimitCORE=0 wirkt mit dem naechsten Neustart von jarvis.service" ;;
    esac
    systemctl enable --now auditd >/dev/null 2>&1 || echo "WARNUNG: auditd liess sich nicht starten" >&2
    systemctl enable --now dailyaidecheck.timer >/dev/null 2>&1 || true
    [ -s /var/lib/aide/aide.db ] || echo "  HINWEIS: noch kein AIDE-Vergleichsstand - bash $0 --aide-init"
}

case "$MODUS" in
    --pruefen)
        echo "== Dateien"
        dateien pruefen
        echo "== System"
        system_pruefen
        if [ "$abweichungen" -eq 0 ]; then
            echo "ERGEBNIS: alles umgesetzt"; exit 0
        fi
        echo "ERGEBNIS: $abweichungen Abweichung(en)"; exit 1
        ;;
    --anwenden)
        if [ -z "$TEST" ]; then
            echo "== Pakete"
            DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends $PAKETE >/dev/null \
                || { echo "FEHLER: Paketinstallation fehlgeschlagen" >&2; exit 1; }
        fi
        echo "== Dateien"
        dateien anwenden
        echo "== System"
        anwenden_system
        echo "ERGEBNIS: angewandt (geaendert:${geaendert:- nichts})"
        exit 0
        ;;
    --aide-init)
        [ -n "$TEST" ] && { echo "Testmodus: --aide-init uebersprungen"; exit 0; }
        if systemctl is-active --quiet aideinit-haertung 2>/dev/null; then
            echo "Ein AIDE-Lauf ist bereits aktiv (aideinit-haertung)."; exit 0
        fi
        systemd-run --unit=aideinit-haertung --collect -p Nice=19 -p IOSchedulingClass=idle \
            /usr/sbin/aideinit -y -f
        echo "Gestartet. Fortschritt: systemctl status aideinit-haertung"
        exit 0
        ;;
    *)
        echo "Aufruf: $0 --pruefen | --anwenden | --aide-init" >&2
        exit 2
        ;;
esac
