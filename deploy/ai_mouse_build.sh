#!/usr/bin/env bash
# Baut die AI-Mouse-Anwendung und legt sie unter vendor/ai-mouse/ ab.
#
# ⚠ DAS GEHT AUF LINUX. Der erste Entwurf dieses Bereichs behauptete das
# Gegenteil ("eine Windows-EXE kann der Server nicht bauen") – GEMESSEN am
# 2026-09-09 auf DEV-Hardware: `dotnet publish -r win-x64 --self-contained`
# erzeugt in 25 Sekunden eine 65,9-MB-Datei, die `file` als
# "PE32+ executable for MS Windows (GUI), x86-64" ausweist. WinForms braucht
# dafuer nur `EnableWindowsTargeting=true`; laufen muss sie nicht hier.
#
# Warum trotzdem ein Skript und kein Bau bei jedem Abruf: 25 Sekunden je
# Download waeren eine Zumutung, und das NuGet-Verzeichnis muesste dem
# Dienstbenutzer gehoeren. Also einmal bauen, Ergebnis nach vendor/ – wie bei
# vendor/tika-app.jar.
#
#   bash deploy/ai_mouse_build.sh [--pruefen] [--runtime win-x64|win-arm64]
#
# --pruefen  meldet nur den Zustand und baut nichts (Exit 0 = liegt bereit).

set -euo pipefail

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJEKT="$WURZEL/ai-mouse/src/AiMouse/AiMouse.csproj"
ZIEL="$WURZEL/vendor/ai-mouse"
RUNTIME="win-x64"
NUR_PRUEFEN=0

while [ $# -gt 0 ]; do
    case "$1" in
        --pruefen) NUR_PRUEFEN=1 ;;
        --runtime) shift; RUNTIME="${1:-win-x64}" ;;
        *) echo "Unbekanntes Argument: $1" >&2; exit 2 ;;
    esac
    shift
done

case "$RUNTIME" in
    win-x64|win-arm64) ;;
    *) echo "FEHLER: --runtime muss win-x64 oder win-arm64 sein." >&2; exit 2 ;;
esac

meldung() { printf '[AI-Mouse] %s\n' "$*"; }

# ── Zustand ─────────────────────────────────────────────────────────────────
# Geprueft wird der INHALT, nicht nur die Existenz: eine 0-Byte-Datei oder ein
# abgebrochener Download saehe sonst wie ein fertiger Stand aus. Die magischen
# Bytes "MZ" hat jede PE-Datei.
liegt_bereit() {
    [ -s "$ZIEL/AiMouse.exe" ] && [ "$(head -c2 "$ZIEL/AiMouse.exe" 2>/dev/null)" = "MZ" ]
}

if [ "$NUR_PRUEFEN" = "1" ]; then
    if liegt_bereit; then
        meldung "bereit: $ZIEL/AiMouse.exe ($(du -h "$ZIEL/AiMouse.exe" | cut -f1))"
        exit 0
    fi
    meldung "NICHT vorhanden: $ZIEL/AiMouse.exe"
    exit 1
fi

# ── SDK finden oder holen ───────────────────────────────────────────────────
# ⚠ AUF DEBIAN 13 GIBT ES KEIN apt-PAKET `dotnet-sdk-8.0` (gemessen auf DEV am
# 2026-09-09: "kann nicht gefunden werden" in trixie main). Microsoft liefert
# das SDK ueber ein eigenes Repo oder ueber `dotnet-install.sh` – und der
# zweite Weg braucht KEINE Root-Rechte: er legt das SDK einfach in ein
# Verzeichnis. Genau das tun wir, unter vendor/, das ohnehin dem Dienstbenutzer
# gehoert. Kein apt, kein fremdes Repo, kein Broker.
DOTNET_EIGEN="$WURZEL/vendor/dotnet"
if [ -x "$DOTNET_EIGEN/dotnet" ]; then
    export PATH="$DOTNET_EIGEN:$PATH"
    export DOTNET_ROOT="$DOTNET_EIGEN"
fi

if ! command -v dotnet >/dev/null 2>&1 && [ "${JARVIS_AIMOUSE_SDK_AUTO:-1}" != "0" ]; then
    meldung "kein .NET-SDK gefunden – hole es nach $DOTNET_EIGEN (~200 MB, einmalig)…"
    HOLER="$(mktemp)"
    # Offizieller Weg von Microsoft. Ueber HTTPS; scheitert der Download, endet
    # das Skript unten mit dem ueblichen Klartext-Fehler.
    if curl -fsSL --max-time 120 https://dot.net/v1/dotnet-install.sh -o "$HOLER" 2>/dev/null; then
        mkdir -p "$DOTNET_EIGEN"
        if bash "$HOLER" --channel 8.0 --install-dir "$DOTNET_EIGEN" --no-path >/dev/null 2>&1; then
            export PATH="$DOTNET_EIGEN:$PATH"
            export DOTNET_ROOT="$DOTNET_EIGEN"
            meldung "SDK bereit: $("$DOTNET_EIGEN/dotnet" --version 2>/dev/null || echo '?')"
        else
            meldung "WARNUNG: dotnet-install.sh ist fehlgeschlagen."
        fi
    else
        meldung "WARNUNG: dotnet-install.sh nicht erreichbar (kein Netzweg zu dot.net?)."
    fi
    rm -f "$HOLER"
fi

if ! command -v dotnet >/dev/null 2>&1; then
    # Fail-closed MIT WEG: eine Meldung "dotnet fehlt" allein sagt nicht, dass
    # es das SDK sein muss (die Runtime genuegt nicht) und auch nicht, dass es
    # eine Alternative gibt.
    cat >&2 <<'ENDE'
[AI-Mouse] FEHLER: Es ist kein .NET SDK installiert.

Der automatische Weg (dotnet-install.sh nach vendor/dotnet) hat nicht
funktioniert - meist fehlt der Netzweg zu dot.net.

Abhilfe, eine von beiden:
  a) SDK von Hand bereitstellen, z. B.
       curl -fsSL https://dot.net/v1/dotnet-install.sh | bash -s -- --channel 8.0
     ODER Microsofts apt-Repo einbinden (Debian 13 hat kein eigenes Paket).
  b) Die Datei auf einem anderen Rechner bauen (ai-mouse/build.ps1 unter
     Windows oder dieses Skript auf einem Rechner mit SDK) und die
     entstandene AiMouse.exe nach vendor/ai-mouse/ kopieren.

Ohne die Datei bleibt der Download-Knopf unter /ai-mouse aus; alles andere
(Auswertung von Bildausschnitten) funktioniert unabhaengig davon.
ENDE
    exit 1
fi

if [ ! -f "$PROJEKT" ]; then
    echo "[AI-Mouse] FEHLER: Projekt nicht gefunden: $PROJEKT" >&2
    exit 1
fi

# ── Hauswerte einsetzen ─────────────────────────────────────────────────────
# ⚠ HIER UND NICHT NUR IM DIENST. Bis zum 2026-09-09 setzte allein der
# Python-Weg die Marke; dieses Skript rufen aber auch der Bootstrap (Schritt 6g)
# und ein Administrator von Hand – die so gebaute Anwendung trug dann weder
# Marke noch Farbe des Hauses. Gemeldet als "das branding muss in die exe".
#
# Es ist idempotent: stehen die Werte schon richtig in Vorgaben.cs, passiert
# nichts. Schlaegt es fehl, wird trotzdem gebaut (fail-open) – eine Anwendung
# mit Vorgabemarke ist besser als keine.
PY="$WURZEL/venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3 || true)"
if [ -n "$PY" ]; then
    if ! "$PY" -c "
import sys
sys.path.insert(0, '$WURZEL')
from backend import ai_mouse
ai_mouse._hauswerte_schreiben()
" 2>/dev/null; then
        meldung "WARNUNG: Hauswerte konnten nicht gesetzt werden - baue mit den vorhandenen."
    fi
fi

meldung "baue $RUNTIME (dauert etwa eine halbe Minute)…"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# `EnableWindowsTargeting` ist auf Nicht-Windows Pflicht – ohne das bricht der
# Bau mit einem Hinweis auf das fehlende Windows-Desktop-Paket ab.
if ! dotnet publish "$PROJEKT" \
        --configuration Release \
        --runtime "$RUNTIME" \
        --self-contained true \
        -p:PublishSingleFile=true \
        -p:EnableWindowsTargeting=true \
        --output "$TMP" \
        --nologo >"$TMP/bau.log" 2>&1; then
    echo "[AI-Mouse] FEHLER: der Bau ist fehlgeschlagen:" >&2
    tail -20 "$TMP/bau.log" >&2
    exit 1
fi

if [ ! -s "$TMP/AiMouse.exe" ]; then
    echo "[AI-Mouse] FEHLER: der Bau meldete Erfolg, aber es gibt keine EXE." >&2
    exit 1
fi

# ⚠ MASSGEBLICH IST DER ZUSTAND AUF PLATTE, NICHT DER RUECKGABEWERT – dieselbe
# Regel wie bei tika_setup: ein "Erfolg", der nichts hergestellt hat, ist eine
# Zusage, die der naechste Abruf kassiert.
if [ "$(head -c2 "$TMP/AiMouse.exe")" != "MZ" ]; then
    echo "[AI-Mouse] FEHLER: die erzeugte Datei ist keine Windows-Anwendung." >&2
    exit 1
fi

mkdir -p "$ZIEL"
# Erst daneben legen, dann umbenennen: ein abgebrochenes Kopieren darf keine
# halbe EXE hinterlassen, die "liegt_bereit" fuer fertig haelt.
cp "$TMP/AiMouse.exe" "$ZIEL/.AiMouse.exe.neu"
mv "$ZIEL/.AiMouse.exe.neu" "$ZIEL/AiMouse.exe"

# Dem Dienstbenutzer uebereignen, falls als root gelaufen – sonst kann das
# Backend die Datei spaeter nicht ersetzen (Register: als root angelegte
# Dateien legen den naechsten Lauf lahm).
if [ "$(id -u)" = "0" ] && id jarvis >/dev/null 2>&1; then
    chown jarvis:jarvis "$ZIEL/AiMouse.exe"
fi

meldung "fertig: $ZIEL/AiMouse.exe ($(du -h "$ZIEL/AiMouse.exe" | cut -f1))"
