#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Systemhaertung B1-B8, B13, B14, D5, D8 und E2 (Teil) der Checkliste "hardening" (Confluence, Seite 342048622)
# – als root.
#
#   bash system_haertung.sh --pruefen     nur melden, nichts aendern
#                                         Exit 0 = alles umgesetzt, 1 = Abweichung
#   bash system_haertung.sh --anwenden    Pakete + Konfiguration, idempotent
#   bash system_haertung.sh --aide-init   AIDE-Vergleichsstand als eigene Unit
#                                         starten (dauert 15-20 Minuten)
#
# WAS ES TUT (je Massnahme der Liste):
#   B1  sudo protokolliert nach /var/log/sudo.log (woechentlich rotiert)
#   B2  needrestart – nur AUFLISTEN, nie selbst neu starten
#   B3  nicht benoetigte Kernel-Module gesperrt
#   B4  Kernel-Werte (/etc/sysctl.d/90-haertung.conf)
#   B5  keine Speicherabbilder (Limits, coredump.conf, LimitCORE fuer jarvis)
#   B6  auditd mit Regeln auf Anmeldung, Rechte, Units und den Hauptschluessel;
#       Speicher 20 x 50 MB statt der Vorgabe 5 x 8 MB (siehe AUDITD_WERTE)
#   B7  AIDE mit Ausnahmen fuer Netzfreigaben, Pseudo-Dateisysteme und Caches
#   B8  lynis installiert (der Lauf und seine Bewertung sind Handarbeit)
#   B13 Ueberwachung: jarvis-ueberwachung.timer ruft alle 5 Minuten
#       backend/ueberwachung.py aus der ROOT-EIGENEN Broker-Kopie auf (nicht
#       aus /opt/jarvis - Befund K1). Die Datei kommt mit dem Broker-Neustart
#       dorthin; fehlt sie, meldet --anwenden das und richtet nichts ein.
#   B14 Kennwortregeln lokaler Konten: pwquality (mindestens 14 Zeichen) und
#       pam_faillock (5 Fehlversuche in 15 Minuten sperren 15 Minuten) ueber
#       zwei eigene pam-auth-update-Profile - keine Datei eines Pakets wird
#       geaendert. root bleibt ausgenommen (Notzugang ueber die Konsole).
#       Die Web-Anmeldung lokaler Konten bekommt einen eigenen PAM-Dienst
#       jarvis-web OHNE faillock (Begruendung bei PAM_WEB).
#   D5  Kein Swap: jarvis.service und jarvis-broker.service bekommen
#       MemorySwapMax=0 (eigener Drop-in 75-swap.conf - im Speicher beider
#       liegen die entpackten Geheimnisse). Dazu wird der Swap abgeschaltet:
#       die swap-Zeilen in /etc/fstab werden mit "#haertung-D5# " auskommentiert
#       und swapoff laeuft - aber NUR, wenn danach genug Speicher frei bleibt
#       (MemAvailable minus belegter Swap >= SWAP_RESERVE_KB) und nicht
#       SWAP_ERLAUBT=ja in /etc/jarvis/broker.conf steht. Mit SWAP_ERLAUBT=ja
#       werden nur die eigenen Kommentare zurueckgenommen (swapon -a holt ihn
#       sofort zurueck). Gemessen auf ECHT 23.11.2026: 16 GB RAM, der Dienst lag
#       seit August hoechstens bei 7,6 GB (systemd "memory peak" je Lauf); die
#       Spitze im Juli (14,6 GB + 4,3 GB Swap) war der behobene OOM-Fehler beim
#       Neuaufbau des FAISS-Index.
#   D8 IPv6 aus auf allen Schnittstellen ausser Loopback (eigene Datei
#       /etc/sysctl.d/90-haertung-ipv6.conf) - aber NUR, wenn das Netz kein
#       IPv6 nutzt: keine globale IPv6-Adresse, keine IPv6-Standardroute und
#       nicht IPV6_ERLAUBT=ja in /etc/jarvis/broker.conf. ::1 bleibt (lokale
#       Dienste lauschen dort). Eine Schnittstelle unter NetworkManager bekommt
#       ipv6.method disabled - sonst setzt NM disable_ipv6 bei jeder Verbindung
#       wieder auf 0 (DEV 22.11.2026: Datei mit all=1 seit Juni, ens192 trotzdem 0).
#   E2  (Teil) /dev/shm ohne Ausfuehrung: eigene fstab-Zeile mit
#       nosuid,nodev,noexec (systemd-remount-fs uebernimmt sie beim Start),
#       im laufenden System per remount. Eine schon vorhandene, FREMDE
#       /dev/shm-Zeile ohne noexec wird gemeldet, nicht geaendert.
#
# WAS ES BEWUSST NICHT TUT – jeweils gemessen am 18.11.2026:
#   * Kein Eingriff in apt: Remove-Unused-Dependencies verwaltet Jarvis selbst
#     (/etc/apt/apt.conf.d/52jarvis-unattended, backend/apt_upgrades.py). Ein
#     Aufraeumen wuerde Abhaengigkeiten des Agenten entfernen (cmake/boost,
#     ffmpeg, X/VNC, LibreOffice-Teile). Eine eigene Datei, die das ueberstimmt,
#     waere zudem wirkungslos – die Jarvis-Datei wird spaeter gelesen.
#   * Kein kernel.modules_disabled (Checkliste 66): Netzfreigaben laden das
#     cifs-Modul erst beim Einhaengen.
#   * Kein IPv6 aus auf Loopback (lo): x11vnc, chrony und cups lauschen auf
#     ::1, und "localhost" loest zuerst nach ::1 auf. Gemessen 22.11.2026: auf
#     ECHT hat ens192 nur eine Link-local-Adresse, keine Route ausser fe80::/64,
#     DNS nur ueber IPv4 - an entfernten Zielen aendert die Abschaltung nichts.
#   * Kein noexec auf /tmp (E2): gemessen auf DEV 23.11.2026 brechen damit
#     direkt aufgerufene Skripte der Sandbox (./skript), Bibliotheken aus /tmp
#     (ctypes) und cmake-Laufproben beim Bauen von Paketen (dlib ueber pip) -
#     und /var/tmp und das Home des Dienstes bleiben ohnehin ausfuehrbar.
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

PAKETE="needrestart auditd audispd-plugins aide aide-common lynis libpam-pwquality"

# Werkzeug fuer die sudoers-Pruefung. Im Produktivlauf IMMER das visudo des
# Systems - die Variable wird dort nicht gelesen, sonst waehlte die Umgebung das
# Pruefwerkzeug fuer eine Datei, die sudo fuer alle sperren kann.
# Im Testmodus darf der Waechter eines vorgeben: auf einem CI-Laeufer ist das
# vorhandene visudo nicht dasselbe wie auf dem Zielsystem. Am 2026-11-19 lehnte
# das visudo von Ubuntu 26.04 "Defaults logfile=" ab ("unknown setting:
# 'logfile'"), waehrend dieselbe Datei auf Debian 13 mit visudo 1.9.16p2
# "Analyse OK" ist (auf DEV gemessen) - die Sonde war falsch, nicht die Datei.
VISUDO="visudo"
if [ -n "$TEST" ] && [ -n "${JARVIS_VISUDO:-}" ]; then
    VISUDO="$JARVIS_VISUDO"
fi
# Dasselbe fuer pam-auth-update (B14): im Produktivlauf immer das des Systems,
# im Testmodus eine Attrappe des Waechters, die nur die Sandkasten-Wurzel kennt.
PAM_AUTH_UPDATE="pam-auth-update"
if [ -n "$TEST" ] && [ -n "${JARVIS_PAM_AUTH_UPDATE:-}" ]; then
    PAM_AUTH_UPDATE="$JARVIS_PAM_AUTH_UPDATE"
fi
# Dasselbe fuer ip (D8): die Schranke "nutzt das Netz IPv6?" misst die echten
# Adressen und Routen; im Testmodus liefert eine Attrappe den Zustand.
IP_BEFEHL="ip"
if [ -n "$TEST" ] && [ -n "${JARVIS_IP:-}" ]; then
    IP_BEFEHL="$JARVIS_IP"
fi
# Fuer den Laufzeitteil von D8 (ipv6_system) gibt der Waechter im Testmodus
# ein Ersatzverzeichnis fuer /proc/sys/net/ipv6/conf und eine nmcli-Attrappe
# vor. Ohne beide laeuft der Teil im Testmodus gar nicht - nie gegen das echte
# /proc oder das echte NetworkManager des Pruefrechners.
IPV6_CONF="/proc/sys/net/ipv6/conf"
NMCLI="nmcli"
if [ -n "$TEST" ]; then
    IPV6_CONF="${JARVIS_IPV6_CONF:-}"
    NMCLI="${JARVIS_NMCLI:-}"
fi
# Fuer den Laufzeitteil von D5 (swap_system) dasselbe: /proc/swaps,
# /proc/meminfo und swapoff im Testmodus NUR als Ersatz des Waechters, ohne
# Vorgabe leer - dann laeuft der Teil im Testmodus gar nicht.
PROC_SWAPS="/proc/swaps"
MEMINFO="/proc/meminfo"
SWAPOFF="swapoff"
if [ -n "$TEST" ]; then
    PROC_SWAPS="${JARVIS_PROC_SWAPS:-}"
    MEMINFO="${JARVIS_MEMINFO:-}"
    SWAPOFF="${JARVIS_SWAPOFF:-}"
fi
# Was nach dem Abschalten mindestens frei bleiben muss (2 GB). swapoff holt
# jede ausgelagerte Seite zurueck; reicht der Speicher nicht, greift waehrend
# swapoff der OOM-Killer - deshalb wird VORHER gerechnet.
SWAP_RESERVE_KB=2097152
FSTAB="$W/etc/fstab"
SWAP_MARKE="#haertung-D5# "
# E2: Optionen von /dev/shm lesen und neu einhaengen. Im Testmodus NUR ueber
# die Ersatzdatei und die mount-Attrappe des Waechters, ohne Vorgabe leer -
# nie das /dev/shm des Pruefrechners.
MOUNT="mount"
SHM_OPTIONEN=""
if [ -n "$TEST" ]; then
    MOUNT="${JARVIS_MOUNT:-}"
    SHM_OPTIONEN="${JARVIS_SHM_OPTIONEN:-}"
fi
SHM_KOMMENTAR="# Haertung E2 (Checkliste 27) - deploy/security/system_haertung.sh: /dev/shm ohne Ausfuehrung"
SHM_ZEILE="tmpfs /dev/shm tmpfs defaults,nosuid,nodev,noexec 0 0"
BROKER_CONF="$W/etc/jarvis/broker.conf"

# ── Inhalte ──────────────────────────────────────────────────────────────────
SUDOERS='# Haertung B1 (Checkliste 37, 75) - deploy/security/system_haertung.sh
Defaults use_pty
Defaults logfile="/var/log/sudo.log"
Defaults timestamp_timeout=5
Defaults passwd_tries=3'

LOGROTATE='# Haertung B1 (Checkliste 75) - deploy/security/system_haertung.sh
# sudo schreibt mit logfile= in eine eigene Datei, die kein Paket rotiert -
# ohne diese Regel waechst sie unbegrenzt.
/var/log/sudo.log {
    weekly
    rotate 12
    compress
    delaycompress
    missingok
    notifempty
    create 0600 root root
}'

# auditd: Vorgabe sind 5 Dateien zu 8 MB. Gemessen am 18.11.2026: ein einziger
# lynis-Lauf ueber sudo erzeugte in einer Minute 28.545 root-cmd-Eintraege
# (jeder Hilfsprozess des Shellskripts zaehlt als Befehl einer Person) - danach
# reichte das Protokoll nur noch sechs Minuten zurueck, fruehere Ereignisse auf
# sudoers und den Hauptschluessel waren herausrotiert. 20 x 50 MB = 1 GB.
AUDITD_WERTE="max_log_file=50 num_logs=20"

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
# OHNE IPv6-Abschaltung (D8, eigene Datei mit Schranke: SYSCTL_IPV6) und OHNE kernel.modules_disabled
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

SWAP_DROPIN='# Haertung D5 (Checkliste 28, 103) - deploy/security/system_haertung.sh
# Nichts aus dem Speicher dieses Dienstes geht in den Swap: dort liegen die
# entpackten Geheimnisse (Hauptschluessel, LLM-Schluessel, Sitzungen).
# Eigener Drop-in: haertung_installieren.sh raeumt nur seine eigenen ab.
[Service]
MemorySwapMax=0'

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

# Wachsende Protokolle (gemessen: im ersten Pruefstand taeglich gemeldet).
# "Log" erlaubt Wachsen und meldet Schrumpfen oder Ersetzen der AKTUELLEN Datei;
# rotierte Fassungen werden nur noch auf Eigentuemer und Rechte geprueft
# ("LowLog"), neue und entfernte sind erlaubt - jede Rotation waere sonst ein Fund.
/var/log/audit/audit\.log$ f Log
/var/log/audit/audit\.log\.[0-9]+$ f LowLog+ANF+ARF
/var/log/sudo\.log$ f Log
/var/log/sudo\.log\.[0-9]+(\.gz)?$ f LowLog+ANF+ARF
/var/log/aide/aideinit\.(log|errors)$ f Log
# SentinelOne rotiert seine Logs selbst nach Groesse (name.N.log,
# old_logs.tar.gz) - auch die aktuelle Datei schrumpft dabei. Der Agent liefert
# an seine eigene Konsole; hier zaehlen nur Eigentuemer und Rechte.
/opt/sentinelone/log/[^/]+$ f LowLog+ANF+ARF

# Laufzeit: Arbeitsverzeichnisse und Anhaenge der Sandbox-Laeufe (je Benutzer,
# fluechtig), Credential-Kopien und Mount-Propagation von systemd (bei jedem
# Dienststart neu). Die Quelle des Hauptschluessels unter /etc/jarvis bleibt
# voll geprueft.
!/tmp/jarvis-arbeit
!/tmp/jarvis-anhaenge
!/run/credentials
!/run/systemd/propagate

# Nutzungszaehler des Root-Brokers (seit Commit 4b4796ab getrennt von der
# Freigabeliste): aendern sich im Betrieb laufend und werden deshalb als
# wechselnde Datei gefuehrt - Rechte und Eigentuemer bleiben geprueft, der
# Inhalt nicht. Die Freigabeliste /etc/jarvis/broker-policy.json bleibt VOLL
# geprueft; genau dafuer wurden die Zaehler herausgeloest.
/var/lib/jarvis-broker$ d VarDir
/var/lib/jarvis-broker/zaehler\.json$ f VarFile
!/var/lib/jarvis-broker/zaehler\.tmp$

# Zustand der Ueberwachung (B13): wird alle 5 Minuten neu geschrieben.
/var/lib/jarvis-ueberwachung$ d VarDir
/var/lib/jarvis-ueberwachung/zustand\.json$ f VarFile
!/var/lib/jarvis-ueberwachung/zustand\.json\.tmp$'

# B13 (Checkliste 136). Laeuft als root, weil es das Kernel-Journal, den
# Zustand aller Units und das Zertifikat lesen muss - aber ohne Netz und ohne
# Schreibrecht ausser auf das eigene Zustandsverzeichnis.
UEBERW_PROG="/usr/local/lib/jarvis-broker/backend/ueberwachung.py"
UEBERW_SERVICE="# Haertung B13 (Checkliste 136) - deploy/security/system_haertung.sh
[Unit]
Description=Jarvis Serverueberwachung (Haertung B13)

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 -I $UEBERW_PROG --lauf
Nice=10
IOSchedulingClass=idle
TimeoutStartSec=120
StateDirectory=jarvis-ueberwachung
StateDirectoryMode=0755
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateNetwork=yes
NoNewPrivileges=yes"

UEBERW_TIMER='# Haertung B13 (Checkliste 136) - deploy/security/system_haertung.sh
[Unit]
Description=Jarvis Serverueberwachung alle 5 Minuten (Haertung B13)

[Timer]
OnBootSec=3min
OnUnitActiveSec=5min
AccuracySec=30s

[Install]
WantedBy=timers.target'

# B14 (Checkliste 44). Gemessen auf DEV am 21.11.2026 mit einem Wegwerfkonto:
#  * pwquality.conf.d wird gelesen: passwd lehnt 9 Zeichen ab ("shorter than
#    14 characters"), 20 Zeichen gehen durch. root (chpasswd) wird nur gewarnt,
#    nicht gebremst - deshalb prueft Jarvis die Laenge beim Kennwortwechsel
#    selbst (main.KENNWORT_MIN_LAENGE).
#  * faillock zaehlt auch, wenn ein Konto sein EIGENES Kennwort prueft (die
#    Zaehldatei gehoert dem Konto) - also auch die Web-Anmeldung von jarvis.
#  * Im Dienstkontext (ProtectSystem=strict wie jarvis.service) meldet
#    pam_faillock "System error" - AUCH beim richtigen Kennwort. Mit faillock im
#    Dienst "login" haette sich niemand mehr lokal im Web anmelden koennen.
PWQUALITY='# Haertung B14 (Checkliste 44) - deploy/security/system_haertung.sh
# Gilt fuer passwd. root (chpasswd ueber den Broker) wird nur gewarnt - dort
# prueft Jarvis die Laenge selbst (backend/main.py, KENNWORT_MIN_LAENGE).
minlen = 14'

# Gleiche Werte in beiden Profilen: faillock liest sie je Aufruf aus den
# Argumenten, die Datei /etc/security/faillock.conf (gehoert libpam-modules)
# bleibt unberuehrt - eine geaenderte Paketdatei hielte jedes Update an.
FAILLOCK_ARGS="deny=5 unlock_time=900 fail_interval=900"
FAILLOCK="Name: Sperre nach Fehlversuchen - Zaehlen (Haertung B14)
Default: yes
Priority: 0
Auth-Type: Primary
Auth:
	[default=die]	pam_faillock.so authfail $FAILLOCK_ARGS"
FAILLOCK_VORAB="Name: Sperre nach Fehlversuchen - Pruefen und Zuruecksetzen (Haertung B14)
Default: yes
Priority: 1024
Auth-Type: Primary
Auth:
	requisite	pam_faillock.so preauth $FAILLOCK_ARGS
Account-Type: Primary
Account:
	required	pam_faillock.so"

PAM_WEB='# Haertung B14 (Checkliste 44) - deploy/security/system_haertung.sh
# Web-Anmeldung lokaler Konten (backend/main.py, _pam_dienst). NUR pam_unix,
# bewusst OHNE pam_faillock: im Dienstkontext meldet faillock "System error",
# auch beim richtigen Kennwort (DEV 21.11.2026). Gegen Durchprobieren sperrt
# Jarvis selbst, je IP und je Konto (BSI M3, backend/anmelde_schutz.py) - und
# diese Sperre kann ein Administrator in der Oberflaeche aufheben.
auth     required   pam_unix.so
account  required   pam_unix.so'

SYSCTL_IPV6='# Haertung D8 (Checkliste 54) - deploy/security/system_haertung.sh
# IPv6 aus, ausser auf Loopback. Die Reihenfolge traegt: "all" setzt den Wert
# auch auf lo, die letzte Zeile nimmt lo wieder aus (::1 bleibt erreichbar).
# Zurueck: IPV6_ERLAUBT=ja in /etc/jarvis/broker.conf, dann --anwenden.
net.ipv6.conf.all.disable_ipv6 = 1
net.ipv6.conf.default.disable_ipv6 = 1
net.ipv6.conf.lo.disable_ipv6 = 0'

# ipv6_grund: warum IPv6 an bleiben muss (leer = darf abgeschaltet werden).
# Gemessen wird die Nutzung, nicht vermutet: eine globale Adresse oder eine
# Standardroute heisst, das Netz spricht IPv6 - dann waere das Abschalten
# ein Ausfall. Nach dem Abschalten sind beide weg; der Wert bleibt dann aus,
# bis jemand IPV6_ERLAUBT=ja setzt.
ipv6_grund() {
    local wert
    wert="$(sed -n 's/^[[:space:]]*IPV6_ERLAUBT[[:space:]]*=[[:space:]]*//p' "$BROKER_CONF" 2>/dev/null \
            | tail -1 | tr -d '"'"'" | tr -d '[:space:]')"
    if [ "$wert" = "ja" ]; then
        echo "IPV6_ERLAUBT=ja in /etc/jarvis/broker.conf"; return
    fi
    if [ -n "$("$IP_BEFEHL" -6 -o addr show scope global 2>/dev/null)" ]; then
        echo "globale IPv6-Adresse vorhanden ($("$IP_BEFEHL" -6 -o addr show scope global 2>/dev/null | awk '{print $2}' | sort -u | tr '\n' ' ')- das Netz nutzt IPv6)"; return
    fi
    if [ -n "$("$IP_BEFEHL" -6 route show default 2>/dev/null)" ]; then
        echo "IPv6-Standardroute vorhanden - das Netz nutzt IPv6"; return
    fi
}
IPV6_GRUND="$(ipv6_grund)"

# swap_grund: warum der Swap bleiben soll (leer = darf weg). Nur die
# ausdrueckliche Entscheidung in broker.conf - ob der Speicher reicht, wird
# erst beim Abschalten gemessen (swap_system), weil es sich laufend aendert.
swap_grund() {
    local wert
    wert="$(sed -n 's/^[[:space:]]*SWAP_ERLAUBT[[:space:]]*=[[:space:]]*//p' "$BROKER_CONF" 2>/dev/null \
            | tail -1 | tr -d '"'"'" | tr -d '[:space:]')"
    [ "$wert" = "ja" ] && echo "SWAP_ERLAUBT=ja in /etc/jarvis/broker.conf"
}
SWAP_GRUND="$(swap_grund)"

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
etc/logrotate.d/sudo-haertung|0644|LOGROTATE
etc/systemd/system/jarvis-ueberwachung.service|0644|UEBERW_SERVICE
etc/systemd/system/jarvis-ueberwachung.timer|0644|UEBERW_TIMER
etc/security/pwquality.conf.d/90-haertung.conf|0644|PWQUALITY
etc/pam.d/jarvis-web|0644|PAM_WEB
usr/share/pam-configs/jarvis-faillock|0644|FAILLOCK
usr/share/pam-configs/jarvis-faillock-vorab|0644|FAILLOCK_VORAB
etc/sysctl.d/90-haertung-ipv6.conf|0644|SYSCTL_IPV6
etc/systemd/system/jarvis.service.d/75-swap.conf|0644|SWAP_DROPIN
etc/systemd/system/jarvis-broker.service.d/75-swap.conf|0644|SWAP_DROPIN
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
    if [ "$name" = "SUDOERS" ] && command -v "$VISUDO" >/dev/null 2>&1; then
        local visudo_sagt
        if ! visudo_sagt="$(LC_ALL=C "$VISUDO" -cf "$tmp" 2>&1)"; then
            rm -f "$tmp"
            # Die Begruendung von visudo MITNEHMEN. Bis 2026-11-19 verschwand sie
            # in /dev/null, und uebrig blieb "fehlgeschlagen" ohne Zeile, ohne
            # Grund und ohne naechsten Schritt - auf einem Laeufer mit anderer
            # sudo-Fassung war damit nicht zu sagen, WAS sie beanstandet.
            echo "FEHLER: sudoers-Pruefung (visudo -cf) fehlgeschlagen - nichts eingespielt" >&2
            echo "FEHLER: $VISUDO ($("$VISUDO" -V 2>/dev/null | head -1)) sagt: ${visudo_sagt:-(keine Ausgabe)}" >&2
            exit 3
        fi
    fi
    [ -z "$TEST" ] && chown root:root "$tmp"
    mv -f "$tmp" "$ziel"
    echo "  geschrieben  $ziel"
    geaendert="$geaendert $name"
}

# ipv6_bleibt_an pruefen|anwenden <ziel>: IPv6 darf nicht aus (IPV6_GRUND).
# Eine schon geschriebene Datei waere dann ein Widerspruch - sie gehoert weg,
# aber nur, wenn es UNSERE ist (gleicher Inhalt); eine fremde bleibt liegen.
ipv6_bleibt_an() {
    local aktion="$1" ziel="$2"
    if [ ! -f "$ziel" ]; then
        echo "  bleibt an   IPv6 ($IPV6_GRUND)"
    elif [ "$aktion" = "pruefen" ]; then
        echo "  WEICHT AB   $ziel (IPv6 soll an bleiben: $IPV6_GRUND)"
        abweichungen=$((abweichungen + 1))
    elif [ "$(cat "$ziel")" = "$SYSCTL_IPV6" ]; then
        rm -f "$ziel"
        echo "  entfernt     $ziel ($IPV6_GRUND)"
        echo "  HINWEIS: IPv6 kommt mit dem naechsten Neustart zurueck (oder sofort:"
        echo "           sysctl -w net.ipv6.conf.all.disable_ipv6=0 net.ipv6.conf.default.disable_ipv6=0)"
        geaendert="$geaendert SYSCTL_IPV6"
    else
        echo "  WARNUNG: $ziel ist nicht von diesem Skript - nicht entfernt" >&2
    fi
}

dateien() {
    local aktion="$1"
    local zeile pfad modus var
    while IFS= read -r zeile; do
        [ -z "$zeile" ] && continue
        pfad="${zeile%%|*}"; zeile="${zeile#*|}"
        modus="${zeile%%|*}"; var="${zeile#*|}"
        if [ "$var" = "SYSCTL_IPV6" ] && [ -n "$IPV6_GRUND" ]; then
            ipv6_bleibt_an "$aktion" "$W/$pfad"
            continue
        fi
        if [ "$aktion" = "pruefen" ]; then
            pruefe_datei "$W/$pfad" "$modus" "${!var}"
        else
            schreibe "$W/$pfad" "$modus" "${!var}" "$var"
        fi
    done <<< "$ZIELE"
}

# auditd_konf pruefen|anwenden: einzelne Schluessel in auditd.conf (die Datei
# gehoert dem Paket - sie wird nicht ersetzt, nur diese Werte werden gesetzt)
auditd_konf() {
    local datei="$W/etc/audit/auditd.conf" paar k v ist
    for paar in $AUDITD_WERTE; do
        k="${paar%%=*}"; v="${paar#*=}"
        ist="$(sed -nE "s/^[[:space:]]*$k[[:space:]]*=[[:space:]]*([^[:space:]]+).*/\1/p" "$datei" 2>/dev/null | tail -1)"
        if [ "$ist" = "$v" ]; then
            if [ "$1" = "pruefen" ]; then echo "  ok          $datei: $k = $v"
            else echo "  unveraendert $datei: $k = $v"; fi
            continue
        fi
        if [ "$1" = "pruefen" ]; then
            echo "  WEICHT AB   $datei: $k = ${ist:-fehlt} (soll $v)"
            abweichungen=$((abweichungen + 1))
        else
            mkdir -p "$(dirname "$datei")"
            if grep -qE "^[[:space:]]*$k[[:space:]]*=" "$datei" 2>/dev/null; then
                sed -i -E "s/^[[:space:]]*$k[[:space:]]*=.*/$k = $v/" "$datei"
            else
                echo "$k = $v" >> "$datei"
            fi
            echo "  geschrieben  $datei: $k = $v"
            case " $geaendert " in *" AUDITD "*) ;; *) geaendert="$geaendert AUDITD" ;; esac
        fi
    done
}

# pam_pruefen: ist der B14-Stapel wirklich aktiv? Die Profile liegen zu lassen
# genuegt nicht - wirksam ist erst, was pam-auth-update in common-* schreibt.
pam_pruefen() {
    local d="$W/etc/pam.d"
    grep -qE '^auth[[:space:]]+requisite[[:space:]]+pam_faillock\.so[[:space:]]+preauth' "$d/common-auth" 2>/dev/null \
        || { echo "  AUS         faillock preauth in common-auth"; abweichungen=$((abweichungen + 1)); }
    grep -qE '^auth[[:space:]]+\[default=die\][[:space:]]+pam_faillock\.so[[:space:]]+authfail' "$d/common-auth" 2>/dev/null \
        || { echo "  AUS         faillock authfail in common-auth"; abweichungen=$((abweichungen + 1)); }
    grep -qE '^account[[:space:]]+required[[:space:]]+pam_faillock\.so' "$d/common-account" 2>/dev/null \
        || { echo "  AUS         faillock in common-account"; abweichungen=$((abweichungen + 1)); }
    grep -qE '^password[[:space:]]+requisite[[:space:]]+pam_pwquality\.so' "$d/common-password" 2>/dev/null \
        || { echo "  AUS         pwquality in common-password"; abweichungen=$((abweichungen + 1)); }
}

# pam_aktivieren: die Profile einschalten - aber NUR, wenn der Jarvis-Code die
# Web-Anmeldung schon ueber jarvis-web fuehrt. Aelterer Code prueft ueber den
# Dienst "login"; dort braeche faillock JEDE lokale Web-Anmeldung (siehe PAM_WEB).
pam_aktivieren() {
    local code="$W/opt/jarvis/backend/main.py"
    if [ -f "$code" ] && ! grep -q 'PAM_DIENST_WEB = "jarvis-web"' "$code"; then
        echo "WARNUNG: $code prueft die Web-Anmeldung noch ueber den Dienst 'login' -" >&2
        echo "         faillock NICHT eingeschaltet. Erst Jarvis aktualisieren und" >&2
        echo "         jarvis.service neu starten, dann erneut --anwenden." >&2
        return 0
    fi
    # Schon aktiv und Profile unveraendert: nicht neu schreiben lassen (jeder
    # Lauf von pam-auth-update erneuerte sonst common-* - Rauschen fuer AIDE).
    local vorher=$abweichungen
    pam_pruefen >/dev/null
    local fehlt=$((abweichungen - vorher)); abweichungen=$vorher
    case " $geaendert " in *" FAILLOCK"*) fehlt=1 ;; esac
    if [ "$fehlt" -eq 0 ]; then
        echo "  unveraendert faillock/pwquality (pam-auth-update)"
        return 0
    fi
    if [ -n "$TEST" ] && [ -z "${JARVIS_PAM_AUTH_UPDATE:-}" ]; then
        echo "  HINWEIS Testmodus ohne JARVIS_PAM_AUTH_UPDATE - pam-auth-update uebersprungen"
        return 0
    fi
    if ! DEBIAN_FRONTEND=noninteractive "$PAM_AUTH_UPDATE" --enable jarvis-faillock jarvis-faillock-vorab; then
        echo "WARNUNG: pam-auth-update fehlgeschlagen - faillock nicht eingeschaltet" >&2
        return 0
    fi
    echo "  aktiviert    faillock (pam-auth-update)"
}

# ipv6_system pruefen|anwenden: der WIRKSAME Wert je Schnittstelle (D8).
# Die Datei allein beweist nichts: auf DEV stand all=1 seit Juni 2026, und
# NetworkManager hatte ens192 trotzdem auf 0 gesetzt (ipv6.method=auto).
ipv6_system() {
    local aktion="$1" d if wert con methode
    [ -n "$IPV6_GRUND" ] && return 0
    [ -n "$IPV6_CONF" ] && [ -d "$IPV6_CONF" ] || return 0
    for d in "$IPV6_CONF"/*/; do
        if="$(basename "$d")"
        case "$if" in all|default|lo) continue ;; esac
        wert="$(cat "$d/disable_ipv6" 2>/dev/null)"
        # NetworkManager: verwaltet er die Schnittstelle, gehoert die Einstellung
        # in sein Profil - ein sysctl -w allein hielte nur bis zur naechsten Verbindung.
        # Nur Schnittstellen, die NM SELBST verbindet ("100 (connected)") - eine
        # "externally" verbundene (tailscale0, Docker-Bruecken) gehoert einem
        # anderen Dienst, ihr In-Memory-Profil zu aendern hiesse, es festzuschreiben.
        con=""; methode=""
        if [ -n "$NMCLI" ] && command -v "$NMCLI" >/dev/null 2>&1 \
           && [ "$(LC_ALL=C "$NMCLI" -g GENERAL.STATE device show "$if" 2>/dev/null | head -1)" = "100 (connected)" ]; then
            con="$("$NMCLI" -g GENERAL.CONNECTION device show "$if" 2>/dev/null | head -1)"
            [ -n "$con" ] && methode="$("$NMCLI" -g ipv6.method connection show "$con" 2>/dev/null | head -1)"
        fi
        if [ "$aktion" = "pruefen" ]; then
            if [ "$wert" != "1" ]; then
                echo "  AN          IPv6 auf $if (disable_ipv6 = ${wert:-?})"
                abweichungen=$((abweichungen + 1))
            fi
            if [ -n "$con" ] && [ "$methode" != "disabled" ]; then
                echo "  NM          $if: Profil \"$con\" mit ipv6.method=$methode (setzt IPv6 bei jeder Verbindung wieder an)"
                abweichungen=$((abweichungen + 1))
            fi
            continue
        fi
        if [ -n "$con" ] && [ "$methode" != "disabled" ]; then
            # Nur das Profil aendern, die Verbindung NICHT neu aufbauen: das waere
            # eine Netzunterbrechung. Wirksam wird es mit der naechsten Verbindung,
            # bis dahin traegt das sysctl -w darunter.
            if "$NMCLI" connection modify "$con" ipv6.method disabled; then
                echo "  gesetzt      NetworkManager \"$con\": ipv6.method disabled (vorher $methode)"
            else
                echo "WARNUNG: NetworkManager-Profil \"$con\" nicht geaendert" >&2
            fi
        fi
        if [ "$wert" != "1" ]; then
            if ipv6_aus "$if"; then
                echo "  aus          IPv6 auf $if"
            else
                echo "WARNUNG: IPv6 auf $if liess sich nicht abschalten" >&2
            fi
        fi
    done
}

# ipv6_aus <schnittstelle>: im Produktivlauf sysctl -w, im Testmodus die
# Datei im Ersatzverzeichnis (dieselbe Form wie /proc).
ipv6_aus() {
    if [ -n "$TEST" ]; then
        echo 1 > "$IPV6_CONF/$1/disable_ipv6"
    else
        sysctl -q -w "net.ipv6.conf.$1.disable_ipv6=1" >/dev/null
    fi
}

# fstab_schreiben <inhalt>: /etc/fstab atomar ersetzen, Rechte und
# Eigentuemer wie vorher (die Datei gehoert dem System, nicht diesem Skript).
fstab_schreiben() {
    local tmp
    tmp="$(mktemp "$(dirname "$FSTAB")/.haertung.XXXXXX")" || return 1
    printf '%s\n' "$1" > "$tmp"
    chmod --reference="$FSTAB" "$tmp"
    [ -z "$TEST" ] && chown --reference="$FSTAB" "$tmp"
    mv -f "$tmp" "$FSTAB"
}

# swap_fstab pruefen|anwenden: Swap-Zeilen in /etc/fstab (D5). Auskommentiert
# wird mit einer eigenen Marke - nur DIESE Zeilen nimmt SWAP_ERLAUBT=ja wieder
# zurueck; eine von Hand auskommentierte Zeile bleibt, wie sie ist.
swap_fstab() {
    local aktion="$1" aktiv eigene spec
    [ -f "$FSTAB" ] || return 0
    aktiv="$(awk '!/^[[:space:]]*#/ && $3 == "swap" {print $1}' "$FSTAB")"
    eigene="$(grep -c "^$SWAP_MARKE" "$FSTAB")"
    if [ -n "$SWAP_GRUND" ]; then
        if [ "$eigene" -eq 0 ]; then
            echo "  bleibt an   Swap ($SWAP_GRUND)"
        elif [ "$aktion" = "pruefen" ]; then
            echo "  WEICHT AB   $FSTAB: $eigene Swap-Zeile(n) von D5 auskommentiert (Swap soll bleiben: $SWAP_GRUND)"
            abweichungen=$((abweichungen + 1))
        elif fstab_schreiben "$(sed "s/^$SWAP_MARKE//" "$FSTAB")"; then
            echo "  zurueck      $FSTAB: $eigene Swap-Zeile(n) wieder aktiv ($SWAP_GRUND)"
            echo "  HINWEIS: Swap kommt mit dem naechsten Start zurueck (oder sofort: swapon -a)"
            geaendert="$geaendert FSTAB"
        else
            echo "WARNUNG: $FSTAB nicht geschrieben" >&2
        fi
        return 0
    fi
    [ -z "$aktiv" ] && return 0
    if [ "$aktion" = "pruefen" ]; then
        for spec in $aktiv; do
            echo "  SWAP        $FSTAB: $spec (wird beim Start eingeschaltet)"
            abweichungen=$((abweichungen + 1))
        done
        return 0
    fi
    if fstab_schreiben "$(awk -v m="$SWAP_MARKE" '!/^[[:space:]]*#/ && $3 == "swap" {print m $0; next} {print}' "$FSTAB")"; then
        echo "  auskommentiert $FSTAB: $(echo $aktiv)"
        geaendert="$geaendert FSTAB"
    else
        echo "WARNUNG: $FSTAB nicht geschrieben" >&2
    fi
}

# swap_system pruefen|anwenden: der WIRKSAME Swap (D5). swapoff nur, wenn
# danach genug Speicher frei bleibt - gerechnet aus MemAvailable und dem
# belegten Swap, bevor irgendetwas abgeschaltet wird.
swap_system() {
    local aktion="$1" geraete belegt verfuegbar g
    [ -n "$SWAP_GRUND" ] && return 0
    [ -n "$PROC_SWAPS" ] && [ -f "$PROC_SWAPS" ] || return 0
    geraete="$(awk 'NR > 1 {print $1}' "$PROC_SWAPS")"
    [ -z "$geraete" ] && return 0
    belegt="$(awk 'NR > 1 {s += $4} END {print s + 0}' "$PROC_SWAPS")"
    if [ "$aktion" = "pruefen" ]; then
        for g in $geraete; do
            echo "  SWAP an     $g"
            abweichungen=$((abweichungen + 1))
        done
        return 0
    fi
    [ -n "$SWAPOFF" ] || return 0
    verfuegbar="$(awk '/^MemAvailable:/ {print $2}' "$MEMINFO" 2>/dev/null)"
    if [ -z "$verfuegbar" ] || [ $((verfuegbar - belegt)) -lt "$SWAP_RESERVE_KB" ]; then
        echo "WARNUNG: Swap bleibt an - zu wenig freier Speicher (verfuegbar $(( ${verfuegbar:-0} / 1024 )) MB," \
             "im Swap $((belegt / 1024)) MB, Reserve $((SWAP_RESERVE_KB / 1024)) MB)" >&2
        return 0
    fi
    for g in $geraete; do
        if "$SWAPOFF" "$g"; then
            echo "  aus          Swap $g ($((belegt / 1024)) MB zurueckgeholt)"
        else
            echo "WARNUNG: swapoff $g fehlgeschlagen" >&2
        fi
    done
}

# shm_fstab pruefen|anwenden: eigene fstab-Zeile fuer /dev/shm (E2). Eine
# vorhandene Zeile eines anderen bleibt unangetastet - fehlt ihr eine der drei
# Optionen, wird das gemeldet (sonst gewaenne beim Start die fremde Zeile).
shm_fstab() {
    local aktion="$1" opts o fehlt=""
    [ -f "$FSTAB" ] || return 0
    opts="$(awk '!/^[[:space:]]*#/ && $2 == "/dev/shm" {print $4}' "$FSTAB" | tail -1)"
    if [ -z "$opts" ]; then
        if [ "$aktion" = "pruefen" ]; then
            echo "  FEHLT       $FSTAB: /dev/shm mit noexec"
            abweichungen=$((abweichungen + 1))
        elif fstab_schreiben "$(cat "$FSTAB")
$SHM_KOMMENTAR
$SHM_ZEILE"; then
            echo "  ergaenzt     $FSTAB: /dev/shm mit nosuid,nodev,noexec"
            geaendert="$geaendert FSTAB"
        else
            echo "WARNUNG: $FSTAB nicht geschrieben" >&2
        fi
        return 0
    fi
    for o in nosuid nodev noexec; do
        case ",$opts," in *",$o,"*) ;; *) fehlt="$fehlt $o" ;; esac
    done
    if [ -n "$fehlt" ]; then
        echo "  WEICHT AB   $FSTAB: /dev/shm-Zeile ohne$fehlt (nicht von diesem Skript - nicht geaendert)"
        abweichungen=$((abweichungen + 1))
    fi
}

# shm_optionen: die WIRKSAMEN Optionen von /dev/shm (leer = unbekannt)
shm_optionen() {
    if [ -n "$TEST" ]; then
        [ -n "$SHM_OPTIONEN" ] && cat "$SHM_OPTIONEN" 2>/dev/null
    else
        findmnt -no OPTIONS /dev/shm 2>/dev/null
    fi
}

# shm_system pruefen|anwenden: /dev/shm im laufenden System (E2). Die
# fstab-Zeile wirkt erst beim naechsten Start; bis dahin traegt das remount.
shm_system() {
    local aktion="$1" opts
    opts="$(shm_optionen)"
    [ -n "$opts" ] || return 0
    case ",$opts," in *",noexec,"*) return 0 ;; esac
    if [ "$aktion" = "pruefen" ]; then
        echo "  AUSFUEHRBAR /dev/shm ($opts)"
        abweichungen=$((abweichungen + 1))
        return 0
    fi
    [ -n "$MOUNT" ] || return 0
    if "$MOUNT" -o remount,nosuid,nodev,noexec /dev/shm; then
        echo "  noexec       /dev/shm"
    else
        echo "WARNUNG: /dev/shm liess sich nicht mit noexec neu einhaengen" >&2
    fi
}

system_pruefen() {
    pam_pruefen
    ipv6_system pruefen
    swap_fstab pruefen
    swap_system pruefen
    shm_fstab pruefen
    shm_system pruefen
    [ -n "$TEST" ] && return 0
    # D5: wirkt MemorySwapMax=0 in der LAUFENDEN Unit? Der Drop-in allein
    # beweist es nicht (ohne daemon-reload steht memory.swap.max auf "max").
    local u m
    for u in jarvis jarvis-broker; do
        systemctl is-active --quiet "$u.service" || continue
        m="$(cat "/sys/fs/cgroup/system.slice/$u.service/memory.swap.max" 2>/dev/null)"
        if [ -n "$m" ] && [ "$m" != "0" ]; then
            echo "  SWAP        $u.service darf in den Swap (memory.swap.max = $m)"
            abweichungen=$((abweichungen + 1))
        fi
    done
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
    systemctl is-enabled --quiet jarvis-ueberwachung.timer 2>/dev/null \
        && systemctl is-active --quiet jarvis-ueberwachung.timer 2>/dev/null \
        || { echo "  AUS         jarvis-ueberwachung.timer"; abweichungen=$((abweichungen + 1)); }
    [ -f "$UEBERW_PROG" ] \
        || { echo "  FEHLT       $UEBERW_PROG (Broker-Kopie aelter als B13 - jarvis-broker neu starten)"; abweichungen=$((abweichungen + 1)); }
    # Ein Timer, der laeuft, aber nichts schreibt, ist kein Waechter: der
    # Zustand muss juenger sein als drei Takte (15 Minuten).
    if [ -f /var/lib/jarvis-ueberwachung/zustand.json ]; then
        local alter=$(( $(date +%s) - $(stat -c %Y /var/lib/jarvis-ueberwachung/zustand.json) ))
        [ "$alter" -le 900 ] \
            || { echo "  VERALTET    Ueberwachung: letzter Lauf vor $((alter / 60)) Minuten"; abweichungen=$((abweichungen + 1)); }
    else
        echo "  FEHLT       Zustand der Ueberwachung (/var/lib/jarvis-ueberwachung/zustand.json)"
        abweichungen=$((abweichungen + 1))
    fi
    # Laufende Kernel-Werte gegen die Datei
    local k v ist
    while IFS='=' read -r k v; do
        k="$(echo "$k" | tr -d ' ')"; v="$(echo "$v" | tr -d ' ')"
        case "$k" in ''|\#*) continue ;; esac
        ist="$(sysctl -n "$k" 2>/dev/null | tr -d ' ')"
        if [ "$ist" != "$v" ]; then
            echo "  SYSCTL      $k = $ist (soll $v)"; abweichungen=$((abweichungen + 1))
        fi
    done <<< "$SYSCTL$([ -z "$IPV6_GRUND" ] && printf '\n%s' "$SYSCTL_IPV6")"
}

anwenden_system() {
    pam_aktivieren
    swap_fstab anwenden
    shm_fstab anwenden
    if [ -n "$TEST" ]; then
        ipv6_system anwenden
        swap_system anwenden
        shm_system anwenden
        return 0
    fi
    # D5: erst MemorySwapMax=0 und die geaenderte fstab bei systemd bekannt
    # machen (daemon-reload setzt memory.swap.max der laufenden Units und
    # entfernt die erzeugte .swap-Unit), dann den Swap abschalten.
    case " $geaendert " in *" SWAP_DROPIN "*|*" FSTAB "*) systemctl daemon-reload ;; esac
    swap_system anwenden
    shm_system anwenden
    case " $geaendert " in *" SYSCTL "*|*" SYSCTL_IPV6 "*)
        if sysctl --system 2>&1 | grep -iE "error|invalid|unknown"; then
            echo "WARNUNG: sysctl --system meldet Fehler (siehe oben)" >&2
        fi ;;
    esac
    ipv6_system anwenden
    case " $geaendert " in *" AUDIT "*) augenrules --load >/dev/null 2>&1 || echo "WARNUNG: augenrules --load fehlgeschlagen" >&2 ;; esac
    case " $geaendert " in *" AUDITD "*)
        # SIGHUP: auditd liest die Konfiguration neu und uebernimmt die Werte
        systemctl reload auditd >/dev/null 2>&1 || auditctl --signal reload >/dev/null 2>&1 \
            || echo "WARNUNG: auditd hat die neue Konfiguration nicht uebernommen" >&2 ;;
    esac
    case " $geaendert " in *" DROPIN "*)
        systemctl daemon-reload
        echo "  HINWEIS: LimitCORE=0 wirkt mit dem naechsten Neustart von jarvis.service" ;;
    esac
    systemctl enable --now auditd >/dev/null 2>&1 || echo "WARNUNG: auditd liess sich nicht starten" >&2
    systemctl enable --now dailyaidecheck.timer >/dev/null 2>&1 || true
    case " $geaendert " in *" UEBERW_"*) systemctl daemon-reload ;; esac
    if [ -f "$UEBERW_PROG" ]; then
        systemctl enable --now jarvis-ueberwachung.timer >/dev/null 2>&1 \
            || echo "WARNUNG: jarvis-ueberwachung.timer liess sich nicht starten" >&2
    else
        # Ohne Programm liefe der Timer alle 5 Minuten in einen Fehler - dann
        # lieber gar nicht einschalten und laut sagen, warum.
        echo "WARNUNG: $UEBERW_PROG fehlt - Broker-Kopie aelter als B13. Erst" >&2
        echo "         'systemctl restart jarvis-broker.service', dann erneut --anwenden." >&2
    fi
    [ -s /var/lib/aide/aide.db ] || echo "  HINWEIS: noch kein AIDE-Vergleichsstand - bash $0 --aide-init"
}

case "$MODUS" in
    --pruefen)
        echo "== Dateien"
        dateien pruefen
        auditd_konf pruefen
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
        auditd_konf anwenden
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
