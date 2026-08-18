#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Paketfilter: DROP als Vorgabe, nur die gebrauchten Ports offen
#
# DER BEFUND (gemessen 2026-08-11): Die INPUT-Chain hatte `policy ACCEPT` und
# darunter drei ACCEPT-Regeln fuer 80, 443 und 6080 – aber KEINE abschliessende
# DROP-Regel. Die drei Regeln erlaubten also nur, was ohnehin erlaubt war: offen
# war alles, was lauscht. Auf DEV waren das zusaetzlich 22 (SSH) und 3389 (xrdp),
# auf ECHT 5900 (x11vnc, ohne Passwort), 111 (rpcbind) und 3128 (squid).
#
# WARUM DIE REIHENFOLGE HIER LEBENSWICHTIG IST: wer `policy DROP` setzt, bevor
# SSH und ESTABLISHED erlaubt sind, sperrt sich selbst aus – ueber genau die
# Verbindung, mit der er arbeitet. Deshalb wird die Policy ZULETZT gesetzt, und
# `--test` legt vorher einen Rueckfall-Timer, der die Regeln nach n Sekunden
# wiederherstellt, falls die Sitzung abbricht.
#
# TAILSCALE bleibt unangetastet: die `ts-input`/`ts-forward`-Chains gehoeren dem
# Dienst, werden von ihm verwaltet und laufen VOR den eigenen Regeln (INPUT
# springt als erstes dorthin). Sie werden nicht geleert.
#
#   bash deploy/security/firewall.sh --test [sekunden]   # mit Rueckfall-Timer
#   bash deploy/security/firewall.sh --anwenden          # dauerhaft
#   bash deploy/security/firewall.sh --status
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

# Offen nach aussen. Wer hier etwas ergaenzt, sollte dazu sagen, WARUM – ein
# Port ohne Begruendung ist der Anfang des Zustands, den dieses Skript behebt.
TCP_OFFEN=(
    22      # SSH – Administration. OHNE DIESE ZEILE SPERRT SICH DAS SKRIPT AUS.
    80      # HTTP, leitet auf HTTPS um
    443     # Jarvis (FastAPI) – hierueber laeuft auch der Desktop:
            #   /novnc (Oberflaeche) + /ws/vnc (Datenstrom), beides mit Token
            #   und seit 2026-08-18 nur fuer Administratoren.
)
# 6080 IST HIER BEWUSST NICHT MEHR DRIN (gemessen und entfernt 2026-08-18).
# Der Kommentar an dieser Stelle lautete "der EINZIGE vorgesehene Weg zum
# Desktop" – das war falsch und teuer: websockify lauschte auf 0.0.0.0:6080,
# lieferte noVNC OHNE JEDE ANMELDUNG aus (HTTP 200 samt Directory-Listing) und
# proxyte auf x11vnc, das mit `-nopw` laeuft. Wer den Host im Netz erreichte,
# hatte Maus und Tastatur auf dem Desktop – die x11vnc-Haertung vom 2026-08-11
# (`-localhost` auf 5900) war damit umgangen. websockify bindet jetzt nur noch
# 127.0.0.1 (start_jarvis*.sh), der Port braucht also gar keine Freigabe mehr.
# xrdp (3389) wird nur freigegeben, wenn der Dienst auf DIESEM Host laeuft. Auf
# DEV ist er aktiv und wird benutzt, auf ECHT gibt es ihn nicht – eine feste
# Freigabe waere dort ein offener Port fuer nichts.
if systemctl is-active --quiet xrdp 2>/dev/null || ss -tlnH 2>/dev/null | grep -q ':3389'; then
    TCP_OFFEN+=(3389)
fi
# Ausdruecklich NICHT freigegeben, obwohl es lauscht (Befunde vom 2026-08-11):
#   111  rpcbind – braucht von aussen niemand
#   3128 SSH-Tunnel auf einen Squid (`ssh -L *:3128 …`, seit Wochen als root).
#        Der Tunnel bleibt unangetastet: apt-Updates haengen daran, und der
#        Filter macht ihn von aussen dicht, ohne einen laufenden Prozess zu
#        stoeren. Wer ihn richtig stellen will: `-L 127.0.0.1:3128` statt `*`.
SICHERUNG_DIR=/root/fw-backup

_ist_root() { [[ $EUID -eq 0 ]] || { echo "Bitte als root ausfuehren."; exit 1; }; }

status() {
    if ! _hat_iptables; then
        echo "── nftables: Tabelle jarvis_fw ──────────────────────────"
        nft list table inet jarvis_fw 2>/dev/null | grep -E 'policy|dport|accept' | sed 's/^/  /' \
            || echo "  (Tabelle jarvis_fw existiert nicht – kein Filter aktiv)"
        echo "── Lauschend auf allen Adressen ─────────────────────────"
        ss -tlnH | awk '{if ($4 !~ /^127\.0\.0\.1/ && $4 !~ /^\[::1\]/) print "  " $4}' | sort -u
        return
    fi
    echo "── INPUT-Policy ─────────────────────────────────────────"
    iptables -S INPUT | head -1
    ip6tables -S INPUT 2>/dev/null | head -1
    echo "── Freigaben (TCP) ──────────────────────────────────────"
    # Die Freigaben stehen in der eigenen Kette JARVIS-IN, nicht in INPUT. Die
    # erste Fassung grepte nur INPUT und meldete "(keine)", obwohl fuenf Regeln
    # standen – eine Anzeige, die den eigenen Zustand verschweigt.
    { iptables -S JARVIS-IN 2>/dev/null; iptables -S INPUT; } \
        | grep -E '\-\-dport' | sed 's/^/  /' || echo "  (keine)"
    echo "── Lauschend auf allen Adressen (waere ohne Freigabe gefiltert) ─"
    ss -tlnH | awk '{split($4,a,":"); port=a[length(a)];
                     if ($4 !~ /^127\.0\.0\.1/ && $4 !~ /^\[::1\]/) print "  " $4, "(Port " port ")"}' \
        | sort -u
}

sichern() {
    mkdir -p "$SICHERUNG_DIR"
    local ts; ts=$(date +%Y%m%d-%H%M%S)
    if _hat_iptables; then
        iptables-save  > "$SICHERUNG_DIR/iptables-$ts.rules"
        ip6tables-save > "$SICHERUNG_DIR/ip6tables-$ts.rules" 2>/dev/null || true
        echo "$SICHERUNG_DIR/iptables-$ts.rules"
    else
        nft list ruleset > "$SICHERUNG_DIR/nft-$ts.rules"
        echo "$SICHERUNG_DIR/nft-$ts.rules"
    fi
}

# Gibt es iptables? Auf DEV ja (iptables-nft), auf ECHT NICHT – dort ist nur
# `nft` vorhanden. Ein zweites Skript waere Drift-Gefahr, deshalb beide Wege
# hier, mit derselben Portliste als einziger Quelle.
_hat_iptables() { command -v iptables >/dev/null 2>&1; }

# ── nftables-Weg ─────────────────────────────────────────────────────────────
# EIGENE Tabelle `inet jarvis_fw`. Die vorhandene `inet jarvis_egress`
# (backend/egress_guard.py, Ausgangssperre fuer den Sandbox-Benutzer) wird NICHT
# angefasst: bei nft hat jede Tabelle ihre eigenen Ketten, und ein Paket muss
# alle Hooks passieren – die beiden stoeren sich also nicht.
regeln_setzen_nft() {
    local ports=""
    local p
    for p in "${TCP_OFFEN[@]}"; do ports+="$p, "; done
    ports="${ports%, }"
    # `nft -f` mit einer Tabellendefinition HAENGT AN, es ersetzt nicht: ein
    # zweiter Lauf (erst --test, dann --anwenden) verdoppelte jede Regel. Auf ECHT
    # nachgemessen: 2x jede Zeile. Deshalb die eigene Tabelle vorher wegwerfen –
    # `delete` in derselben Transaktion, damit zwischen Loeschen und Anlegen kein
    # Zeitfenster ohne Filter entsteht. Das `table`+`delete`-Paar am Anfang macht
    # das auch beim ERSTEN Lauf fehlerfrei (delete auf eine nicht vorhandene
    # Tabelle waere sonst ein Fehler).
    nft -f - <<NFT
table inet jarvis_fw {}
delete table inet jarvis_fw
table inet jarvis_fw {
    chain input {
        type filter hook input priority filter; policy drop;

        iif lo accept
        ct state established,related accept
        ip protocol icmp accept
        ip6 nexthdr ipv6-icmp accept
        tcp dport { $ports } ct state new accept
    }
    chain forward {
        type filter hook forward priority filter; policy drop;
    }
}
NFT
}

_nft_speichern() {
    mkdir -p /etc/jarvis
    # NUR die eigene Tabelle sichern – ein `nft list ruleset` wuerde die
    # Tailscale- und egress_guard-Tabellen mitschreiben und beim Laden
    # verdoppeln.
    { echo 'table inet jarvis_fw'; echo 'delete table inet jarvis_fw'; \
      nft list table inet jarvis_fw; } > /etc/jarvis/firewall.nft
}

regeln_setzen() {
    local ipt
    for ipt in iptables ip6tables; do
        command -v "$ipt" >/dev/null || continue

        # Eigene Kette, damit die Tailscale-Regeln und die Chain-Struktur
        # unberuehrt bleiben. Vorhandene Fassung leeren = idempotent.
        "$ipt" -N JARVIS-IN 2>/dev/null || "$ipt" -F JARVIS-IN

        # 1) Loopback zuerst: Broker-Socket, WhatsApp-Bridge (3001), CUPS und
        #    jeder localhost-Aufruf des Backends laufen darueber.
        "$ipt" -A JARVIS-IN -i lo -j ACCEPT
        # 2) Antworten auf ausgehende Verbindungen. OHNE DIESE ZEILE bricht
        #    alles Ausgehende: DNS, apt, die LLM-Anbieter, git.
        "$ipt" -A JARVIS-IN -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
        # 3) ICMP: ping und – wichtiger – MTU-Discovery. Ein pauschales DROP
        #    von ICMP erzeugt haengende Verbindungen, die niemand mit der
        #    Firewall in Verbindung bringt.
        if [[ "$ipt" == "iptables" ]]; then
            "$ipt" -A JARVIS-IN -p icmp -j ACCEPT
        else
            "$ipt" -A JARVIS-IN -p ipv6-icmp -j ACCEPT
        fi
        # 4) Die vorgesehenen Dienste
        local p
        for p in "${TCP_OFFEN[@]}"; do
            "$ipt" -A JARVIS-IN -p tcp --dport "$p" -m conntrack --ctstate NEW -j ACCEPT
        done

        # Kette einhaengen (nur einmal) – NACH ts-input, damit Tailscale zuerst
        # entscheidet.
        "$ipt" -C INPUT -j JARVIS-IN 2>/dev/null || "$ipt" -A INPUT -j JARVIS-IN

        # Die alten Einzelregeln in INPUT sind jetzt doppelt: entfernen, damit
        # nur noch EINE Stelle die Freigaben bestimmt.
        for p in 80 443 6080; do
            while "$ipt" -C INPUT -p tcp --dport "$p" -j ACCEPT 2>/dev/null; do
                "$ipt" -D INPUT -p tcp --dport "$p" -j ACCEPT
            done
        done

        # 5) ZULETZT die Policy. Vorher waere jede der Zeilen oben ein Rennen
        #    gegen die eigene SSH-Verbindung.
        "$ipt" -P INPUT DROP
        # Der Host routet nicht (Tailscale bringt seine ts-forward-Regeln selbst
        # mit und laeuft davor).
        "$ipt" -P FORWARD DROP
        "$ipt" -P OUTPUT ACCEPT
    done
}

persistieren() {
    # Kein netfilter-persistent installiert – die Regeln werden beim Boot aus
    # der gespeicherten Datei geladen. Eigene Unit statt eines Eintrags in
    # start_jarvis_root.sh: der Filter soll stehen, BEVOR Dienste lauschen,
    # und auch dann, wenn der Jarvis-Bootstrap scheitert.
    mkdir -p /etc/jarvis
    if ! _hat_iptables; then
        _nft_speichern
        cat > /etc/systemd/system/jarvis-firewall.service <<'UNIT2'
[Unit]
Description=Jarvis Paketfilter (nftables, DROP als Vorgabe)
DefaultDependencies=no
Before=network-pre.target
Wants=network-pre.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c '/usr/sbin/nft -f /etc/jarvis/firewall.nft || true'

[Install]
WantedBy=sysinit.target
UNIT2
        systemctl daemon-reload
        systemctl enable jarvis-firewall.service >/dev/null 2>&1
        echo "Regeln gespeichert (/etc/jarvis/firewall.nft) + Unit aktiviert."
        return
    fi
    iptables-save  > /etc/jarvis/firewall-v4.rules
    ip6tables-save > /etc/jarvis/firewall-v6.rules 2>/dev/null || true
    cat > /etc/systemd/system/jarvis-firewall.service <<'UNIT'
[Unit]
Description=Jarvis Paketfilter (DROP als Vorgabe)
DefaultDependencies=no
Before=network-pre.target
Wants=network-pre.target
After=systemd-modules-load.service

[Service]
Type=oneshot
RemainAfterExit=yes
# `|| true`: ein Fehler beim Laden darf den Boot nicht anhalten – dann gilt der
# Kernel-Standard (ACCEPT), was schlechter als gewollt, aber besser als ein
# Server ist, der nicht hochkommt.
ExecStart=/bin/sh -c 'iptables-restore < /etc/jarvis/firewall-v4.rules || true'
ExecStart=/bin/sh -c 'ip6tables-restore < /etc/jarvis/firewall-v6.rules || true'

[Install]
WantedBy=sysinit.target
UNIT
    systemctl daemon-reload
    systemctl enable jarvis-firewall.service >/dev/null 2>&1
    echo "Regeln gespeichert (/etc/jarvis/firewall-v*.rules) + Unit aktiviert."
}

case "${1:---status}" in
    --status)
        status
        ;;
    --test)
        _ist_root
        SEK="${2:-300}"
        SICH=$(sichern)
        echo "Sicherung: $SICH"
        # Rueckfall-Timer VOR der Aenderung: bricht die Sitzung ab, stellt er den
        # alten Stand wieder her. Das ist der Unterschied zwischen einem Test und
        # einem Ausfall.
        if _hat_iptables; then
            systemd-run --on-active="$SEK" --unit=fw-rollback --description="Firewall-Rueckfall" \
                /sbin/iptables-restore "$SICH" >/dev/null 2>&1
        else
            # nft: die eigene Tabelle wieder entfernen = Zustand von vorher.
            systemd-run --on-active="$SEK" --unit=fw-rollback --description="Firewall-Rueckfall" \
                /usr/sbin/nft delete table inet jarvis_fw >/dev/null 2>&1
        fi
        [[ $? -eq 0 ]] \
            && echo "Rueckfall-Timer aktiv: in ${SEK}s zurueck (Abbruch: systemctl stop fw-rollback.timer)" \
            || echo "WARNUNG: Rueckfall-Timer konnte nicht gesetzt werden!"
        if _hat_iptables; then regeln_setzen; else regeln_setzen_nft; fi
        echo
        status
        echo
        echo "Wenn alles laeuft:  systemctl stop fw-rollback.timer && bash $0 --anwenden"
        ;;
    --anwenden)
        _ist_root
        sichern >/dev/null
        systemctl stop fw-rollback.timer 2>/dev/null || true
        if _hat_iptables; then regeln_setzen; else regeln_setzen_nft; fi
        persistieren
        echo
        status
        ;;
    *)
        echo "Aufruf: $0 [--status|--test [sekunden]|--anwenden]"
        exit 1
        ;;
esac
