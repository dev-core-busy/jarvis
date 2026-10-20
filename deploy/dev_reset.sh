#!/bin/bash
# DEV auf origin/master zuruecksetzen - ABER NIE ueber fremde Arbeit hinweg.
#
# ⚠ WARUM ES DIESES SKRIPT GIBT (Vorfall 2026-10-11). Der letzte Schritt von
# `c+p` ist auf DEV `git fetch` + `git reset --hard origin/master`. CLAUDE.md
# sagt dazu "vorher die abweichenden Dateien in ein tar sichern" - ich habe
# bei einem von fuenf Resets nur die ANZAHL ausgegeben und im selben Skript
# resettet. Auf DEV lagen fuenf per scp deployte Dateien eines parallelen
# Arbeitsstands (knowledge.js, vision.js, settings.html, wissen.html,
# vision_engine.py); der Reset hat sie ueberschrieben. Rekonstruierbar waren
# sie nur, weil dieselben Dateien im Arbeitsbaum noch lagen - das war Glueck,
# keine Vorsorge.
#
# Dass vier Resets davor "0 Abweichungen" zeigten, war genau das Problem: eine
# Regel, die meist nicht greift, wird nachlaessig behandelt. Deshalb entscheidet
# das jetzt nicht mehr ein Mensch im Augenblick, sondern dieses Skript:
#   · Abweichungen? -> SICHERN, BENENNEN, ABBRECHEN (Exit 3). Keine Aktion.
#   · Erst ein ausdrueckliches --uebernehmen setzt zurueck.
# Die Dateien werden NAMENTLICH ausgegeben, nicht gezaehlt: eine Zahl sagt
# nicht, was man verliert.
#
# ⚠ JEDER git-Aufruf laeuft als DIENSTBENUTZER. Auch lesende Aufrufe schreiben
# (`git status` aktualisiert .git/index); als root ausgefuehrt gehoert der Index
# danach root, und der naechste Abruf des Dienstes scheitert mit
# "Unzureichende Berechtigung ... .git/objects" (Register, am 2026-10-11 mit 45
# root-eigenen Objekten wiedergefunden).
#
# Aufruf (als root auf DEV):
#   deploy/dev_reset.sh --pruefen        nur melden, nie aendern
#   deploy/dev_reset.sh                  sichern; bei Abweichungen abbrechen
#   deploy/dev_reset.sh --uebernehmen    sichern UND zuruecksetzen
#   deploy/dev_reset.sh --uebernehmen --wiederherstellen
#                                        sichern, zuruecksetzen, Arbeitsstand
#                                        wieder drueberlegen (md5-belegt)
#   deploy/dev_reset.sh --wiederherstellen [--kein-neustart]
#                                        nur die neueste Sicherung zurueckholen
#   zusaetzlich: --dir <pfad> (Vorgabe /opt/jarvis), --dienst <name>,
#                --kein-neustart
# Exit: 0 = zurueckgesetzt (oder nichts zu tun) · 2 = falscher Aufruf/Umgebung
#       3 = Abweichungen vorhanden, NICHT zurueckgesetzt · 1 = Fehler

set -u

DIR="/opt/jarvis"
DIENST="jarvis.service"
MODUS="sichern"          # sichern | pruefen | uebernehmen
NEUSTART=1
WIEDERHER=0
SICHERUNG=""        # von --uebernehmen gesetzt; sonst die neueste

meldung() { echo "[DEV-Reset] $*"; }
fehler()  { echo "[DEV-Reset] FEHLER: $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --pruefen)       MODUS="pruefen"; shift ;;
        --uebernehmen)   MODUS="uebernehmen"; shift ;;
        --dir)           DIR="${2:-}"; shift 2 ;;
        --dienst)        DIENST="${2:-}"; shift 2 ;;
        --kein-neustart) NEUSTART=0; shift ;;
        --wiederherstellen) WIEDERHER=1; shift ;;
        *) echo "Unbekanntes Argument: $1" >&2; exit 2 ;;
    esac
done
[ "$(id -u)" = "0" ] || { echo "Nur als root." >&2; exit 2; }

# ⚠ Als root ausgefuehrt darf dieses Skript nicht aus einem Ort kommen, den ein
# anderer aendern kann - sonst ist es selbst der Weg zu root (Befund K1).
# Genau das ist hier naheliegend: die Datei liegt im Repo unter
# deploy/dev_reset.sh, und /opt/jarvis gehoert dem DIENSTBENUTZER. Wer sie von
# dort als root startet, laesst root ausfuehren, was `jarvis` hineinschreibt.
# Dieselbe Schranke wie in deploy/security/deploy_key_einrichten.sh.
SELF="$(readlink -f "$0")"
for p in "$SELF" "$(dirname "$SELF")"; do
    if [ "$(stat -c '%u' "$p")" != "0" ] || [ $(( 0$(stat -c '%a' "$p") & 022 )) -ne 0 ]; then
        echo "[DEV-Reset] FEHLER: $p gehoert nicht root oder ist fremd beschreibbar." >&2
        echo "            Vorher in einen root-eigenen Ort kopieren, z. B.:" >&2
        echo "              install -o root -g root -m 0700 $SELF /root/dev_reset.sh" >&2
        echo "              /root/dev_reset.sh $*" >&2
        exit 2
    fi
done
[[ "$DIR" =~ ^/[A-Za-z0-9._/-]+$ ]] || { echo "--dir ungueltig" >&2; exit 2; }
[ -d "$DIR/.git" ] || { echo "$DIR ist kein git-Arbeitsbaum" >&2; exit 2; }

# Dienstbenutzer = Eigentuemer des Arbeitsbaums. NICHT geraten: ein falscher
# Benutzer hinterlaesst genau die Eigentuemer-Schaeden, die oben stehen.
NUTZER="$(stat -c %U "$DIR")"
id "$NUTZER" >/dev/null 2>&1 || { echo "Eigentuemer '$NUTZER' von $DIR ist kein Konto" >&2; exit 2; }
g() { runuser -u "$NUTZER" -- git -C "$DIR" "$@"; }

meldung "Arbeitsbaum $DIR, Dienstbenutzer $NUTZER"
VORHER="$(g rev-parse --short HEAD)" || fehler "HEAD nicht lesbar"
meldung "HEAD vorher: $VORHER"

# ── Abweichungen feststellen ──────────────────────────────────────────────
# --ignored bewusst NICHT: erzeugte Dateien (__pycache__, node_modules) sind
# kein Arbeitsstand. Verfolgte Aenderungen und unverfolgte Dateien sind es.
ABW="$(g status --porcelain)" || fehler "git status fehlgeschlagen"
ANZ=$(printf '%s' "$ABW" | grep -c . || true)

# ⚠ --wiederherstellen OHNE --uebernehmen ist ein EIGENER Vorgang, kein Reset.
# Die Schranke unten fragt "darf ich verfolgte Aenderungen wegwerfen?" - das
# ist hier die falsche Frage, denn es wird nichts zurueckgesetzt, sondern eine
# Sicherung zurueckgeholt. Beim Bau lief dieser Fall in die Schranke und endete
# mit Exit 3 und der Meldung "es wird nichts zurueckgesetzt" - richtig und
# irrefuehrend, weil niemand einen Reset verlangt hatte (gemessen 2026-10-12,
# zwei meiner eigenen Proben waren dadurch wertlos).
if [ "$WIEDERHER" = "1" ] && [ "$MODUS" != "uebernehmen" ]; then
    NUR_WIEDERHER=1
    meldung "nur Wiederherstellen - kein fetch, kein reset."
else
    NUR_WIEDERHER=0
fi

if [ "$NUR_WIEDERHER" = "0" ] && [ "$ANZ" -gt 0 ]; then
    # ⚠ NUR VERFOLGTE AENDERUNGEN GEHEN BEIM RESET VERLOREN. `git reset --hard`
    # laesst unverfolgte Dateien stehen (im Sandkasten am 2026-10-11 gemessen:
    # wip.txt ueberlebte). Beides in einen Topf zu werfen waere eine
    # Falschaussage im Warntext - und ein Warntext, der uebertreibt, wird
    # beim dritten Mal ueberlesen.
    VERLUST="$(printf '%s\n' "$ABW" | grep -v '^??' || true)"
    BLEIBT="$(printf '%s\n' "$ABW" | grep '^??' || true)"
    N_VERLUST=$(printf '%s' "$VERLUST" | grep -c . || true)
    N_BLEIBT=$(printf '%s' "$BLEIBT" | grep -c . || true)

    meldung "$ANZ Abweichung(en) gefunden – NAMENTLICH:"
    if [ "$N_VERLUST" -gt 0 ]; then
        meldung "  $N_VERLUST verfolgte Aenderung(en) – DIESE gehen beim Reset verloren:"
        printf '%s\n' "$VERLUST" | sed 's/^/      /'
    fi
    if [ "$N_BLEIBT" -gt 0 ]; then
        meldung "  $N_BLEIBT unverfolgte Datei(en) – die ueberleben den Reset:"
        printf '%s\n' "$BLEIBT" | sed 's/^/      /'
    fi

    # --pruefen legt KEINE Sicherung an: es verspricht "nur melden, nie
    # aendern", und eine Datei in /root ist eine Aenderung. Ein Vertrag, der
    # nicht gilt, ist sein eigener Defekt - gemessen und behoben, bevor das
    # Skript in Gebrauch ging.
    if [ "$MODUS" = "pruefen" ]; then
        meldung "--pruefen: keine Sicherung angelegt, nichts geaendert."
        meldung "Zum Sichern ohne Reset: $0${DIR:+ --dir $DIR}"
        exit 3
    fi

    # Sichern, bevor irgendetwas angefasst wird. Ins HOME von root (0700),
    # nicht nach /tmp: /tmp wird geleert (Register).
    # ⚠ Sekundengenauer Name KOLLIDIERT: zwei Laeufe in derselben Sekunde
    # schrieben am 2026-10-11 im Sandkasten dieselbe Datei, der zweite hat die
    # Sicherung des ersten UEBERSCHRIEBEN. Eine Sicherung, die eine Sicherung
    # zerstoert, ist keine. Deshalb zusaetzlich die PID und keine Ueberschreibung.
    ZIEL="/root/dev-abweichungen-$(date +%Y%m%d-%H%M%S)-$$.tgz"
    [ -e "$ZIEL" ] && fehler "Sicherungsziel $ZIEL existiert bereits – es wird NICHTS zurueckgesetzt."
    # Nur verfolgte Aenderungen UND unverfolgte Dateien, Pfade NUL-getrennt,
    # damit Leerzeichen im Namen nicht zerfallen.
    if printf '%s\n' "$ABW" | sed 's/^...//' | tr '\n' '\0' \
         | tar czf "$ZIEL" -C "$DIR" --null -T - 2>/dev/null; then
        chmod 0600 "$ZIEL"
        meldung "gesichert: $ZIEL ($(stat -c %s "$ZIEL") Bytes, $(tar tzf "$ZIEL" | wc -l) Eintraege)"
        SICHERUNG="$ZIEL"
    else
        fehler "Sicherung nach $ZIEL fehlgeschlagen – es wird NICHTS zurueckgesetzt."
    fi

    if [ "$MODUS" != "uebernehmen" ]; then
        meldung "ABBRUCH: es wird nichts zurueckgesetzt."
        meldung "Diese Dateien gehen beim Reset verloren. Entweder committen/woanders"
        meldung "sichern, oder den Verlust ausdruecklich in Kauf nehmen:"
        meldung "    $0 --uebernehmen${DIR:+ --dir $DIR}"
        meldung "Wiederherstellen aus der Sicherung: tar xzf $ZIEL -C $DIR"
        exit 3
    fi
    meldung "--uebernehmen gesetzt: der Reset laeuft, die Sicherung liegt oben."
else
    meldung "keine Abweichungen."
fi

[ "$MODUS" = "pruefen" ] && { meldung "--pruefen: nichts geaendert."; exit 0; }

if [ "$NUR_WIEDERHER" = "1" ]; then
    NACHHER="$VORHER"          # nichts bewegt sich am HEAD
else

# ── Abruf und Reset ───────────────────────────────────────────────────────
# ⚠ Exit-Code VOR jedem Pipe pruefen. `git fetch | tail` meldet den Code von
# `tail`, `set -e` greift nicht, und der folgende Reset laeuft dann gegen den
# ALTEN origin/master - was wie ein Erfolg aussieht (Register).
g fetch origin
RC=$?
[ "$RC" -eq 0 ] || fehler "git fetch fehlgeschlagen (Exit $RC) – NICHT zurueckgesetzt."

ZIELSTAND="$(g rev-parse --short origin/master)" || fehler "origin/master nicht lesbar"
meldung "origin/master: $ZIELSTAND"

g reset --hard origin/master >/dev/null
RC=$?
[ "$RC" -eq 0 ] || fehler "git reset fehlgeschlagen (Exit $RC)"

NACHHER="$(g rev-parse --short HEAD)"
meldung "HEAD nachher: $NACHHER"
[ "$NACHHER" = "$ZIELSTAND" ] || fehler "HEAD ($NACHHER) != origin/master ($ZIELSTAND)"
REST=$(g status --porcelain | grep -c . || true)
meldung "Abweichungen danach: $REST"

# Eigentuemer-Schaeden einsammeln, falls doch jemand als root git gerufen hat.
ROOTIG=$(find "$DIR/.git" -user root | wc -l)
if [ "$ROOTIG" -gt 0 ]; then
    meldung "$ROOTIG root-eigene Datei(en) in .git – richtiggestellt."
    chown -R "$NUTZER":"$NUTZER" "$DIR/.git"
fi

if [ "$NEUSTART" = "1" ]; then
    systemctl restart "$DIENST"
    RC=$?
    [ "$RC" -eq 0 ] || fehler "Neustart von $DIENST fehlgeschlagen (Exit $RC)"
    sleep 5
    AKTIV="$(systemctl is-active "$DIENST")"
    meldung "$DIENST: $AKTIV"
    [ "$AKTIV" = "active" ] || fehler "$DIENST laeuft nach dem Neustart nicht"
fi

fi

# ── Wiederherstellen (--wiederherstellen) ─────────────────────────────────
# ⚠ WARUM DAS INS SKRIPT GEHOERT. Dreimal habe ich am 2026-10-12 nach dem
# Reset von Hand `tar xzf` gerufen, und zweimal ging es schief:
#   · als root ausgepackt -> .git/index gehoerte danach root, und der naechste
#     Abruf des Dienstbenutzers waere an "Unzureichende Berechtigung ...
#     .git/objects" gescheitert - genau die Falle, die dieses Skript intern
#     ueberall meidet.
#   · als Dienstbenutzer ausgepackt -> "Keine Berechtigung", denn die Sicherung
#     liegt mit 0600 bei root (richtig fuer Geheimnisse, aber dann kann er sie
#     nicht lesen).
# Ein Schritt, der nur AUSSERHALB des Skripts stattfindet, umgeht alle seine
# Schranken. Deshalb hier: als root auspacken, danach die ausgepackten Pfade
# dem Dienstbenutzer geben, und die Rueckgabe per md5 BELEGEN statt annehmen.
if [ "$WIEDERHER" = "1" ]; then
    A="$SICHERUNG"
    if [ -z "$A" ]; then
        A="$(ls -1t /root/dev-abweichungen-*.tgz 2>/dev/null | head -1)"
        [ -n "$A" ] && meldung "keine eigene Sicherung in diesem Lauf - nehme die neueste: $A"
    fi
    [ -n "$A" ] && [ -f "$A" ] || fehler "keine Sicherung zum Wiederherstellen gefunden"

    # Soll-Pruefsummen AUS DEM ARCHIV, bevor etwas angefasst wird.
    # ⚠ WAS DIESER VERGLEICH BELEGT UND WAS NICHT: er stellt Archiv gegen die
    # entpackte Datei, beweist also ein TREUES Auspacken (nichts abgeschnitten,
    # nichts von der Platte verfaelscht, Rechte haben den Schreibvorgang nicht
    # verhindert). Er kann NICHT sagen, ob das Archiv der richtige Stand ist -
    # ein falsches oder vertauschtes Archiv wird klaglos "byte-gleich"
    # wiederhergestellt. Beim Bau am 2026-10-12 habe ich genau das falsch
    # geprueft: ein absichtlich verfaelschtes Archiv meldete BYTE-GLEICH, und
    # das war richtig - meine Probe war die falsche. Wer den Stand pruefen
    # will, vergleicht gegen den Arbeitsbaum, nicht gegen das Archiv.
    SOLL="$(mktemp)"; IST="$(mktemp)"
    tar xzf "$A" -O --to-stdout >/dev/null 2>&1 || true   # Archiv lesbar?
    while IFS= read -r f; do
        case "$f" in */) continue ;; esac
        echo "$(tar xzOf "$A" "$f" 2>/dev/null | md5sum | cut -d' ' -f1)  $f" >> "$SOLL"
    done < <(tar tzf "$A")
    meldung "Wiederherstellen aus $A ($(grep -c . "$SOLL") Datei(en))"

    # ⚠ Auch das Wiederherstellen UEBERSCHREIBT - also vorher sichern, was es
    # trifft. Ein Vorgang, der nicht zurueckgenommen werden kann, braucht
    # keinen Schalter, sondern eine Sicherung.
    VOR_WH="/root/dev-vor-wiederherstellen-$(date +%Y%m%d-%H%M%S)-$$.tgz"
    if tar tzf "$A" | sed 's|/$||' | (cd "$DIR" && tr '\n' '\0' \
            | tar czf "$VOR_WH" -C "$DIR" --null -T - 2>/dev/null); then
        chmod 0600 "$VOR_WH"
        meldung "vorheriger Stand gesichert: $VOR_WH"
    else
        meldung "(nichts zu sichern - die Dateien gibt es im Baum noch nicht)"
    fi
    tar xzf "$A" -C "$DIR" || fehler "Auspacken nach $DIR fehlgeschlagen"
    # Nur die ausgepackten Pfade umhaengen - kein chown -R ueber den ganzen Baum.
    while IFS= read -r f; do
        case "$f" in */) continue ;; esac
        [ -e "$DIR/$f" ] && chown "$NUTZER":"$NUTZER" "$DIR/$f"
    done < <(tar tzf "$A")

    while IFS= read -r f; do
        case "$f" in */) continue ;; esac
        echo "$(md5sum "$DIR/$f" 2>/dev/null | cut -d' ' -f1)  $f" >> "$IST"
    done < <(tar tzf "$A")
    if diff -q <(sort "$SOLL") <(sort "$IST") >/dev/null; then
        meldung "wiederhergestellt und BYTE-GLEICH ($(grep -c . "$SOLL") Datei(en))"
    else
        diff <(sort "$SOLL") <(sort "$IST") | head -10
        rm -f "$SOLL" "$IST"
        fehler "Wiederherstellung NICHT byte-gleich - siehe Abweichungen oben"
    fi
    rm -f "$SOLL" "$IST"
    # Ein root-Rueckstand in .git waere genau der Schaden, den das Auspacken
    # sonst anrichtet - also noch einmal nachsehen.
    R2=$(find "$DIR/.git" -user root | wc -l)
    if [ "$R2" -gt 0 ]; then
        chown -R "$NUTZER":"$NUTZER" "$DIR/.git"
        meldung "$R2 root-eigene Datei(en) in .git nach dem Auspacken - richtiggestellt."
    fi
    meldung "Abweichungen jetzt: $(g status --porcelain | grep -c . || true) (der Arbeitsstand ist zurueck)"
fi

meldung "fertig: $VORHER -> $NACHHER"
exit 0
