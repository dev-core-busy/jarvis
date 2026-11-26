#!/usr/bin/env bash
# Ausgangsfilter fuer den ganzen Host (Haertung D1).
#
# Heute filtert nur `inet jarvis_egress` (backend/egress_guard.py) – und zwar
# allein den Sandbox-Benutzer. Dieses Skript legt eine EIGENE Tabelle
# `inet jarvis_ausgang` an, die jeden neuen ausgehenden Verkehr gegen eine
# Freigabeliste je Benutzer, Protokoll, Port und Ziel prueft.
#
# ZWEI STUFEN (MODUS in der Konfiguration):
#   protokoll  policy accept – nichts wird verworfen, aber jede neue Verbindung,
#              die keine Freigabe trifft, landet gedrosselt im Kernel-Journal
#              (Praefix "nft-aus-frei: ", mit uid). Vorgabe, wenn MODUS fehlt.
#   sperre     policy drop – dieselbe Zeile mit "nft-aus-drop: ", das Paket
#              wird verworfen.
# Erst wenn der Protokollmodus ueber einen laengeren Zeitraum nichts mehr
# meldet, was gebraucht wird, darf die Sperre kommen.
#
# KONFIGURATION: /etc/jarvis/ausgang.conf (umlenkbar mit JARVIS_AUSGANG_CONF).
# Echte Adressen stehen NUR dort, nie im Repo – Vorlage mit Platzhaltern:
# deploy/security/ausgang.conf.beispiel. Format, eine Freigabe je Zeile:
#   MODUS=protokoll|sperre
#   erlaube <benutzer|alle> <tcp|udp|icmp> <ports|-> <ziele|*>
#     benutzer  Name oder uid; wird beim Erzeugen in die uid aufgeloest
#               (unbekannt = Abbruch). "alle" bindet an KEINEN Benutzer –
#               noetig fuer Kernel-Sockets (CIFS), die keinen Eigentuemer haben.
#     ports     "443" oder "22,443" oder "8000-8100"; "-" = alle Ports
#               (bei icmp Pflicht).
#     ziele     IPv4-Adressen/Netze, kommagetrennt; "*" = jedes Ziel.
#               "alle ... *" wird abgewiesen: das waere kein Filter mehr.
#
# Aufruf:
#   ausgang.sh --zeigen     Regelsatz ausgeben (kein root noetig, fuer Waechter)
#   ausgang.sh --pruefen    Zustand melden, nichts aendern
#   ausgang.sh --anwenden   pruefen (nft -c), laden, speichern, Boot-Unit an
#   ausgang.sh --entfernen  Tabelle, gespeicherten Satz und Unit entfernen
#
# Die Tabelle stoert die anderen nicht: bei nft hat jede Tabelle eigene Ketten,
# ein Paket muss alle Hooks passieren. `jarvis_egress` bleibt unberuehrt.
set -euo pipefail

KONF="${JARVIS_AUSGANG_CONF:-/etc/jarvis/ausgang.conf}"
ABLAGE="${JARVIS_AUSGANG_ABLAGE:-/etc/jarvis/ausgang.nft}"
UNIT_DIR="${JARVIS_UNIT_DIR:-/etc/systemd/system}"
UNIT="jarvis-ausgang.service"
TABELLE="jarvis_ausgang"
LOG_RATE="30/minute"
PRAEFIX_FREI="nft-aus-frei: "
PRAEFIX_DROP="nft-aus-drop: "

fehler() { echo "FEHLER: $*" >&2; exit 1; }

MODUS="protokoll"
REGELN=()

# _uid <name|zahl> – gibt die uid aus oder bricht ab. Zahlen werden nicht
# nachgeschlagen: eine uid ohne Namen (Kernel-Thread, geloeschter Benutzer) ist
# zulaessig, ein Tippfehler im Namen nicht.
_uid() {
    if [[ "$1" =~ ^[0-9]+$ ]]; then echo "$1"; return; fi
    id -u -- "$1" 2>/dev/null || fehler "Benutzer unbekannt: $1"
}

_ports_pruefen() {
    local p="$1" teil
    [[ "$p" == "-" ]] && return 0
    IFS=, read -ra teile <<<"$p"
    for teil in "${teile[@]}"; do
        if [[ "$teil" =~ ^([0-9]{1,5})(-([0-9]{1,5}))?$ ]]; then
            (( BASH_REMATCH[1] >= 1 && BASH_REMATCH[1] <= 65535 )) || fehler "Port ausserhalb 1-65535: $teil"
            if [[ -n "${BASH_REMATCH[3]}" ]]; then
                (( BASH_REMATCH[3] <= 65535 && BASH_REMATCH[3] > BASH_REMATCH[1] )) || fehler "Portbereich ungueltig: $teil"
            fi
        else
            fehler "Port ungueltig: $teil"
        fi
    done
}

_ziele_pruefen() {
    local z="$1" teil o
    [[ "$z" == "*" ]] && return 0
    IFS=, read -ra teile <<<"$z"
    for teil in "${teile[@]}"; do
        [[ "$teil" =~ ^([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})(/([0-9]{1,2}))?$ ]] \
            || fehler "Ziel ungueltig (nur IPv4/Netz): $teil"
        for o in 1 2 3 4; do (( BASH_REMATCH[o] <= 255 )) || fehler "Ziel ungueltig: $teil"; done
        [[ -z "${BASH_REMATCH[6]}" ]] || (( BASH_REMATCH[6] <= 32 )) || fehler "Netzmaske ungueltig: $teil"
    done
}

# Liest die Konfiguration und baut je Freigabe eine nft-Zeile. Jeder Fehler
# bricht ab, BEVOR etwas ausgegeben wird – ein halber Satz waere schlimmer als
# keiner.
_laden() {
    [[ -f "$KONF" ]] || fehler "Konfiguration fehlt: $KONF (Vorlage: deploy/security/ausgang.conf.beispiel)"
    local zeile nr=0 wort benutzer proto ports ziele rest regel uid
    while IFS= read -r zeile || [[ -n "$zeile" ]]; do
        nr=$((nr + 1))
        zeile="${zeile%%#*}"
        zeile="$(echo "$zeile" | tr -s '[:space:]' ' ' | sed 's/^ //; s/ $//')"
        [[ -z "$zeile" ]] && continue
        if [[ "$zeile" =~ ^MODUS=(.*)$ ]]; then
            case "${BASH_REMATCH[1]}" in
                protokoll|sperre) MODUS="${BASH_REMATCH[1]}" ;;
                *) fehler "Zeile $nr: MODUS muss protokoll oder sperre sein" ;;
            esac
            continue
        fi
        read -r wort benutzer proto ports ziele rest <<<"$zeile"
        [[ "$wort" == "erlaube" && -n "${ziele:-}" && -z "${rest:-}" ]] \
            || fehler "Zeile $nr: erwartet 'erlaube <benutzer|alle> <proto> <ports|-> <ziele|*>'"
        case "$proto" in tcp|udp|icmp) ;; *) fehler "Zeile $nr: Protokoll muss tcp, udp oder icmp sein" ;; esac
        [[ "$proto" != "icmp" || "$ports" == "-" ]] || fehler "Zeile $nr: icmp hat keine Ports (\"-\")"
        [[ "$benutzer" != "alle" || "$ziele" != "*" ]] || fehler "Zeile $nr: 'alle' mit Ziel '*' waere kein Filter"
        _ports_pruefen "$ports"
        _ziele_pruefen "$ziele"
        regel=""
        if [[ "$benutzer" != "alle" ]]; then
            uid="$(_uid "$benutzer")"
            regel+="meta skuid $uid "
        fi
        [[ "$ziele" == "*" ]] || regel+="ip daddr { ${ziele//,/, } } "
        if [[ "$proto" == "icmp" ]]; then
            regel+="ip protocol icmp "
        elif [[ "$ports" == "-" ]]; then
            regel+="meta l4proto $proto "
        else
            regel+="$proto dport { ${ports//,/, } } "
        fi
        REGELN+=("${regel}accept comment \"$benutzer\"")
    done < "$KONF"
}

# Der Regelsatz als Text – eine Quelle fuer --zeigen und --anwenden.
# `table` + `delete` am Anfang ersetzt eine vorhandene Tabelle in DERSELBEN
# Transaktion (nft -f haengt sonst an und verdoppelt jede Regel, siehe
# firewall.sh) und ist auch beim ersten Lauf fehlerfrei.
# Reihenfolge: loopback und bestehende Verbindungen zuerst, dann die
# Freigaben, die Log-Zeile ZULETZT – davor protokollierte sie Erlaubtes.
_regeln_text() {
    local policy praefix r
    if [[ "$MODUS" == "sperre" ]]; then policy="drop"; praefix="$PRAEFIX_DROP"
    else policy="accept"; praefix="$PRAEFIX_FREI"; fi
    echo "table inet $TABELLE {}"
    echo "delete table inet $TABELLE"
    echo "table inet $TABELLE {"
    echo "    chain out {"
    echo "        type filter hook output priority filter; policy $policy;"
    echo "        oifname \"lo\" accept"
    echo "        ct state established,related accept"
    for r in "${REGELN[@]}"; do echo "        $r"; done
    echo "        limit rate $LOG_RATE log prefix \"$praefix\" flags skuid"
    echo "    }"
    echo "}"
}

_ist_root() { [[ "$(id -u)" == "0" ]] || fehler "nur als root"; }

zeigen() {
    _laden
    _regeln_text
}

pruefen() {
    echo "── Konfiguration: $KONF"
    if [[ -f "$KONF" ]]; then
        ( _laden; echo "   MODUS=$MODUS, ${#REGELN[@]} Freigaben" ) || echo "   ungueltig (siehe FEHLER)"
    else
        echo "   fehlt"
    fi
    echo "── Tabelle inet $TABELLE:"
    if nft list table inet "$TABELLE" >/dev/null 2>&1; then
        nft list chain inet "$TABELLE" out | grep -E 'policy' | sed 's/^ */   /'
    else
        echo "   nicht geladen"
    fi
    echo "── Boot-Unit $UNIT: $(systemctl is-enabled "$UNIT" 2>/dev/null || echo fehlt)"
    echo "── Gespeicherter Satz: $([[ -f "$ABLAGE" ]] && echo "$ABLAGE" || echo fehlt)"
}

anwenden() {
    _ist_root
    _laden
    local neu="$ABLAGE.neu"
    mkdir -p "$(dirname "$ABLAGE")"
    _regeln_text > "$neu"
    # Erst pruefen, dann laden, dann ersetzen: eine kaputte Datei darf weder
    # den laufenden Satz noch den des naechsten Starts verdraengen.
    if ! nft -c -f "$neu"; then
        echo "FEHLER: Regelsatz ungueltig – nichts geaendert ($neu zur Ansicht)." >&2
        exit 1
    fi
    nft -f "$neu"
    mv -f "$neu" "$ABLAGE"
    chmod 0600 "$ABLAGE"
    # Unit wie jarvis-firewall.service: frueh im Start, ohne `|| true` – ein
    # Fehlschlag haelt den Start nicht an, wird aber sichtbar (systemctl --failed).
    cat > "$UNIT_DIR/$UNIT" <<UNITTEXT
[Unit]
Description=Jarvis Ausgangsfilter (nftables, Haertung D1)
DefaultDependencies=no
Before=network-pre.target
Wants=network-pre.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/nft -f $ABLAGE

[Install]
WantedBy=sysinit.target
UNITTEXT
    systemctl daemon-reload
    systemctl enable "$UNIT" >/dev/null 2>&1
    echo "Ausgangsfilter geladen (MODUS=$MODUS, ${#REGELN[@]} Freigaben), gespeichert in $ABLAGE, $UNIT aktiv."
}

entfernen() {
    _ist_root
    nft delete table inet "$TABELLE" 2>/dev/null || true
    systemctl disable "$UNIT" >/dev/null 2>&1 || true
    rm -f "$UNIT_DIR/$UNIT" "$ABLAGE"
    systemctl daemon-reload
    if nft list table inet "$TABELLE" >/dev/null 2>&1; then
        fehler "Tabelle inet $TABELLE ist noch da"
    fi
    echo "Ausgangsfilter entfernt."
}

case "${1:-}" in
    --zeigen)    zeigen ;;
    --pruefen)   pruefen ;;
    --anwenden)  anwenden ;;
    --entfernen) entfernen ;;
    *) echo "Aufruf: $0 --zeigen | --pruefen | --anwenden | --entfernen" >&2; exit 2 ;;
esac
