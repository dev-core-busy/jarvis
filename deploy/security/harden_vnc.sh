#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# x11vnc nur noch auf localhost binden (-localhost)
#
# DER BEFUND (gemessen 2026-08-11): Auf ECHT nahm Port 5900 Verbindungen aus dem
# Netz an und meldete im RFB-Handshake als EINZIGEN Security-Type `1` = None.
# Kein Passwort. Wer den Host im Netz erreicht, hat Maus und Tastatur auf dem
# Desktop – und damit den Browser und die Dateien des `jarvis`-Benutzers. Der
# Umweg über 5900 überspringt genau die Anmeldung, die noVNC (6080) davorlegt.
#
# URSACHE waren zwei fehlende Argumente, an 15 Aufrufstellen:
#   * `-nopw`        – x11vnc verlangt kein Passwort
#   * kein `-localhost` – es lauscht auf allen Adressen
# `-nopw` bleibt (websockify müsste sonst ein Passwort kennen), ist aber nur
# vertretbar, WEIL `-localhost` den Zugang auf den Host selbst beschränkt:
# websockify verbindet sich lokal, der Weg von außen führt über 6080 und damit
# über die Portal-Anmeldung.
#
# IDEMPOTENT: ergänzt `-localhost` nur, wo es fehlt. Mehrfach ausführbar.
#
#   bash deploy/security/harden_vnc.sh [--pruefen]
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

NUR_PRUEFEN=0
[[ "${1:-}" == "--pruefen" ]] && NUR_PRUEFEN=1

BASIS="${JARVIS_ROOT:-/opt/jarvis}"
DATEIEN=(
    "$BASIS/start_jarvis_root.sh"
    "$BASIS/start_jarvis.sh"
    "$BASIS/run.sh"
    "/etc/systemd/system/x11vnc.service"
)

gefunden=0
geaendert=0
offen=0

for f in "${DATEIEN[@]}"; do
    [[ -f "$f" ]] || continue
    # Zeilen mit einem x11vnc-Aufruf (nicht Kommentare, nicht pgrep/pkill)
    mapfile -t treffer < <(grep -n 'x11vnc' "$f" \
        | grep -E 'x11vnc (-|"\$)' \
        | grep -v -E '^\s*[0-9]+:\s*#' \
        | grep -v -E 'pgrep|pkill')
    for zeile in "${treffer[@]}"; do
        nr="${zeile%%:*}"
        inhalt="${zeile#*:}"
        gefunden=$((gefunden + 1))
        if [[ "$inhalt" == *"-localhost"* ]]; then
            continue
        fi
        offen=$((offen + 1))
        if [[ $NUR_PRUEFEN -eq 1 ]]; then
            echo "  OFFEN  $f:$nr"
            continue
        fi
        # `-localhost` direkt hinter `x11vnc` einfuegen: die Option gilt
        # unabhaengig von der Reihenfolge, und so wird kein Argument zerlegt,
        # das ueber Zeilenumbrueche fortgesetzt wird (docker/entrypoint.sh).
        sed -i "${nr}s/x11vnc /x11vnc -localhost /" "$f"
        geaendert=$((geaendert + 1))
        echo "  ergaenzt  $f:$nr"
    done
done

echo
echo "x11vnc-Aufrufe gefunden: $gefunden"
if [[ $NUR_PRUEFEN -eq 1 ]]; then
    echo "ohne -localhost:         $offen"
    [[ $offen -eq 0 ]] && echo "OK – alle Aufrufe binden nur localhost."
    exit $(( offen > 0 ))
fi
echo "ergaenzt:                $geaendert"

if [[ $geaendert -gt 0 ]] && [[ -f /etc/systemd/system/x11vnc.service ]]; then
    systemctl daemon-reload
    echo "systemd neu geladen."
    if systemctl is-active --quiet x11vnc; then
        systemctl restart x11vnc
        echo "x11vnc neu gestartet (lauscht jetzt nur auf 127.0.0.1)."
    else
        echo "HINWEIS: x11vnc laeuft derzeit nicht – die Aenderung wirkt beim naechsten Start."
    fi
fi

# Nachweis: worauf lauscht 5900 jetzt?
echo
echo "Sockets auf 5900:"
ss -tlnp 2>/dev/null | awk 'NR==1 || /:5900/' || true
