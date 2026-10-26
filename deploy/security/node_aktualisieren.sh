#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Node.js auf eine unterstuetzte LTS-Linie heben (BSI M6) – als root.
#
# DER BEFUND (BSI-Abgleich ECHT, 2026-09-29): Node v20.20.2, Lebensende
# 30.04.2026 – keine Sicherheitsupdates mehr. Debian 13 liefert selbst nur
# nodejs 20 (DEV: 20.19.2+dfsg aus trixie). Node laeuft hier fuer die
# WhatsApp-Bridge (services/whatsapp-bridge) und fuer MCP-Server per npx.
#
# WAS DAS SKRIPT TUT:
#   1. NodeSource-Paketquelle fuer node_$ZIEL einrichten – OHNE deren
#      setup-Skript (das liefe als root aus dem Netz). Den Signaturschluessel
#      prueft es gegen den unten festgeschriebenen Fingerabdruck; weicht er ab,
#      Abbruch. Apt prueft danach jede Paketliste gegen genau diesen Schluessel.
#   2. Pin-Priority 600 fuer nodejs aus deb.nodesource.com – sonst gewinnt die
#      gleichnamige Debian-Fassung, sobald sie eine hoehere Revision hat.
#   3. apt install nodejs (ersetzt Debians nodejs/libnode/npm; NodeSource
#      bringt npm mit).
#   4. node_modules der Bridge neu bauen (native Teile haengen an der
#      Node-ABI), als Dienstbenutzer; eine laufende Bridge neu starten.
#
# INNERHALB DER LINIE (seit 26.10.2026): ``--automatisch`` zieht auf der
# Ziel-Linie auch den neuesten NodeSource-Stand nach (apt-get --only-upgrade,
# gleiche Schranke wie beim Linienwechsel). Anlass: CVE-2026-111497 (Brotli,
# behoben in 24.22.1) – ECHT stand auf 24.21.0, und das Skript meldete
# "Ziel-Linie erreicht", weil es nur die Hauptversion verglich. Node
# kennzeichnet Sicherheitsstaende in apt nicht; jeder neuere Stand einer
# LTS-Linie ist der Traeger ihrer Fixes. unattended-upgrades greift hier nicht
# (52jarvis-unattended laesst nur Debian-Security zu).
# Der Broker-Start legt dafuer einen taeglichen Timer an (start_jarvis_root.sh).
#
# NACHWEIS NICHT UEBER process.versions.brotli: 24.22.1 meldet weiter 1.2.0,
# obwohl der Fix drin ist (DEV, 26.10.2026). Massgeblich ist die Node-Version.
#
# AUTOMATISCH (seit 06.10.2026, Entscheidung des Betreibers): der Broker-Start
# ruft ``--automatisch`` als eigene systemd-Unit auf, sobald die installierte
# Linie unter ZIEL liegt. Umgestellt wird dann nur, wenn der Trockenlauf
# AUSSER Node selbst (nodejs, npm, libnode*, nodejs-doc) nichts entfernen
# wuerde – auf DEV (Debians Node) waeren es webpack, eslint, terser u. a.
# gewesen; dort bleibt es bei einer Warnung im Journal. Notschalter:
# NODE_AUTO=aus in /etc/jarvis/broker.conf.
#
#   bash deploy/security/node_aktualisieren.sh            # auf ZIEL heben
#   bash deploy/security/node_aktualisieren.sh --pruefen  # nur Stand melden
#   bash deploy/security/node_aktualisieren.sh --ziel-erreicht   # Exit 0, wenn >= ZIEL
#   bash deploy/security/node_aktualisieren.sh --automatisch     # Linie heben bzw. nachziehen,
#                                                                # nur ohne Fremd-Entfernungen
#   bash deploy/security/node_aktualisieren.sh --simulieren
#       Trockenlauf: Paketquelle nur in einem Wegwerf-Verzeichnis, apt-get -s –
#       zeigt, was installiert und ENTFERNT wuerde (Debians npm und die
#       node-*-Pakete; novnc haengt an "nodejs" ohne Version und bleibt).
#       Am System wird nichts geaendert.
# ─────────────────────────────────────────────────────────────────────────────
set -u

# Node 24 ist LTS bis 30.04.2028. Vor dem naechsten Wechsel Lebensende pruefen:
# https://nodejs.org/en/about/previous-releases
ZIEL=24
# Unter dieser Hauptversion meldet der Broker-Start eine Warnung (22 = noch im
# Wartungszweig bis 30.04.2027, 20 und aelter = ohne Updates).
MINDEST=22

# Fingerabdruck des NodeSource-Repo-Schluessels (nodesource-repo.gpg.key,
# abgerufen 2026-10-06 ueber https://deb.nodesource.com/gpgkey/). Aendert
# NodeSource den Schluessel, bricht das Skript ab – dann den neuen auf einem
# zweiten Weg bestaetigen und hier eintragen, nicht blind uebernehmen.
NODESOURCE_FPR="6F71F525282841EEDAF851B42F59B5F99B1BE0B4"
SCHLUESSEL_URL="https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key"
KEYRING=/usr/share/keyrings/nodesource.gpg
QUELLE=/etc/apt/sources.list.d/nodesource.sources
PIN=/etc/apt/preferences.d/nodejs

JARVIS_DIR="${JARVIS_DIR:-/opt/jarvis}"
BRIDGE_DIR="$JARVIS_DIR/services/whatsapp-bridge"

_major() { node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0; }

if [ "${1:-}" = "--pruefen" ]; then
    m="$(_major)"
    if [ "$m" -ge "$MINDEST" ] 2>/dev/null; then
        echo "Node $(node --version) – unterstuetzt (Mindest-Linie $MINDEST)."
        exit 0
    fi
    echo "Node ${m} – ohne Sicherheitsupdates. Anheben: bash $0"
    exit 1
fi

if [ "${1:-}" = "--ziel-erreicht" ]; then
    [ "$(_major)" -ge "$ZIEL" ] 2>/dev/null
    exit $?
fi

# Waechter-Modus (tests/test_bsi_m6_m7.py): kein root, Trockenlauf aus Datei,
# am Ende nur melden statt umstellen
TEST="${JARVIS_NODE_TEST:-}"
[ -n "$TEST" ] || [ "$(id -u)" = "0" ] || { echo "Bitte als root ausfuehren." >&2; exit 1; }

# Entfernt der Trockenlauf etwas, das NICHT zu Node selbst gehoert? (Liste auf stdout)
_fremde_entfernungen() {
    sed -n 's/^  Remv \([^ ]*\) .*/\1/p' "$1" | grep -vE '^(nodejs|nodejs-doc|npm|libnode[0-9a-z-]*)$' || true
}

# Bridge-Module zur neuen ABI bauen – NIE als root (Code-Review 2026-10-07):
# "als Eigentuemer von BRIDGE_DIR" hiess root, wenn der Broker-Start vor dem
# chown (start_jarvis_root.sh, Schritt 6b) lief – dann baute root in einem
# Baum, den der Dienstbenutzer schreibt (Skripte aus package.json als root).
_bridge_bauen() {
    [ -f "$BRIDGE_DIR/package.json" ] || return 0
    local eigner
    eigner="$(stat -c %U "$BRIDGE_DIR")"
    if [ -d "$BRIDGE_DIR/node_modules" ]; then
        if [ "$eigner" = "root" ] || [ -z "$eigner" ]; then
            echo "WARNUNG: $BRIDGE_DIR gehoert root – npm rebuild NICHT als root; nach dem chown von Hand als Dienstbenutzer: cd $BRIDGE_DIR && npm rebuild" >&2
        else
            runuser -u "$eigner" -- sh -c "cd '$BRIDGE_DIR' && npm rebuild" \
                && echo "Bridge-Module neu gebaut (als $eigner)." \
                || echo "WARNUNG: npm rebuild in $BRIDGE_DIR gescheitert – Bridge vor dem Start pruefen." >&2
        fi
    fi
    if systemctl is-active --quiet whatsapp-bridge.service; then
        systemctl restart whatsapp-bridge.service && echo "whatsapp-bridge.service neu gestartet."
    fi
}

# Auf der Ziel-Linie den neuesten NodeSource-Stand nachziehen (Kopf: "INNERHALB
# DER LINIE"). Dieselbe Schranke wie beim Linienwechsel, nie ueber die Linie
# hinaus, nur aus der von diesem Skript eingerichteten Quelle. Waechter-Modus:
# Staende aus JARVIS_NODE_INST/JARVIS_NODE_KAND, Trockenlauf aus JARVIS_NODE_SIM_ECHT.
_linie_nachziehen() {
    local inst kand sim f
    if [ -n "$TEST" ]; then
        inst="${JARVIS_NODE_INST:-}"
        kand="${JARVIS_NODE_KAND:-}"
    else
        if [ ! -f "$QUELLE" ]; then
            echo "[Node] nicht aus NodeSource ($QUELLE fehlt) – Stand innerhalb der Linie nicht pruefbar."
            return 0
        fi
        apt-get update -o Dir::Etc::sourcelist="$QUELLE" -o Dir::Etc::sourceparts=- \
            -o APT::Get::List-Cleanup=0 -o DPkg::Lock::Timeout=300 >/dev/null 2>&1 \
            || { echo "[Node] WARNUNG: NodeSource-Paketliste nicht ladbar – Stand nicht geprueft." >&2; return 4; }
        inst="$(dpkg-query -W -f='${Version}' nodejs 2>/dev/null)"
        # LC_ALL=C: die Ausgabe von apt-cache ist lokalisiert
        kand="$(LC_ALL=C apt-cache policy nodejs | sed -n 's/^ *Candidate: *//p')"
    fi
    if [ -z "$inst" ] || [ -z "$kand" ] || [ "$kand" = "(none)" ]; then
        echo "[Node] WARNUNG: Stand nicht bestimmbar (installiert '$inst', Kandidat '$kand')." >&2
        return 4
    fi
    if ! dpkg --compare-versions "$kand" gt "$inst"; then
        echo "[Node] $inst ist der neueste Stand der Linie."
        return 0
    fi
    if [ "${kand%%.*}" != "$(_major)" ]; then
        echo "[Node] WARNUNG: Kandidat $kand liegt ausserhalb der Linie $(_major) – nicht automatisch." >&2
        return 4
    fi
    sim="$(mktemp)"
    if [ -n "$TEST" ]; then
        cat "${JARVIS_NODE_SIM_ECHT:-/dev/null}" > "$sim"
    elif ! LC_ALL=C apt-get -s install --only-upgrade nodejs > "$sim.roh" 2>&1; then
        echo "[Node] WARNUNG: Trockenlauf gescheitert – kein Nachziehen:" >&2
        tail -3 "$sim.roh" >&2; rm -f "$sim" "$sim.roh"; return 4
    else
        grep -E '^(Inst|Remv) ' "$sim.roh" | sed 's/^/  /' > "$sim"
        rm -f "$sim.roh"
    fi
    f="$(_fremde_entfernungen "$sim")"
    rm -f "$sim"
    if [ -n "$f" ]; then
        echo "[Node] ABBRUCH: Nachziehen $inst -> $kand wuerde $(echo "$f" | wc -l) weitere Pakete entfernen ($(echo "$f" | head -8 | tr '\n' ' ')…) – nicht automatisch." >&2
        return 4
    fi
    echo "[Node] Nachziehen innerhalb der Linie: $inst -> $kand"
    if [ -n "$TEST" ]; then
        echo "[Node] (Test) wuerde jetzt nachziehen"
    else
        DEBIAN_FRONTEND=noninteractive apt-get install -y --only-upgrade -o DPkg::Lock::Timeout=300 nodejs \
            || { echo "[Node] ABBRUCH: apt-get install --only-upgrade nodejs gescheitert." >&2; return 1; }
        hash -r
        echo "[Node] nachher: $(node --version 2>/dev/null || echo keins)"
    fi
    _bridge_bauen
}

if [ "${1:-}" = "--automatisch" ]; then
    KONF="${JARVIS_BROKER_CONF:-/etc/jarvis/broker.conf}"
    if [ -f "$KONF" ] && grep -qiE '^[[:space:]]*NODE_AUTO[[:space:]]*=[[:space:]]*"?aus' "$KONF"; then
        echo "[Node] NODE_AUTO=aus – keine automatische Umstellung."
        exit 0
    fi
    command -v node >/dev/null 2>&1 || { echo "[Node] nicht installiert – nichts zu tun."; exit 0; }
    if [ "$(_major)" -ge "$ZIEL" ] 2>/dev/null; then
        echo "[Node] $(node --version) – Ziel-Linie $ZIEL erreicht."
        _linie_nachziehen
        exit $?
    fi
    sim="$(mktemp)"
    if [ -n "$TEST" ]; then
        cat "${JARVIS_NODE_SIM:-/dev/null}" > "$sim"
    elif ! bash "$0" --simulieren > "$sim" 2>&1; then
        echo "[Node] WARNUNG: Trockenlauf gescheitert – keine Umstellung:" >&2
        tail -3 "$sim" >&2; rm -f "$sim"; exit 4
    fi
    fremd="$(_fremde_entfernungen "$sim")"
    rm -f "$sim"
    if [ -n "$fremd" ]; then
        anzahl="$(echo "$fremd" | wc -l)"
        echo "[Node] WARNUNG: Umstellung auf Node $ZIEL wuerde $anzahl weitere Pakete entfernen ($(echo "$fremd" | head -8 | tr '\n' ' ')…) – nicht automatisch. Liste: bash $0 --simulieren; umstellen von Hand: bash $0" >&2
        exit 4
    fi
    echo "[Node] Automatische Umstellung $(node --version) -> Linie $ZIEL"
    [ -n "$TEST" ] && echo "[Node] (Test) wuerde jetzt umstellen"
    # JARVIS_NODE_AUTO=1: die Installation prueft die Schranke UNMITTELBAR vor
    # apt-get install noch einmal gegen die echten Paketlisten (siehe unten).
    JARVIS_NODE_AUTO=1 exec bash "$0"
fi
# Schranke der Automatik, UNMITTELBAR vor apt-get install (Code-Review
# 2026-10-07): bis dahin galt die Pruefung "keine Fremd-Entfernungen" nur fuer
# den Trockenlauf mit frisch geladenen Listen in einem Wegwerf-Verzeichnis; die
# echte Installation lud nur die NodeSource-Liste neu und lief dann mit -y ohne
# Schranke. Weichen beide Staende ab, entfernte apt unbeaufsichtigt Pakete.
# $1 = Ausgabe von apt-get -s install nodejs gegen den ECHTEN Stand.
_schranke_auto() {
    [ "${JARVIS_NODE_AUTO:-}" = "1" ] || return 0
    local f
    f="$(_fremde_entfernungen "$1")"
    if [ -n "$f" ]; then
        echo "[Node] ABBRUCH: die Installation wuerde jetzt $(echo "$f" | wc -l) weitere Pakete entfernen ($(echo "$f" | head -8 | tr '\n' ' ')…) – nicht automatisch." >&2
        return 4
    fi
    return 0
}

if [ -n "$TEST" ]; then
    # Waechter-Modus der Installation: Schranke gegen den Trockenlauf aus
    # JARVIS_NODE_SIM_ECHT, danach nur der Bridge-Schritt (Attrappen im PATH).
    sim_echt="$(mktemp)"
    cat "${JARVIS_NODE_SIM_ECHT:-/dev/null}" > "$sim_echt"
    _schranke_auto "$sim_echt" || { rc=$?; rm -f "$sim_echt"; exit $rc; }
    rm -f "$sim_echt"
    echo "[Node] (Test) wuerde jetzt installieren"
    _bridge_bauen
    exit 0
fi

command -v apt-get >/dev/null || { echo "Nur fuer apt-Systeme (Debian/Ubuntu)." >&2; exit 1; }

vorher="$(node --version 2>/dev/null || echo keins)"
echo "Node vorher: $vorher"

# 1. Schluessel holen und pruefen – in ein Wegwerf-Verzeichnis
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
curl -fsSL --proto '=https' --tlsv1.2 "$SCHLUESSEL_URL" -o "$tmp/key.asc" \
    || { echo "ABBRUCH: Schluessel nicht abrufbar." >&2; exit 1; }
fpr="$(gpg --show-keys --with-colons "$tmp/key.asc" 2>/dev/null | awk -F: '$1=="fpr"{print $10; exit}')"
if [ "$fpr" != "$NODESOURCE_FPR" ]; then
    echo "ABBRUCH: Schluessel-Fingerabdruck $fpr statt $NODESOURCE_FPR." >&2
    exit 1
fi
gpg --dearmor < "$tmp/key.asc" > "$tmp/nodesource.gpg" \
    || { echo "ABBRUCH: Schluessel nicht lesbar." >&2; exit 1; }
arch="$(dpkg --print-architecture)"

# _quelle <keyring> – der Inhalt der Paketquelle
_quelle() {
    printf '%s\n' "Types: deb" "URIs: https://deb.nodesource.com/node_${ZIEL}.x" "Suites: nodistro" \
        "Components: main" "Architectures: $arch" "Signed-By: $1"
}
_pin() { printf '%s\n' "Package: nodejs" "Pin: origin deb.nodesource.com" "Pin-Priority: 600"; }

if [ "${1:-}" = "--simulieren" ]; then
    # Alles in $tmp: Quellen = System + NodeSource, eigene Listen/Cache/Vorrang
    mkdir -p "$tmp/teile" "$tmp/vorrang" "$tmp/listen/partial" "$tmp/cache/archives/partial"
    cp /etc/apt/sources.list.d/* "$tmp/teile/" 2>/dev/null
    rm -f "$tmp/teile/nodesource.list" "$tmp/teile/nodesource.sources"
    _quelle "$tmp/nodesource.gpg" > "$tmp/teile/nodesource.sources"
    cp /etc/apt/preferences.d/* "$tmp/vorrang/" 2>/dev/null
    _pin > "$tmp/vorrang/nodejs"
    APT=(-o Dir::Etc::SourceParts="$tmp/teile" -o Dir::Etc::PreferencesParts="$tmp/vorrang"
         -o Dir::State::Lists="$tmp/listen" -o Dir::Cache="$tmp/cache")
    apt-get "${APT[@]}" update >/dev/null 2>&1 \
        || { echo "ABBRUCH: Paketlisten im Trockenlauf nicht ladbar." >&2; exit 1; }
    echo "Kandidat: $(apt-cache "${APT[@]}" policy nodejs | sed -n 's/^ *Installationskandidat: *//p;s/^ *Candidate: *//p')"
    apt-get "${APT[@]}" -s install nodejs | grep -E '^(Inst|Remv) ' | sed 's/^/  /'
    echo "Trockenlauf – am System nichts geaendert."
    exit 0
fi

install -m 0644 -o root -g root "$tmp/nodesource.gpg" "$KEYRING" \
    || { echo "ABBRUCH: Schluessel nicht installierbar." >&2; exit 1; }

# 2. Paketquelle + Vorrang
_quelle "$KEYRING" > "$QUELLE"
rm -f /etc/apt/sources.list.d/nodesource.list   # Altform des setup-Skripts
_pin > "$PIN"

# 3. Installieren
apt-get update -o Dir::Etc::sourcelist="$QUELLE" -o Dir::Etc::sourceparts=- \
    -o APT::Get::List-Cleanup=0 >/dev/null \
    || { echo "ABBRUCH: Paketliste von NodeSource nicht ladbar." >&2; exit 1; }
apt-get -s install nodejs | grep -E '^(Inst|Remv) ' | sed 's/^/  /' > "$tmp/sim_echt"
_schranke_auto "$tmp/sim_echt" || exit $?
DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs \
    || { echo "ABBRUCH: apt-get install nodejs gescheitert." >&2; exit 1; }
hash -r
nachher="$(node --version 2>/dev/null || echo keins)"
echo "Node nachher: $nachher"
if [ "$(_major)" -lt "$ZIEL" ] 2>/dev/null; then
    echo "ABBRUCH: erwartet wurde Node $ZIEL – apt-cache policy nodejs pruefen." >&2
    exit 1
fi

# 4. Bridge: Module zur neuen ABI bauen (als Eigentuemer, nie als root)
_bridge_bauen
echo "Fertig: $vorher -> $nachher"
