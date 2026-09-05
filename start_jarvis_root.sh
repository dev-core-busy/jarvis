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

JARVIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$JARVIS_DIR"

if [ "$(id -u)" != "0" ]; then
    echo "FEHLER: start_jarvis_root.sh muss als root laufen (jarvis-broker.service)." >&2
    exit 1
fi

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
            pkill -x x11vnc 2>/dev/null; sleep 1
            x11vnc -localhost -display :0 -auth guess -shared -forever -nopw -bg -quiet -rfbport 5900
            sleep 2
            if pgrep -x x11vnc >/dev/null; then
                pkill -x Xvfb 2>/dev/null   # leeres Fallback-Display aufraeumen
                echo "[VNC-Watcher] x11vnc auf :0 umgezogen."
                exit 0
            fi
            # :0 noch nicht bereit -> zurueck auf :10, weiter warten
            x11vnc -localhost -display :10 -rfbport 5900 -shared -forever -nopw -bg -quiet
        done
    ) &
    disown 2>/dev/null || true
}

# 5. x11vnc starten
if ! pgrep -x "x11vnc" > /dev/null; then
    echo "Starte x11vnc für $DISPLAY..."
    if [ "$DISPLAY" == ":0" ]; then
        x11vnc -localhost -display :0 -auth guess -shared -forever -nopw -bg -quiet -rfbport 5900
    elif [ -n "$XAUTHORITY" ]; then
        x11vnc -localhost -display "$DISPLAY" -auth "$XAUTHORITY" -shared -forever -nopw -bg -quiet -rfbport 5900
    else
        x11vnc -localhost -display "$DISPLAY" -rfbport 5900 -shared -forever -nopw -bg -quiet
    fi
    sleep 3
    if ! pgrep -x "x11vnc" > /dev/null && [ "$DISPLAY" == ":0" ]; then
        echo "x11vnc konnte :0 nicht binden. Fallback auf :10..."
        export DISPLAY=:10
        Xvfb :10 -screen 0 1280x800x24 &
        sleep 2
        openbox --sm-disable &
        x11vnc -localhost -display :10 -rfbport 5900 -shared -forever -nopw -bg -quiet
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
SANDBOX_PY="$JARVIS_DIR/deploy/sandbox_python.sh"
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
TIKA_SETUP="$JARVIS_DIR/deploy/tika_setup.sh"
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
                AUSGABE="$(./venv/bin/python -c 'from backend import egress_guard as e; r=e.setup(); print("OK" if r.get("ok") else "FEHLER"); [print(" ", s["name"], "ok" if s["ok"] else "FEHLER", s.get("detail","")[:120]) for s in r.get("steps",[])]' 2>&1)"
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
echo "Starte Root-Broker..."
export JARVIS_BROKER_GROUP="${JARVIS_BROKER_GROUP:-jarvis}"
exec ./venv/bin/python -m backend.broker.daemon
