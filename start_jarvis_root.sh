#!/bin/bash
# Jarvis Root-Bootstrap + Root-Broker (jarvis-broker.service)
#
# Laeuft als root und uebernimmt ALLE root-pflichtigen Startaufgaben, die
# frueher in start_jarvis.sh (jarvis.service als root) lagen:
#   - Display-Erkennung + Xvfb-Fallback
#   - iptables-Freischaltung der Jarvis-Ports
#   - Screensaver-/dconf-Haertung
#   - x11vnc (+ Selbstheilungs-Watcher) und websockify
# Danach startet er den Root-Broker (backend/broker/daemon.py), ueber den das
# unprivilegierte Backend (jarvis.service, User=jarvis) Root-Operationen
# anfordert. Siehe deploy/security/README.md.

# ZWEI VERZEICHNISSE (Befund K1, BSI-Abgleich 2026-09-29):
#   CODE_DIR   – woher DIESES Skript und der Broker-Code kommen. Regulaer die
#                root-eigene Kopie /usr/local/lib/jarvis-broker.
#   JARVIS_DIR – der Projektbaum mit den Daten (/opt/jarvis). Er gehoert dem
#                Dienstbenutzer; als root wird daraus NICHTS ausgefuehrt, kein
#                Skript, kein venv, kein git. Frueher lief genau das – und wer
#                als jarvis eine Zeile darin aenderte, hatte beim naechsten
#                Broker-Start root.
CODE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BROKER_INSTALL_DIR="${JARVIS_BROKER_INSTALL_DIR:-/usr/local/lib/jarvis-broker}"
if [ -z "${JARVIS_DIR:-}" ]; then
    # Aus der Kopie heraus kennt das Skript den Projektbaum nicht aus seinem
    # eigenen Ort; die Unit setzt JARVIS_DIR, sonst die Vorgabe.
    if [ "$CODE_DIR" = "$BROKER_INSTALL_DIR" ]; then JARVIS_DIR="/opt/jarvis"; else JARVIS_DIR="$CODE_DIR"; fi
fi
export JARVIS_DIR
cd "$JARVIS_DIR"

if [ "$(id -u)" != "0" ]; then
    echo "FEHLER: start_jarvis_root.sh muss als root laufen (jarvis-broker.service)." >&2
    exit 1
fi

# 0. Broker-Code root-eigen halten
#
# a) Laeuft dieses Skript noch aus dem PROJEKTBAUM (alte Unit), wird die Kopie
#    angelegt, die Unit umgestellt und in die Kopie gewechselt – EINMAL, danach
#    startet systemd direkt von dort. Das macht jede Bestandsinstallation beim
#    naechsten Broker-Neustart selbst sicher, gleich wie der Code kam.
# b) Laeuft es aus der Kopie, wird sie aus der Quelle in /etc/jarvis/broker.conf
#    aufgefrischt (Vorgabe: das oeffentliche Repository, von root selbst
#    geholt). Scheitert das, laeuft der bisherige Stand weiter.
# JARVIS_BROKER_FRISCH=1 verhindert eine Schleife nach dem Wechsel.
INSTALLER_REL="deploy/security/broker_installieren.sh"
if [ "${JARVIS_BROKER_FRISCH:-0}" != "1" ] && [ -f "$CODE_DIR/$INSTALLER_REL" ]; then
    if [ "$CODE_DIR" != "$BROKER_INSTALL_DIR" ]; then
        echo "[Broker] laeuft aus dem Projektbaum $CODE_DIR – stelle auf root-eigene Kopie um."
        bash "$CODE_DIR/$INSTALLER_REL" --jarvis-dir "$JARVIS_DIR"; RC=$?
        if [ "$RC" != "0" ] && [ "$RC" != "3" ] && [ ! -f "$BROKER_INSTALL_DIR/STAND" ]; then
            # Erstinstallation ohne Netzweg: einmalig aus dem Baum, der ohnehin
            # gerade als root laeuft – schlechter wird es dadurch nicht, und beim
            # naechsten Start versucht es die Quelle erneut.
            echo "[Broker] WARNUNG: Quelle nicht erreichbar – Erstinstallation aus dem Projektbaum." >&2
            bash "$CODE_DIR/$INSTALLER_REL" --jarvis-dir "$JARVIS_DIR" --quelle lokal; RC=$?
        fi
        if [ -x "$BROKER_INSTALL_DIR/start_jarvis_root.sh" ]; then
            UNIT=/etc/systemd/system/jarvis-broker.service
            if [ -f "$BROKER_INSTALL_DIR/deploy/security/jarvis-broker.service" ]; then
                sed -e "s|^Environment=JARVIS_DIR=.*|Environment=JARVIS_DIR=$JARVIS_DIR|" \
                    "$BROKER_INSTALL_DIR/deploy/security/jarvis-broker.service" > "$UNIT.tmp" \
                    && mv "$UNIT.tmp" "$UNIT" && systemctl daemon-reload \
                    && echo "[Broker] Unit zeigt jetzt auf $BROKER_INSTALL_DIR."
            fi
            export JARVIS_BROKER_FRISCH=1
            exec "$BROKER_INSTALL_DIR/start_jarvis_root.sh"
        fi
        echo "[Broker] WARNUNG: root-eigene Kopie nicht verfuegbar – laeuft weiter aus dem Projektbaum (unsicher)." >&2
    else
        bash "$CODE_DIR/$INSTALLER_REL" --jarvis-dir "$JARVIS_DIR"; RC=$?
        if [ "$RC" = "0" ]; then
            export JARVIS_BROKER_FRISCH=1
            exec "$BROKER_INSTALL_DIR/start_jarvis_root.sh"
        fi
    fi
fi

# 0b. WhatsApp-Bridge nicht als root (K1-a, auf ECHT gemessen: User=root)
#
# Die Bridge startet `node index.js` aus dem Projektbaum. Als root waere jede
# Aenderung daran durch den Dienstbenutzer ein Weg zu root – und der Broker darf
# die Unit starten (systemctl-Whitelist). Idempotent, greift nur bei User=root
# bzw. fehlendem User und nur, wenn die Unit in den Projektbaum zeigt.
WA_UNIT=/etc/systemd/system/whatsapp-bridge.service
if [ -f "$WA_UNIT" ] && grep -q "$JARVIS_DIR" "$WA_UNIT" && id jarvis >/dev/null 2>&1; then
    WA_USER="$(grep -E '^User=' "$WA_UNIT" | head -1 | cut -d= -f2)"
    if [ -z "$WA_USER" ] || [ "$WA_USER" = "root" ]; then
        if [ -n "$WA_USER" ]; then
            sed -i 's|^User=.*|User=jarvis|' "$WA_UNIT"
        else
            sed -i 's|^\[Service\]|[Service]\nUser=jarvis|' "$WA_UNIT"
        fi
        systemctl daemon-reload
        systemctl is-active --quiet whatsapp-bridge.service && systemctl restart whatsapp-bridge.service
        echo "[Broker] whatsapp-bridge.service laeuft jetzt als jarvis (vorher: ${WA_USER:-root})."
    fi
fi

# 0c. systemd-Haertung + Rotation des Broker-Audits (BSI M1/M2)
#
# Drop-ins fuer jarvis.service und jarvis-broker.service sowie die
# logrotate-Regel – aus DIESER (root-eigenen) Kopie, damit ein Update sie auf
# jeden Bestandsserver bringt. Wirksam ab dem naechsten Neustart des jeweiligen
# Dienstes; Notausgang HAERTUNG=aus in /etc/jarvis/broker.conf.
if [ -f "$CODE_DIR/deploy/security/haertung_installieren.sh" ]; then
    bash "$CODE_DIR/deploy/security/haertung_installieren.sh" "$JARVIS_DIR" \
        || echo "[Broker] WARNUNG: Haertung nicht installiert (rc=$?)." >&2
fi

# 0c2. Node aktuell halten (BSI M6). Ein EIGENER Timer ruft
# deploy/security/node_aktualisieren.sh --automatisch: unter der Ziel-Linie
# stellt es um, auf ihr zieht es den neuesten NodeSource-Stand nach – im
# Hintergrund, damit apt den Broker-Start nicht aufhaelt. Umgestellt wird nur
# ohne Fremd-Entfernungen (sonst Warnung im Journal der Unit); Notschalter
# NODE_AUTO=aus in /etc/jarvis/broker.conf.
# TAEGLICH statt nur beim Start (26.10.2026): bis dahin lief die Unit nur unter
# der Ziel-Linie, ein Sicherheitsstand innerhalb der Linie blieb liegen (ECHT
# auf 24.21.0 bei CVE-2026-111497, behoben in 24.22.1). Der Timer ist
# transient – ein Broker-Neustart legt ihn neu an, deshalb vorher stoppen.
NODE_SKRIPT="$CODE_DIR/deploy/security/node_aktualisieren.sh"
if command -v node >/dev/null 2>&1 && [ -f "$NODE_SKRIPT" ]; then
    bash "$NODE_SKRIPT" --pruefen >/dev/null \
        || echo "[Broker] WARNUNG: Node $(node --version 2>/dev/null) bekommt keine Sicherheitsupdates mehr (BSI M6)." >&2
    systemctl stop jarvis-node-aktualisieren.timer >/dev/null 2>&1
    systemctl reset-failed jarvis-node-aktualisieren.service jarvis-node-aktualisieren.timer >/dev/null 2>&1
    systemd-run --collect --unit=jarvis-node-aktualisieren \
        --on-active=5min --on-calendar=daily --timer-property=RandomizedDelaySec=30min \
        --description="Jarvis: Node-Linie halten und Sicherheitsstand nachziehen" \
        /bin/bash "$NODE_SKRIPT" --automatisch >/dev/null 2>&1 \
        && echo "[Broker] Node $(node --version 2>/dev/null) – Pruefung in wenigen Minuten, danach taeglich (journalctl -u jarvis-node-aktualisieren)." \
        || echo "[Broker] WARNUNG: Node-Timer liess sich nicht anlegen." >&2
fi

# 0d. Verwaiste Shared-Memory-Segmente abraeumen (hart beendetes x11vnc laesst
# je 42 liegen; bei 4096 startet x11vnc nicht mehr – DEV/ECHT 2026-10-05).
# Nur root-eigene, nicht angehaengte Segmente mit totem Erzeuger.
(cd "$CODE_DIR" && python3 -m backend.desktop_control shm-aufraeumen) \
    || echo "[Broker] WARNUNG: SHM-Aufraeumen fehlgeschlagen." >&2

# 1. Display-Erkennung (Prioritaet: LightDM :1, dann :0, dann :10)
# Beim Boot startet lightdm PARALLEL zu diesem Dienst. Ohne Warten landet x11vnc
# dauerhaft auf dem leeren Xvfb :10 (-> schwarzer VNC-Bildschirm), obwohl der
# echte Desktop Sekunden spaeter da ist. Daher: bis zu 60s auf :0/:1 warten,
# solange ein Display-Manager aktiviert ist.
if [ -z "$DISPLAY" ] || [ "$DISPLAY" == ":10" ]; then
    if systemctl is-enabled lightdm >/dev/null 2>&1; then
        for _i in $(seq 1 30); do
            [ -S "/tmp/.X11-unix/X0" ] || [ -S "/tmp/.X11-unix/X1" ] && break
            echo "Warte auf Display-Manager (:0/:1)... ($_i/30)"
            sleep 2
        done
    fi
    if [ -f "/var/run/lightdm/root/:1" ] && [ -S "/tmp/.X11-unix/X1" ]; then
        export DISPLAY=:1
        export XAUTHORITY="/var/run/lightdm/root/:1"
        echo "LightDM-Display :1 erkannt."
    elif [ -S "/tmp/.X11-unix/X0" ]; then
        export DISPLAY=:0
        echo "Physisches Display :0 erkannt."
    else
        export DISPLAY=:10
        echo "Nutze virtuelles Display :10 (Xvfb)."
    fi
fi

# XAUTHORITY ermitteln (fuer :0, bei :1 bereits oben gesetzt)
if [ "$DISPLAY" == ":0" ] && [ -z "$XAUTHORITY" ]; then
    if [ -f "/var/run/lightdm/root/:0" ]; then
        export XAUTHORITY="/var/run/lightdm/root/:0"
    else
        for home_dir in /home/*; do
            if [ -f "$home_dir/.Xauthority" ]; then
                export XAUTHORITY="$home_dir/.Xauthority"
                break
            fi
        done
    fi
fi

echo "Nutze DISPLAY=$DISPLAY mit XAUTHORITY=$XAUTHORITY"

# 2. Jarvis-Ports vor Tailscale ts-input-DROP freischalten (443, 80)
#    6080 ist seit 2026-08-18 NICHT mehr dabei: websockify bindet nur noch
#    loopback (siehe Schritt 6), eine Freigabe waere eine Tuer ohne Raum.
# NUR mit iptables sinnvoll: die ts-input-Kette von Tailscale ist iptables-basiert.
# Auf reinen nft-Systemen (ECHT hat kein /sbin/iptables) gibt es sie nicht – dort
# regelt `jarvis_fw` aus deploy/security/firewall.sh die Freigabe. Ohne diese
# Pruefung schrieb das Skript bei JEDEM Start drei "Kommando nicht gefunden"-Zeilen
# ins Journal und sah damit nach einem Fehler aus, der keiner war.
if command -v iptables >/dev/null 2>&1; then
    for PORT in 443 80; do
        iptables -C INPUT -p tcp --dport $PORT -j ACCEPT 2>/dev/null || \
            iptables -I INPUT 1 -p tcp --dport $PORT -j ACCEPT
    done
fi

# 3. Screensaver und DPMS deaktivieren (verhindert schwarzen Bildschirm bei VNC)
xset s off -dpms 2>/dev/null || true
pkill -f cinnamon-screensaver 2>/dev/null || true
# gsettings als root wirkt NICHT auf die jarvis-Session (falsches dconf-Profil).
# Stattdessen systemweite dconf-Defaults: Sperre/Screensaver fuer ALLE Benutzer aus.
if command -v dconf >/dev/null 2>&1; then
    mkdir -p /etc/dconf/profile /etc/dconf/db/local.d
    grep -q "^system-db:local" /etc/dconf/profile/user 2>/dev/null || \
        printf "user-db:user\nsystem-db:local\n" > /etc/dconf/profile/user
    cat > /etc/dconf/db/local.d/00-jarvis-nolock <<'DCONF'
[org/cinnamon/desktop/screensaver]
lock-enabled=false
idle-activation-enabled=false
[org/cinnamon/desktop/session]
idle-delay=uint32 0
DCONF
    dconf update 2>/dev/null || true
fi

# 4. Bereinigung alter Locks + Xvfb-Fallback nur bei :10
if [ "$DISPLAY" == ":10" ]; then
    rm -f /tmp/.X10-lock
    rm -rf /tmp/.X11-unix/X10
    if ! pgrep -x "Xvfb" > /dev/null; then
        echo "Starte Xvfb auf :10..."
        Xvfb :10 -screen 0 1280x800x24 &
        sleep 2
    fi
    if ! pgrep -f "cinnamon-session" > /dev/null; then
        echo "Starte Cinnamon Desktop..."
        if [ -z "$DBUS_SESSION_BUS_ADDRESS" ]; then
            eval $(dbus-launch --sh-syntax)
            export DBUS_SESSION_BUS_ADDRESS
        fi
        XDG_SESSION_TYPE=x11 cinnamon-session &
        sleep 3
    fi
fi

# 4b. Desktop-Zugang (x11vnc 5900, websockify 6080) nur fuer root und den Dienstbenutzer
#
# BEFUND H11 (BSI-Abgleich 2026-09-29, auf ECHT): x11vnc laeuft als root mit
# `-nopw`. `-localhost` (2026-08-11) haelt das Netz draussen, aber auf dem Host
# selbst konnte JEDER Prozess verbinden – auch die Agent-Shell der
# Domain-Benutzer (jarvis_sandbox, jarvis_sandbox_noinet). Wer dort eine Zeile
# Python ausfuehrt, hatte Maus und Tastatur auf dem Desktop, ohne Jarvis-Login
# und ohne Administrator-Recht. websockify auf 127.0.0.1:6080 ist derselbe Weg
# (proxyt auf 5900), deshalb beide Ports – eine Sperre nur auf 5900 waere durch
# 6080 umgangen, genau wie 2026-08-18.
#
# Erlaubt bleiben die beiden, die den Desktop tatsaechlich brauchen: root
# (websockify, Broker) und der Dienstbenutzer (Backend-Proxy /ws/vnc, der nur
# Administratoren durchlaesst). Alles andere bekommt einen TCP-Reset.
#   * `oif "lo"` statt einer Adresse: trifft auch Verbindungen an die eigene
#     LAN-IP, die der Kernel ebenfalls ueber lo zustellt.
#   * Die Bedingung haengt an skuid: Kernel-Sockets (CIFS/NFS) tragen keine
#     und fallen durch – kein nacktes drop (Vorfall 2026-09-04).
#   * Eigene Tabelle, `table`+`delete`+Neuanlage in EINER Transaktion: kein
#     Zeitfenster ohne Sperre, kein Verdoppeln bei jedem Broker-Start.
# Test: tests/test_bsi_ldap_vnc.py (wendet _vnc_sperre_regeln in einem eigenen
# Netz-Namespace an und misst, wer verbinden darf).
_vnc_erlaubte_uids() {   # $1 = Dienstbenutzer -> "0" oder "0, <uid>"
    local uid
    uid="$(id -u "$1" 2>/dev/null)"
    if [ -n "$uid" ] && [ "$uid" != "0" ]; then echo "0, $uid"; else echo "0"; fi
}
_vnc_sperre_regeln() {   # $1 = erlaubte uids (Ausgabe von _vnc_erlaubte_uids)
    cat <<NFT
table inet jarvis_vnc {}
delete table inet jarvis_vnc
table inet jarvis_vnc {
    chain out {
        type filter hook output priority filter; policy accept;
        oif "lo" tcp dport { 5900, 6080 } meta skuid != { $1 } reject with tcp reset
    }
}
NFT
}
VNC_SVC_USER="$(systemctl show -p User --value jarvis.service 2>/dev/null)"
[ -z "$VNC_SVC_USER" ] && VNC_SVC_USER="jarvis"
VNC_UIDS="$(_vnc_erlaubte_uids "$VNC_SVC_USER")"
if command -v nft >/dev/null 2>&1; then
    if _vnc_sperre_regeln "$VNC_UIDS" | nft -f -; then
        echo "[VNC] Desktop-Ports 5900/6080 lokal nur fuer uid $VNC_UIDS erreichbar."
    else
        echo "[VNC] WARNUNG: Sperre fuer 5900/6080 nicht gesetzt – jeder lokale Prozess erreicht den Desktop." >&2
    fi
else
    echo "[VNC] WARNUNG: nft fehlt – Desktop-Ports 5900/6080 sind fuer jeden lokalen Prozess erreichbar." >&2
fi

# x11vnc laeuft NIE als root (BSI H11-Rest, 2026-10-12): gestartet wird nur noch
# ueber backend/desktop_control.x11vnc_starten – eigener Systembenutzer
# jarvis-vnc, Kopie des X-Cookies, keine Gruppen/Faehigkeiten. Die Shell ruft
# x11vnc nicht mehr selbst auf (eine zweite Startstelle haette die Haertung
# beim naechsten Umzug wieder umgangen, siehe harden_vnc.sh 2026-08-11).
_vnc_start() {   # $1 = Display, $2 = Cookie-Datei (optional)
    (cd "$CODE_DIR" && python3 -m backend.desktop_control vnc-starten "$@")
}

# Altbestand: eine fremde Unit x11vnc.service mit User=root (auf DEV von Hand
# angelegt, nicht aus dem Repo) startet x11vnc mit Restart=always sofort wieder
# als root und belegt 5900 – sie wird abgeschaltet, x11vnc kommt von hier.
if [ -f /etc/systemd/system/x11vnc.service ] \
        && grep -q '^ExecStart=.*x11vnc' /etc/systemd/system/x11vnc.service \
        && ! grep -q '^User=jarvis-vnc' /etc/systemd/system/x11vnc.service \
        && { systemctl is-enabled --quiet x11vnc.service || systemctl is-active --quiet x11vnc.service; }; then
    systemctl disable --now x11vnc.service >/dev/null 2>&1 \
        && { systemctl reset-failed x11vnc.service >/dev/null 2>&1; true; } \
        && echo "[VNC] Fremde Unit x11vnc.service (root) abgeschaltet – x11vnc startet ueber den Broker." \
        || echo "[VNC] WARNUNG: x11vnc.service liess sich nicht abschalten." >&2
fi
# Laeuft x11vnc noch als root (Stand vor dem Umbau), wird er umgestellt.
if pgrep -u root -x x11vnc >/dev/null; then
    echo "[VNC] x11vnc laeuft als root – wird beendet und als jarvis-vnc neu gestartet."
    (cd "$CODE_DIR" && python3 -m backend.desktop_control vnc-beenden)
fi

# Selbstheilung: Laeuft x11vnc (nur) auf dem leeren Xvfb :10, obwohl lightdm
# aktiviert ist, zieht dieser Hintergrund-Watcher auf das echte :0 um, sobald
# dessen X-Socket verfuegbar ist (heilt Boot-Races und lightdm-Neustarts ohne
# Service-Restart; bis ~10 Minuten).
_vnc_upgrade_watcher() {
    systemctl is-enabled lightdm >/dev/null 2>&1 || return 0
    (
        for _i in $(seq 1 150); do
            sleep 4
            [ -S "/tmp/.X11-unix/X0" ] || continue
            _vnc_start :0
            sleep 2
            if pgrep -x x11vnc >/dev/null; then
                pkill -x Xvfb 2>/dev/null   # leeres Fallback-Display aufraeumen
                echo "[VNC-Watcher] x11vnc auf :0 umgezogen."
                exit 0
            fi
            # :0 noch nicht bereit -> zurueck auf :10, weiter warten
            _vnc_start :10
        done
    ) &
    disown 2>/dev/null || true
}

# 5. x11vnc starten
if ! pgrep -x "x11vnc" > /dev/null; then
    echo "Starte x11vnc für $DISPLAY..."
    if [ "$DISPLAY" != ":0" ] && [ -n "$XAUTHORITY" ]; then
        _vnc_start "$DISPLAY" "$XAUTHORITY"
    else
        _vnc_start "$DISPLAY"
    fi
    sleep 3
    if ! pgrep -x "x11vnc" > /dev/null && [ "$DISPLAY" == ":0" ]; then
        echo "x11vnc konnte :0 nicht binden. Fallback auf :10..."
        export DISPLAY=:10
        Xvfb :10 -screen 0 1280x800x24 &
        sleep 2
        openbox --sm-disable &
        _vnc_start :10
        _vnc_upgrade_watcher
    elif [ "$DISPLAY" == ":10" ]; then
        # von vornherein auf Xvfb gelandet -> ebenfalls auf :0 lauern
        _vnc_upgrade_watcher
    fi
fi

# 6. websockify-Fallback – NUR LOKAL (127.0.0.1:6080)
#
# ⚠ HIER LAG EINE OFFENE TUER (gemessen 2026-08-18, ECHT und DEV): websockify
# lauschte auf 0.0.0.0:6080, lieferte das noVNC-Verzeichnis ohne jede Anmeldung
# aus (HTTP 200, sogar mit Directory-Listing) und proxyte auf x11vnc, das mit
# `-nopw` laeuft. Wer den Host im Netz erreichte, hatte damit Maus und Tastatur
# auf dem Desktop – ganz ohne Jarvis-Login. Der Weg ueber Port 443
# (`/novnc` + `/ws/vnc`) verlangt dagegen ein gueltiges Token UND seit dem
# 2026-08-18 Administrator-Rechte.
#
# Dieselbe Klasse wie die x11vnc-Haertung vom 2026-08-11 (`-localhost`): dort
# wurde 5900 geschlossen, 6080 stand weiter offen und hat den Schutz umgangen.
# Der Fallback bleibt erhalten (lokale Diagnose), bindet aber nur noch loopback.
NOVNC_DIR=""
for dir in /usr/share/novnc /usr/share/noVNC /snap/novnc/current/usr/share/novnc; do
    [ -d "$dir" ] && NOVNC_DIR="$dir" && break
done
if [ -n "$NOVNC_DIR" ] && ! pgrep -f "websockify.*6080" > /dev/null; then
    WSOCK_CMD=""
    if command -v /usr/bin/websockify &>/dev/null; then
        WSOCK_CMD="/usr/bin/websockify"
    elif command -v websockify &>/dev/null; then
        WSOCK_CMD="$(command -v websockify)"
    fi
    if [ -n "$WSOCK_CMD" ]; then
        "$WSOCK_CMD" --web="$NOVNC_DIR" 127.0.0.1:6080 localhost:5900 > /var/log/jarvis-websockify.log 2>&1 &
        echo "websockify Fallback gestartet (127.0.0.1:6080, nur lokal)"
    fi
fi

# 6b. Eigentuemerschaft des Arbeitsverzeichnisses geradeziehen
#
# WARUM: Das Backend laeuft unprivilegiert (jarvis.service, User=jarvis) und
# aktualisiert sich per `git pull`. Um eine Datei zu ERSETZEN oder ein
# Verzeichnis ANZULEGEN, braucht git Schreibrecht auf dem uebergeordneten
# Verzeichnis – nicht auf der Datei. Entsteht also irgendwo unter /opt/jarvis
# etwas als root (ein `scp` als root, ein `git pull` als root, ein Skript mit
# sudo), scheitert der naechste Update mit
#     unable to unlink old '<datei>': Keine Berechtigung
#     cannot create directory at '<verzeichnis>': Keine Berechtigung
# und zwar erst dann, wenn ein Commit genau dieses Verzeichnis anfasst. Das kann
# Monate spaeter sein – auf ECHT am 2026-07-31 an einem root-eigenen `tests/`
# passiert, das seit einem frueheren root-Pull dort lag.
#
# Das Backend selbst kann das NICHT reparieren: chown auf fremde Dateien ist
# root-pflichtig. Hier laeuft root ohnehin, deshalb steht die Reparatur hier und
# nicht als weitere Broker-Op (eine neue Op verlangt zusaetzlich einen
# Broker-Neustart auf jedem Server, sonst antwortet der Endpunkt mit 502).
#
# Absichtlich NUR chown, kein chmod: die Rechte auf data/chats, data/documents
# und data/logs (0750) setzt `sandbox.harden_data_dirs()` beim Start des
# Backends, und die Secrets (0600) gehoeren setup_broker.sh. Zwei Stellen, die
# dieselben Modi setzen, driften auseinander.
SVC_USER="$(systemctl show -p User --value jarvis.service 2>/dev/null)"
[ -z "$SVC_USER" ] && SVC_USER="jarvis"
if [ "$SVC_USER" != "root" ] && id "$SVC_USER" &>/dev/null; then
    # Nur zaehlen und melden, wenn wirklich etwas abweicht – ein `chown -R` bei
    # jedem Boot ueber zehntausende Dateien kostet unnoetig Zeit.
    FREMD="$(find "$JARVIS_DIR" ! -user "$SVC_USER" -print -quit 2>/dev/null)"
    if [ -n "$FREMD" ]; then
        ANZAHL="$(find "$JARVIS_DIR" ! -user "$SVC_USER" 2>/dev/null | wc -l)"
        echo "[Rechte] $ANZAHL Datei(en) gehoeren nicht '$SVC_USER' (z.B. ${FREMD#$JARVIS_DIR/}) – korrigiere, sonst scheitert der naechste Update."
        chown -R "$SVC_USER:$SVC_USER" "$JARVIS_DIR" \
            && echo "[Rechte] $JARVIS_DIR gehoert jetzt $SVC_USER" \
            || echo "[Rechte] WARNUNG: chown fehlgeschlagen – Updates koennen scheitern." >&2
    fi
fi

# 6c. Python-Module der Agent-Shell sicherstellen
#
# WARUM HIER: `shell_execute` startet /usr/bin/python3 (bei Domain-Benutzern als
# jarvis_sandbox), NICHT das venv des Backends. Was dort fehlt, kann der Agent
# nicht nachinstallieren (kein Internet, keine Rechte) und auch das Backend
# nicht (pip als root ist root-pflichtig). Ohne diesen Schritt bleibt es
# Handarbeit pro Server – und genau die ist auseinandergelaufen: auf ECHT lagen
# am 2026-08-18 drei Pakete im System-Python, auf DEV neun, und eine
# Excel-Anfrage endete deshalb dort in einer CSV-Notloesung, waehrend sie hier
# gelang. Bei mehreren Servern skaliert nur eine Automatik.
#
# Im HINTERGRUND, damit der Broker-Socket nicht wartet: eine Nachinstallation
# zieht Pakete aus dem Netz und kann Minuten dauern. Das Skript ist idempotent
# und auf einem eingerichteten Server ein No-op (nur die Pruefung, ~1 s).
#
# Abschaltbar mit JARVIS_SANDBOX_PY_AUTO=0 (z.B. auf Servern ohne Netzzugang
# oder wenn der Paketstand bewusst von Hand gepflegt wird).
# Skript aus dem Broker-Code (root-eigen), nie aus dem Projektbaum (K1).
SANDBOX_PY="$CODE_DIR/deploy/sandbox_python.sh"
if [ "${JARVIS_SANDBOX_PY_AUTO:-1}" != "0" ] && [ -f "$SANDBOX_PY" ]; then
    (
        if bash "$SANDBOX_PY" --pruefen >/dev/null 2>&1; then
            :   # alles vorhanden – nichts melden, sonst rauscht jeder Start
        else
            echo "[Sandbox-Python] Module fuer die Agent-Shell fehlen – installiere nach..."
            # Ausgabe erst einsammeln, DANN filtern: eine Pipeline
            # (`bash … | grep | sed`) liefert den Exit-Code des LETZTEN Glieds,
            # der Fehlschlag des Skripts waere damit unsichtbar.
            AUSGABE="$(bash "$SANDBOX_PY" 2>&1)"
            RC=$?
            # Nur die Zusammenfassung ins Journal – die pip-Download-Zeilen sind
            # dutzende Zeilen Rauschen.
            printf '%s\n' "$AUSGABE" | grep -E '^(  [✓✗]|Installiere|✓|✗|⚠)' \
                | sed 's/^/[Sandbox-Python] /'
            if [ "$RC" -eq 0 ]; then
                echo "[Sandbox-Python] Bereit – alle Module vorhanden."
            else
                echo "[Sandbox-Python] WARNUNG: Nachinstallation fehlgeschlagen (rc=$RC; kein Netzzugang?). Der Agent kann dann keine Excel-/PDF-Verarbeitung per Shell leisten – 'bash deploy/sandbox_python.sh' von Hand ausfuehren." >&2
            fi
        fi
    ) &
fi

# 6d. bubblewrap sicherstellen (privates /tmp pro Agent-Lauf)
#
# WARUM HIER: Die Isolation der Laeufe (backend/lauf_tmp.py) haengt an `bwrap`.
# Fehlt das Paket, laeuft alles weiter – aber OHNE Trennung, und dann kann jeder
# Domain-Benutzer die Arbeitskopien aller anderen lesen. Genau dieser Zustand
# soll nicht durch eine vergessene Handinstallation entstehen; dieselbe
# Begruendung wie bei 6c (bei mehreren Servern skaliert nur eine Automatik).
#
# Fail-OPEN mit Meldung: ein Schutz, der still ausfaellt, ist kein Schutz –
# aber die Anwendung fuer eine Verbesserung abzuschalten waere schlimmer.
# Abschaltbar mit JARVIS_BWRAP_AUTO=0.
if [ "${JARVIS_BWRAP_AUTO:-1}" != "0" ] && [ ! -x /usr/bin/bwrap ]; then
    (
        echo "[Lauf-Isolation] bubblewrap fehlt – installiere nach (bis dahin teilen Laeufe /tmp)..."
        AUSGABE="$(DEBIAN_FRONTEND=noninteractive apt-get install -y bubblewrap 2>&1)"
        RC=$?
        if [ "$RC" -eq 0 ] && [ -x /usr/bin/bwrap ]; then
            echo "[Lauf-Isolation] bubblewrap installiert – privates /tmp pro Lauf ist aktiv."
        else
            printf '%s\n' "$AUSGABE" | tail -3 | sed 's/^/[Lauf-Isolation] /' >&2
            echo "[Lauf-Isolation] WARNUNG: bubblewrap nicht installierbar (rc=$RC; kein Netzzugang?). Die Laeufe teilen weiter /tmp – 'apt-get install -y bubblewrap' von Hand nachziehen." >&2
        fi
    ) &
fi

# 6i. ImageMagick sicherstellen (convert/magick fuer die Agent-Shell)
#
# WARUM HIER: Das Modell greift fuer Bildumwandlungen zuerst zu `convert` –
# ECHT 2026-10-06 und 2026-10-12, beide Male bei PDF -> Bild, beide Male
# "convert: Kommando nicht gefunden" (Exit 127). Auf beiden Servern lag nur
# `imagemagick-7-common` (Daten, KEIN Programm). Eine Lernnotiz vom 06.10.
# ("convert fehlt, nimm pdftoppm") hat den zweiten Fall nicht verhindert –
# den Befehl bereitzustellen ist verlaesslicher, als ihn abzugewoehnen.
# Dieselbe Begruendung wie bei 6c/6d: bei mehreren Servern skaliert nur eine
# Automatik, und der Update-Weg startet den Broker bei Aenderungen an dieser
# Datei mit neu (update_manager._BROKER_PFADE).
#
# Fail-OPEN mit Meldung, im Hintergrund (apt darf den Broker-Start nicht
# aufhalten). Abschaltbar mit JARVIS_IMAGEMAGICK_AUTO=0.
if [ "${JARVIS_IMAGEMAGICK_AUTO:-1}" != "0" ] \
        && ! command -v convert >/dev/null 2>&1 \
        && ! command -v magick >/dev/null 2>&1; then
    (
        echo "[ImageMagick] convert/magick fehlen – installiere nach..."
        AUSGABE="$(DEBIAN_FRONTEND=noninteractive apt-get install -y imagemagick 2>&1)"
        RC=$?
        if [ "$RC" -eq 0 ] && { command -v convert >/dev/null 2>&1 || command -v magick >/dev/null 2>&1; }; then
            echo "[ImageMagick] installiert – convert/magick stehen der Agent-Shell zur Verfuegung."
        else
            printf '%s\n' "$AUSGABE" | tail -3 | sed 's/^/[ImageMagick] /' >&2
            echo "[ImageMagick] WARNUNG: nicht installierbar (rc=$RC; kein Netzzugang?). Bildumwandlung per Shell bleibt auf pdftoppm/Pillow angewiesen – 'apt-get install -y imagemagick' von Hand nachziehen." >&2
        fi
    ) &
fi

# 6h. Wurzel der Netzwerk-Freigaben anlegen (/mnt/rag)
#
# WARUM HIER: `/mnt` gehoert root, das Backend laeuft unprivilegiert – es kann
# die Wurzel also nicht selbst anlegen. Der Broker legt den einzelnen
# Einhaengepunkt beim Verbinden zwar mit an, aber bis dahin zeigt die
# Ordnerliste auf ein Verzeichnis, das es nicht gibt: die Freigabe traegt in
# der Oberflaeche ein Warndreieck "Ordner existiert nicht", und das ist eine
# andere Aussage als "nicht verbunden".
#
# Eine Zeile, kein Netzzugriff, idempotent – deshalb synchron und nicht im
# Hintergrund wie 6c–6g. Gemeldet wird nur ein Problem.
if [ ! -d /mnt/rag ]; then
    if mkdir -p /mnt/rag 2>/dev/null; then
        chmod 755 /mnt/rag
    else
        echo "[Freigaben] WARNUNG: /mnt/rag nicht anlegbar. Netzwerk-Freigaben erscheinen bis dahin als 'Ordner existiert nicht'." >&2
    fi
fi

# 6e. Apache Tika sicherstellen (OneNote-Import, *.one)
#
# WARUM HIER: Der Import von OneNote-Abschnitten haengt an Java + tika-app.jar
# (Begruendung samt Messwerten in backend/tools/onenote.py). Beides bringt KEIN
# git pull mit – die jar ist 65 MB und liegt bewusst nicht im oeffentlichen
# Repo. Ohne diesen Schritt bleibt es Handarbeit pro Server, und genau die ist
# hier schon zweimal auseinandergelaufen (Python-Module der Agent-Shell,
# LibreOffice fuer den PDF-Export: "bei dir geht es, bei mir nicht").
# Dieselbe Begruendung wie bei 6c und 6d – bei mehreren Servern skaliert nur
# eine Automatik.
#
# Im HINTERGRUND, damit der Broker-Socket nicht wartet: der erste Lauf
# installiert eine Java-Laufzeit (~199 MB) und laedt 65 MB von Maven Central.
# Das Skript ist idempotent und auf einem eingerichteten Server ein No-op
# (Pruefsummen + Funktionsprobe, ~1 s).
#
# Abschaltbar mit JARVIS_TIKA_AUTO=0 – fuer Server ohne Netzzugang oder wenn
# die jar bewusst von Hand gepflegt wird (dann sagt JARVIS_TIKA_JAR, wo sie
# liegt).
# Skript aus dem Broker-Code, Ziel (vendor/) im Projektbaum – per JARVIS_DIR.
TIKA_SETUP="$CODE_DIR/deploy/tika_setup.sh"
if [ "${JARVIS_TIKA_AUTO:-1}" != "0" ] && [ -f "$TIKA_SETUP" ]; then
    (
        if bash "$TIKA_SETUP" --pruefen >/dev/null 2>&1; then
            :   # Java und jar liegen – nichts melden, sonst rauscht jeder Start
        else
            echo "[OneNote/Tika] Java oder tika-app.jar fehlt – richte ein (laedt ~65 MB)..."
            # Ausgabe erst einsammeln, DANN filtern: eine Pipeline
            # (`bash … | grep | sed`) liefert den Exit-Code des LETZTEN Glieds,
            # der Fehlschlag des Skripts waere damit unsichtbar.
            AUSGABE="$(bash "$TIKA_SETUP" 2>&1)"
            RC=$?
            # Nur die Zusammenfassung ins Journal – die curl-Fortschrittszeilen
            # sind Rauschen und enthalten Wagenruecklaeufe.
            printf '%s\n' "$AUSGABE" | grep -E '^(  [✓✗]|✓|✗|⚠)' \
                | sed 's/^/[OneNote\/Tika] /'
            if [ "$RC" -eq 0 ]; then
                echo "[OneNote/Tika] Bereit – *.one wird beim naechsten Reindex gelesen."
            else
                echo "[OneNote/Tika] WARNUNG: Einrichtung fehlgeschlagen (rc=$RC; kein Netzzugang zu repo1.maven.org?). Das Backend wiederholt den Versuch selbsttaetig (beim Start und sobald eine .one-Datei indiziert werden soll) – bis dahin werden OneNote-Dateien erfasst, aber nicht gelesen. Bleibt es dabei, fehlt der Netzweg: dann JARVIS_TIKA_JAR auf eine von Hand abgelegte tika-app.jar setzen." >&2
            fi
        fi
    ) &
fi

# 6g. AI-Mouse-Anwendung sicherstellen (Bildschirmausschnitt vom Arbeitsplatz)
#
# WARUM HIER: Die Windows-Anwendung wird aus ai-mouse/ uebersetzt (C#/.NET 8).
# Ein git pull bringt die fertige Datei NICHT mit – sie ist 66 MB und liegt
# bewusst nicht im oeffentlichen Repo. Ohne diesen Schritt bleibt der
# Download-Knopf im Portal aus, und eine Meldung wuerde den Administrator ins
# Terminal schicken: genau der Zustand, der fuer den OneNote-Import am
# 2026-09-04 als inakzeptabel zurueckgewiesen wurde. Dieselbe Begruendung wie
# bei 6c/6d/6e – bei mehreren Servern skaliert nur eine Automatik.
#
# Im HINTERGRUND, damit der Broker-Socket nicht wartet: der Bau dauert rund
# 30 Sekunden (gemessen), ohne .NET-SDK kommen ~200 MB apt dazu. Das Skript ist
# idempotent und auf einem eingerichteten Server ein No-op (--pruefen, ~0,01 s).
#
# Gebaut wird als DIENSTBENUTZER – eine als root angelegte Datei in vendor/
# koennte das Backend spaeter nicht ersetzen (Register).
#
# Abschaltbar mit JARVIS_AIMOUSE_AUTO=0 – fuer Server ohne Netzzugang oder wenn
# die Datei von Hand gepflegt wird (dann sagt JARVIS_AIMOUSE_EXE, wo sie liegt).
AIMOUSE_BUILD="$JARVIS_DIR/deploy/ai_mouse_build.sh"
if [ "${JARVIS_AIMOUSE_AUTO:-1}" != "0" ] && [ -f "$AIMOUSE_BUILD" ] && id jarvis >/dev/null 2>&1; then
    (
        # Das Bauskript liegt im PROJEKTBAUM (es baut dessen Quellen) und laeuft
        # deshalb auch beim Pruefen als Dienstbenutzer – als root waere es ein
        # Skript, das jarvis vorher umschreiben kann (K1).
        if runuser -u jarvis -- bash "$AIMOUSE_BUILD" --pruefen >/dev/null 2>&1; then
            :   # liegt bereit – nichts melden, sonst rauscht jeder Start
        else
            echo "[AI-Mouse] Anwendung fehlt – baue sie (etwa 30 s)..."
            if ! command -v dotnet >/dev/null 2>&1; then
                echo "[AI-Mouse] Kein .NET-SDK – installiere dotnet-sdk-8.0 (~200 MB)..."
                DEBIAN_FRONTEND=noninteractive apt-get update -qq >/dev/null 2>&1
                DEBIAN_FRONTEND=noninteractive apt-get install -y -qq dotnet-sdk-8.0 >/dev/null 2>&1
            fi
            # Ausgabe erst einsammeln, DANN filtern: eine Pipeline liefert den
            # Exit-Code des LETZTEN Glieds, der Fehlschlag waere unsichtbar.
            AUSGABE="$(runuser -u jarvis -- bash "$AIMOUSE_BUILD" 2>&1)"
            RC=$?
            printf '%s\n' "$AUSGABE" | sed 's/^/[AI-Mouse] /'
            if [ "$RC" -ne 0 ]; then
                echo "[AI-Mouse] WARNUNG: Bau fehlgeschlagen (rc=$RC). Das Backend wiederholt den Versuch selbsttaetig (beim Start und sobald jemand das Paket herunterladen will) – bis dahin bleibt der Download im Portal aus. Bleibt es dabei, fehlt das .NET-SDK oder der Netzweg zu NuGet: dann JARVIS_AIMOUSE_EXE auf eine von Hand gebaute AiMouse.exe setzen." >&2
            fi
        fi
    ) &
fi

# 6f. Internet-Sperre: veraltete Regel nachziehen
#
# ⚠ DER FIX VOM 2026-09-04 KOMMT SONST AUF KEINEM SERVER AN. Er steckt im
# RENDERER (backend/egress_guard.py::_render_nft) – die LAUFENDEN nft-Regeln
# entstehen aber ausschliesslich bei egress_setup, und das laeuft nur auf
# Knopfdruck unter Einstellungen -> Sicherheit -> Internet-Zugang. Weder ein
# git pull noch die Update-Pille noch ein Dienst-Neustart fassen sie an.
#
# Die Folge waere still und teuer: auf jedem System mit aktiver Sperre
# scheitert JEDE SMB-/NFS-Freigabe, weil ein 'drop' ohne Benutzerbindung auch
# die Kernel-Sockets von CIFS/NFS trifft (die tragen keine skuid). Jeder
# Userspace-Test gelingt dabei – die Fehlersuche laeuft zuverlaessig in die
# falsche Richtung. Dieselbe Begruendung wie bei 6c/6d/6e: bei mehreren
# Servern skaliert nur eine Automatik.
#
# ⚠ ES WIRD NUR NACHGEZOGEN, NIE EINGERICHTET. Gibt es gar keine Kette, ist die
# Sperre bewusst aus – dann passiert hier NICHTS. Ein Paketfilter, der sich bei
# jedem Start selbst aufsetzt, waere eine andere Kategorie als eine
# nachgeladene jar. Fail-safe in die ruhige Richtung: bei jeder Unklarheit
# (kein nft, keine Kette, Ausnahme) bleibt alles wie es ist.
#
# Abschaltbar mit JARVIS_EGRESS_AUTOFIX=0.
if [ "${JARVIS_EGRESS_AUTOFIX:-1}" != "0" ] && command -v nft >/dev/null 2>&1; then
    (
        # Nur die WIRKSAMEN Regeln zaehlen, nicht die Datei: die kann laengst
        # korrekt sein, waehrend im Kernel die alte Fassung haengt – nach einem
        # Update ist genau das der Regelfall.
        KETTE="$(nft list table inet jarvis_egress 2>/dev/null)"
        if [ -n "$KETTE" ]; then
            # Ein 'drop' OHNE skuid trifft auch Verkehr ohne Socket-Eigentuemer.
            NACKT="$(printf '%s\n' "$KETTE" | grep -E '\bdrop\b' | grep -vE '\bskuid\b' | head -3)"
            if [ -n "$NACKT" ]; then
                echo "[Egress] Die laufende Sperre enthaelt ein 'drop' ohne Benutzerbindung – ziehe nach (SMB/NFS waeren sonst tot)."
                # System-Python aus dem Broker-Code, nicht das venv des Dienstes (K1).
                AUSGABE="$(cd "$CODE_DIR" && JARVIS_PROJECT_ROOT="$JARVIS_DIR" /usr/bin/python3 -c 'from backend import egress_guard as e; r=e.setup(); print("OK" if r.get("ok") else "FEHLER"); [print(" ", s["name"], "ok" if s["ok"] else "FEHLER", s.get("detail","")[:120]) for s in r.get("steps",[])]' 2>&1)"
                RC=$?
                printf '%s\n' "$AUSGABE" | sed 's/^/[Egress] /'
                # ⚠ MASSGEBLICH IST DER ZUSTAND, NICHT DER RUECKGABEWERT: ein
                # "Erfolg", der die alte Regel stehen laesst, ist eine Zusage,
                # die der naechste Mount kassiert.
                REST="$(nft list table inet jarvis_egress 2>/dev/null | grep -E '\bdrop\b' | grep -vE '\bskuid\b' | head -1)"
                if [ -z "$REST" ]; then
                    echo "[Egress] ✓ nachgezogen – Netzwerk-Freigaben funktionieren wieder."
                else
                    echo "[Egress] WARNUNG: die alte Regel steht weiterhin (rc=$RC). Abhilfe von Hand: Einstellungen -> Sicherheit -> Internet-Zugang -> 'Einrichten / Reparieren'." >&2
                fi
            fi
        fi
    ) &
fi

# 7. Root-Broker starten (Vordergrund-Prozess dieses Dienstes)
echo "Starte Root-Broker (Code: $CODE_DIR, Daten: $JARVIS_DIR)..."
export JARVIS_BROKER_GROUP="${JARVIS_BROKER_GROUP:-jarvis}"
export JARVIS_PROJECT_ROOT="$JARVIS_DIR"
# System-Python (root-eigen) und das Arbeitsverzeichnis im Broker-Code: `-m`
# setzt das Arbeitsverzeichnis an den Anfang von sys.path – in /opt/jarvis
# gestartet, kaeme `backend` wieder aus dem Baum des Dienstbenutzers.
cd "$CODE_DIR"
exec /usr/bin/python3 -m backend.broker.daemon
