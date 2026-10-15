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
# FALLSTRICK, der die erste Fassung UNWIRKSAM gemacht hat (gemessen auf ECHT am
# 2026-08-11): Diese Liste enthielt nur Shell-Skripte und die Unit. x11vnc wird
# aber AUCH aus Python gestartet – `backend/desktop_control.py` (Broker-Op
# `vnc_restart`, Session-Wechsel, Bildschirm entsperren). Auf ECHT lief die
# Härtung um 13:49; um 16:17 hat ein VNC-Neustart über genau diesen Pfad den
# Prozess ohne `-localhost` neu gestartet und Port 5900 wieder auf 0.0.0.0
# geöffnet. Die Härtung hielt also bis zum nächsten Klick auf „VNC neu starten".
# Merkregel: Wer einen Prozess härtet, muss ALLE Startstellen erfassen – auch
# die, die nicht in einem Startskript stehen.
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
# Startstellen in Python (Argumentliste statt Kommandozeile, eigenes Muster)
PY_DATEIEN=(
    "$BASIS/backend/desktop_control.py"
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

# ── Python-Startstellen ──────────────────────────────────────────────────────
# Muster ist die Argumentliste `["x11vnc", …]`. Das trifft bewusst NICHT
# `["pkill", "-9", "x11vnc"]` – dort steht der Name nicht an erster Stelle.
# Der Aufruf laeuft ueber mehrere Zeilen, geprueft wird deshalb bis zur
# schliessenden Klammer (hoechstens 5 Zeilen), gepatcht nur die erste.
for f in "${PY_DATEIEN[@]}"; do
    [[ -f "$f" ]] || continue
    for nr in $(grep -n '\["x11vnc"' "$f" | cut -d: -f1); do
        gefunden=$((gefunden + 1))
        block=""
        for ((i = 0; i < 5; i++)); do
            zl=$(sed -n "$((nr + i))p" "$f")
            block+="$zl"
            [[ "$zl" == *"]"* ]] && break
        done
        if [[ "$block" == *"-localhost"* ]]; then
            continue
        fi
        offen=$((offen + 1))
        if [[ $NUR_PRUEFEN -eq 1 ]]; then
            echo "  OFFEN  $f:$nr"
            continue
        fi
        sed -i "${nr}s/\[\"x11vnc\", /[\"x11vnc\", \"-localhost\", /" "$f"
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
