#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Apache Tika bereitstellen – Voraussetzung für den OneNote-Import (*.one)
#
# WARUM: `.one` ist das binäre MS-ONESTORE-Format. Apache Tika hat dafür einen
# vollständigen Parser; in Python gibt es keinen brauchbaren (Begründung samt
# Messwerten im Kopf von backend/tools/onenote.py). Ohne Java + tika-app.jar
# liegen `.one`-Dateien im Wissensordner unlesbar da – der Indexer meldet das
# im Klartext, aber beheben kann es nur ein Administrator.
#
# WARUM DIE JAR NICHT IM REPO LIEGT: sie ist 65 MB, und dieses Repo ist
# öffentlich. Gleiche Behandlung wie die PowerPoint-Hausvorlage: einmal
# ablegen, Pfad konfigurierbar, und bei Abwesenheit ein Klartext-Hinweis
# statt eines rohen Fehlers.
#
# WARUM EIN SKRIPT UND KEINE ANLEITUNG: dieselbe Begründung wie bei
# deploy/sandbox_python.sh – Handarbeit ist der Grund, aus dem DEV und ECHT
# auseinanderlaufen. „Bei dir geht OneNote, bei mir nicht" ist genau der
# Zustand, den das Skript verhindert.
#
# GEPRÜFT WIRD DER INHALT, NICHT DER NAME: die geladene Datei muss die
# veröffentlichte SHA-1 von Maven Central UND die hier gepinnte SHA-256
# erfüllen. Die SHA-1 belegt „das ist, was Maven ausliefert", die gepinnte
# SHA-256 belegt „und es ist die Fassung, gegen die gemessen wurde".
# Maven veröffentlicht für dieses Artefakt nur .sha1 (nachgesehen: .sha256
# und .sha512 gibt es dort nicht) – deshalb beide.
#
# IDEMPOTENT: lädt nur, was fehlt. Mehrfach ausführbar.
#
#   sudo bash deploy/tika_setup.sh [--pruefen]
#
#   --pruefen   zeigt nur den Zustand, lädt und installiert nichts
#               (Exit 1 = etwas fehlt, Exit 0 = vollständig)
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

NUR_PRUEFEN=0
[[ "${1:-}" == "--pruefen" ]] && NUR_PRUEFEN=1

TIKA_VERSION="3.3.1"
TIKA_SHA1="2161b5b56682f543035d328eeeb230717e07f446"
TIKA_SHA256="0e8ee9795ac4244feab466f4a5a9c3b94675af392848243842cb6e1e69d27103"
TIKA_URL="https://repo1.maven.org/maven2/org/apache/tika/tika-app/${TIKA_VERSION}/tika-app-${TIKA_VERSION}.jar"

PROJEKT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR="$PROJEKT/vendor"
ZIEL="$VENDOR/tika-app.jar"
DIENST_USER="${JARVIS_SERVICE_USER:-jarvis}"

FEHLT=0

# ─── 1. Java ────────────────────────────────────────────────────────────────
JAVA="$(command -v java || true)"
if [[ -n "$JAVA" ]]; then
    echo "✓ Java: $JAVA  ($("$JAVA" -version 2>&1 | head -1))"
else
    echo "✗ Java fehlt (Paket: default-jre-headless, ~199 MB installiert)"
    FEHLT=1
    if [[ $NUR_PRUEFEN -eq 0 ]]; then
        if [[ "$(id -u)" != "0" ]]; then
            echo "  → Für die Installation als root ausführen." >&2
            exit 2
        fi
        echo "  → apt-get install default-jre-headless"
        # apt-get update unmittelbar davor: ein veralteter Index lässt die
        # Installation mit 404 scheitern (dieselbe Lehre wie in manager.py).
        apt-get update -qq
        if DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends default-jre-headless; then
            JAVA="$(command -v java || true)"
            [[ -n "$JAVA" ]] && { echo "  ✓ installiert: $("$JAVA" -version 2>&1 | head -1)"; FEHLT=0; }
        else
            echo "  ✗ apt-Installation fehlgeschlagen." >&2
        fi
    fi
fi

# ─── 2. tika-app.jar ────────────────────────────────────────────────────────
pruefe_jar() {
    local f="$1"
    [[ -f "$f" ]] || return 1
    local ist_sha1 ist_sha256
    ist_sha1="$(sha1sum "$f" | cut -d' ' -f1)"
    ist_sha256="$(sha256sum "$f" | cut -d' ' -f1)"
    [[ "$ist_sha1" == "$TIKA_SHA1" && "$ist_sha256" == "$TIKA_SHA256" ]]
}

if pruefe_jar "$ZIEL"; then
    echo "✓ Tika: $ZIEL  (tika-app $TIKA_VERSION, Prüfsummen stimmen)"
elif [[ -f "$ZIEL" ]]; then
    echo "✗ Tika: $ZIEL vorhanden, aber PRÜFSUMME WEICHT AB"
    echo "  erwartet sha256: $TIKA_SHA256"
    echo "  gefunden  sha256: $(sha256sum "$ZIEL" | cut -d' ' -f1)"
    echo "  → Datei prüfen und ggf. löschen, dann dieses Skript erneut ausführen."
    # Bewusst NICHT automatisch überschreiben: eine fremde Datei an diesem Ort
    # ist eine Frage, keine Aufgabe. Vielleicht hat der Betreiber bewusst eine
    # andere Tika-Version abgelegt.
    exit 1
else
    echo "✗ Tika fehlt: $ZIEL"
    FEHLT=1
    if [[ $NUR_PRUEFEN -eq 0 ]]; then
        mkdir -p "$VENDOR"
        TMP="$VENDOR/.tika-app.jar.download"
        echo "  → lade tika-app $TIKA_VERSION (65 MB) von Maven Central"
        if ! curl -fL --retry 2 --connect-timeout 15 -o "$TMP" "$TIKA_URL"; then
            echo "  ✗ Download fehlgeschlagen (kein Internetzugang?)." >&2
            echo "    Alternative: Datei von Hand nach $ZIEL legen, oder" >&2
            echo "    JARVIS_TIKA_JAR auf einen vorhandenen Pfad setzen." >&2
            rm -f "$TMP"
            exit 2
        fi
        if ! pruefe_jar "$TMP"; then
            echo "  ✗ Prüfsumme der geladenen Datei stimmt NICHT – verworfen." >&2
            echo "    sha1  : $(sha1sum "$TMP" | cut -d' ' -f1)" >&2
            echo "    sha256: $(sha256sum "$TMP" | cut -d' ' -f1)" >&2
            rm -f "$TMP"
            exit 2
        fi
        # Erst nach der Prüfung an den endgültigen Ort – eine halb geladene
        # Datei an $ZIEL wäre für den Indexer eine kaputte Tika-Installation.
        mv -f "$TMP" "$ZIEL"
        chmod 0644 "$ZIEL"
        # Eigentümer: der DIENSTBENUTZER, nicht root. Eine als root angelegte
        # Datei unter /opt/jarvis legt den nächsten git pull lahm (Register).
        if [[ "$(id -u)" == "0" ]] && id "$DIENST_USER" &>/dev/null; then
            chown "$DIENST_USER:$DIENST_USER" "$ZIEL" "$VENDOR" 2>/dev/null || true
        fi
        echo "  ✓ abgelegt: $ZIEL"
        FEHLT=0
    fi
fi

echo

# ─── 3. Funktionsprobe ──────────────────────────────────────────────────────
# Ohne sie sagt das Skript nur, dass zwei Dateien da sind – nicht, dass sie
# zusammen arbeiten. Geprüft wird mit der ECHTEN Aufrufform des Extraktors.
if [[ -n "$JAVA" ]] && pruefe_jar "$ZIEL"; then
    # FALLSTRICK (Register): `AUSGABE="$(cmd | head -1)"; RC=$?` prueft den
    # Exit-Code von HEAD, nicht von cmd. Erst auffangen, dann filtern.
    AUSGABE="$("$JAVA" -Xmx512m -jar "$ZIEL" --version 2>&1)"
    RC=$?
    AUSGABE="$(printf '%s\n' "$AUSGABE" | head -1)"
    if [[ $RC -eq 0 && -n "$AUSGABE" ]]; then
        echo "✓ Funktionsprobe: $AUSGABE"
        echo "✓ OneNote-Import einsatzbereit (*.one wird beim nächsten Reindex erfasst)."
        exit 0
    fi
    echo "✗ Funktionsprobe fehlgeschlagen: $AUSGABE" >&2
    exit 2
fi

if [[ $NUR_PRUEFEN -eq 1 && $FEHLT -eq 1 ]]; then
    echo "Es fehlt etwas – zum Einrichten: sudo bash $0"
    exit 1
fi
exit 1
