#!/bin/bash
# Entwicklungs-Verzeichnisse aus einem PRODUKTIONS-Checkout heraushalten.
#
# WARUM: Der Auto-Update zieht das komplette Repository. Damit landen Testdateien,
# jsdom-Pruefstaende, die Android-Quellen und der Go-Windows-Client auf jedem
# Produktivserver – Code, der dort nie ausgefuehrt wird. Am 2026-07-31 hat genau
# das den Update auf ECHT zerlegt: ein root-eigenes `tests/` blockierte den Pull,
# und zwar wegen Dateien, die dort ueberhaupt nicht hingehoeren.
#
# NICHT AUF DEV AUSFUEHREN. Dort laufen die Tests – ohne `tests/` ist der Server
# als Entwicklungsumgebung wertlos. Das Skript fragt deshalb nach, wenn es einen
# Hinweis auf eine Entwicklungsmaschine findet.
#
#   bash deploy/sparse_checkout.sh status     Was ist gerade eingestellt?
#   bash deploy/sparse_checkout.sh enable     Verzeichnisse ausblenden
#   bash deploy/sparse_checkout.sh disable    Alles zurueckholen
#
# Als DIENSTBENUTZER ausfuehren (auf ECHT: jarvis), nicht als root – sonst
# entstehen in .git wieder root-eigene Dateien und der naechste Update scheitert
# an genau dem Problem, das hier behoben werden soll:
#   sudo runuser -u jarvis -- bash deploy/sparse_checkout.sh enable

set -u
JARVIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$JARVIS_DIR" || exit 1

# Was draussen bleibt. Nur Verzeichnisse, die im Betrieb NICHTS tun – geprueft
# per Suche nach Laufzeit-Zugriffen aus backend/, skills/ und den Startskripten.
AUSGESCHLOSSEN=(
    "tests"           # Einheiten-/UI-Tests, jsdom-Pruefstaende, Messwerkzeuge
    "android"         # Kotlin/Compose-App, wird lokal mit Gradle gebaut
    "windows-app-go"  # Go-Client, wird lokal uebersetzt
)

fehler() { echo "FEHLER: $*" >&2; exit 1; }

command -v git >/dev/null || fehler "git nicht gefunden."
git rev-parse --git-dir >/dev/null 2>&1 || fehler "$JARVIS_DIR ist kein Git-Repository."

# sparse-checkout gibt es seit Git 2.25 (Debian 13 hat 2.47).
GIT_MIN="2.25.0"
GIT_VER="$(git --version | awk '{print $3}')"
if [ "$(printf '%s\n%s\n' "$GIT_MIN" "$GIT_VER" | sort -V | head -1)" != "$GIT_MIN" ]; then
    fehler "Git $GIT_VER ist zu alt – sparse-checkout braucht mindestens $GIT_MIN."
fi

status() {
    if [ "$(git config --get core.sparseCheckout 2>/dev/null)" = "true" ]; then
        echo "Sparse-Checkout: AKTIV"
        echo "Muster:"
        sed 's/^/  /' .git/info/sparse-checkout 2>/dev/null
    else
        echo "Sparse-Checkout: aus (vollstaendiger Checkout)"
    fi
    echo "Vorhanden im Arbeitsbaum:"
    for d in "${AUSGESCHLOSSEN[@]}"; do
        if [ -e "$d" ]; then echo "  $d  (da)"; else echo "  $d  – ausgeblendet"; fi
    done
}

case "${1:-status}" in
status)
    status
    ;;

enable)
    # Schranke 1: lokale Aenderungen in den betroffenen Verzeichnissen. Das
    # Ausblenden LOESCHT sie aus dem Arbeitsbaum – nicht versionierte Arbeit
    # waere unwiederbringlich weg.
    VORHANDEN=()
    for d in "${AUSGESCHLOSSEN[@]}"; do [ -e "$d" ] && VORHANDEN+=("$d"); done
    SCHMUTZ=""
    [ ${#VORHANDEN[@]} -gt 0 ] && SCHMUTZ="$(git status --porcelain -- "${VORHANDEN[@]}" 2>/dev/null)"
    if [ -n "$SCHMUTZ" ]; then
        echo "Nicht eingecheckte Aenderungen in den auszublendenden Verzeichnissen:" >&2
        echo "$SCHMUTZ" | sed 's/^/  /' >&2
        fehler "Erst committen oder verwerfen – Ausblenden wuerde diese Dateien entfernen."
    fi

    # Schranke 2: sieht das nach einer Entwicklungsmaschine aus?
    if [ -d ".git/refs/heads" ] && [ -n "$(git config --get user.email 2>/dev/null)" ]; then
        echo "Hinweis: In diesem Repo ist eine git-Identitaet gesetzt ($(git config --get user.email))."
        echo "Auf einem Produktivserver ist das unueblich – ist das hier wirklich Produktion?"
        read -r -p "Fortfahren? [j/N] " a
        [ "$a" = "j" ] || [ "$a" = "J" ] || fehler "Abgebrochen."
    fi

    # --no-cone ist Absicht, nicht Bequemlichkeit: der Cone-Modus kennt nur
    # EINSCHLIESSEN. Man muesste alle uebrigen Verzeichnisse aufzaehlen – und ein
    # spaeter hinzukommendes Verzeichnis fehlte dann STILL im Checkout. Mit
    # "/*" plus Negationen ist die Vorgabe "alles", und nur die genannten
    # Verzeichnisse fallen heraus.
    git sparse-checkout init --no-cone 2>/dev/null || fehler "sparse-checkout init fehlgeschlagen."
    MUSTER=("/*")
    for d in "${AUSGESCHLOSSEN[@]}"; do MUSTER+=("!/$d/"); done
    git sparse-checkout set --no-cone "${MUSTER[@]}" || fehler "sparse-checkout set fehlgeschlagen."

    echo "OK – ausgeblendet: ${AUSGESCHLOSSEN[*]}"
    echo
    status
    echo
    echo "Der naechste 'git pull' ignoriert diese Verzeichnisse. Zurueckholen:"
    echo "  bash deploy/sparse_checkout.sh disable"
    ;;

disable)
    git sparse-checkout disable || fehler "sparse-checkout disable fehlgeschlagen."
    echo "OK – vollstaendiger Checkout wiederhergestellt."
    status
    ;;

*)
    fehler "Unbekannter Befehl '${1}'. Erlaubt: status | enable | disable"
    ;;
esac
