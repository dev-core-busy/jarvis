"""Jarvis Update-Manager – Git-basiertes Update-System mit Auto-Update-Cron."""

import asyncio
import os
import pwd
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

# Reiht Fetch der Pruefung und Pull des Updates hintereinander (Vorfall
# 2026-10-26, siehe check_update). Wirkt nur innerhalb des Dienstes; gegen
# fremde Prozesse schuetzt ``--no-write-fetch-head`` in der Pruefung.
_GIT_SPERRE = threading.Lock()

# ─── Eigentuemer-Diagnose ────────────────────────────────────────────────────
#
# Der Fall, der das gebaut hat (ECHT, 2026-07-31): `/opt/jarvis/tests` gehoerte
# root, alles andere jarvis. Der als jarvis laufende Update meldete
#     Fehler: unable to unlink old 'tests/…': Keine Berechtigung
#     Schwerwiegend: cannot create directory at 'tests/tools': Keine Berechtigung
# und das war alles, was der Betreiber zu sehen bekam. Aus dieser Meldung geht
# NICHT hervor, dass ein Verzeichnis dem falschen Benutzer gehoert – sie klingt
# nach einem kaputten Repository.
#
# Der Schluessel: Zum Ersetzen einer Datei oder Anlegen eines Verzeichnisses
# braucht git Schreibrecht auf dem UEBERGEORDNETEN Verzeichnis, nicht auf der
# Datei. Ein einzelnes fremdes Verzeichnis legt deshalb jeden Update lahm, der
# darin etwas aendert – und zwar erst dann, oft Monate spaeter.


def _gitfehler_riecht_nach_rechten(*texte: str) -> bool:
    """Deutet die Git-Ausgabe auf ein Rechteproblem hin?

    Die Marker sind bewusst die ENGLISCHEN Git-Fragmente: Git uebersetzt diese
    Meldungen nicht, wohl aber die errno-Beschreibung dahinter (auf ECHT stand
    dort „Keine Berechtigung", auf einem englischen System „Permission denied").
    Wer nur auf den uebersetzten Teil prueft, findet den Fall genau auf dem
    System nicht, auf dem er auftritt. Die deutschen/englischen errno-Texte
    stehen trotzdem mit drin – schaden nichts und fangen aeltere Git-Versionen.
    """
    heu = " ".join(t or "" for t in texte).lower()
    return any(m in heu for m in (
        "unable to unlink", "cannot create directory", "unable to create file",
        "unable to write", "permission denied", "keine berechtigung",
    ))


def _fremde_pfade(limit: int = 200) -> list[str]:
    """Versionierte Pfade (+ deren Verzeichnisse + .git), die NICHT uns gehoeren.

    Bewusst ueber `git ls-files` statt eines Verzeichnis-Durchlaufs: PROJECT_ROOT
    enthaelt `venv/` mit ~100.000 Dateien, die git gar nicht anfasst. Geprueft
    wird genau die Menge, auf die git beim Pull schreiben muss – die versionierten
    Dateien, ihre Elternverzeichnisse (dort entstehen neue Dateien) und `.git`.
    """
    try:
        me = os.geteuid()
    except Exception:
        return []
    rc, out, _ = _git("ls-files", "-z", timeout=30)
    if rc != 0:
        return []
    kandidaten: set[str] = {".", ".git"}
    for rel in out.split("\0"):
        if not rel:
            continue
        kandidaten.add(rel)
        # Jede Ebene darueber: das Schreibrecht haengt am Elternverzeichnis.
        teil = os.path.dirname(rel)
        while teil:
            kandidaten.add(teil)
            teil = os.path.dirname(teil)
    fremd = []
    for rel in sorted(kandidaten):
        try:
            st = os.lstat(os.path.join(PROJECT_ROOT, rel))
        except OSError:
            continue          # geloescht/unlesbar – hier nicht unser Thema
        if st.st_uid != me:
            fremd.append(rel)
            if len(fremd) >= limit:
                break
    return fremd


def _benutzername(uid: int) -> str:
    try:
        return pwd.getpwuid(uid).pw_name
    except Exception:
        return f"UID {uid}"


def diagnose_permissions() -> dict:
    """Prueft die Eigentuemerschaft des Arbeitsverzeichnisses.

    Rueckgabe: ``{"ok": True}`` wenn alles uns gehoert, sonst ``ok: False`` mit
    ``hint`` (fertiger Klartext fuer die Oberflaeche), ``paths`` (Beispiele) und
    ``fix`` (der Befehl, der es behebt).
    """
    # ALS ROOT GIBT ES DIESES PROBLEM NICHT – root umgeht die Rechtepruefung des
    # Dateisystems. Ohne diese Schranke meldet die Funktion, aufgerufen aus einer
    # Root-Shell, dass „200 Pfade jemand anderem gehoeren" und schlaegt
    # `chown -R root:root` vor. Das ist genau falsch herum: es wuerde dem
    # Dienstbenutzer das Verzeichnis entziehen und den Dienst lahmlegen.
    # (Beim Ausrollen am 2026-07-31 auf DEV genau so passiert und hier behoben.)
    try:
        if os.geteuid() == 0:
            return {"ok": True, "note": "als root ausgefuehrt – Eigentuemer sind hier ohne Belang"}
    except Exception:
        pass
    fremd = _fremde_pfade()
    if not fremd:
        return {"ok": True}
    me = _benutzername(os.geteuid())
    # Verzeichnisse zuerst nennen – sie sind die eigentliche Sperre.
    verz = [p for p in fremd if (PROJECT_ROOT / p).is_dir()]
    beispiele = (verz or fremd)[:5]
    try:
        besitzer = sorted({
            _benutzername(os.lstat(os.path.join(PROJECT_ROOT, p)).st_uid)
            for p in fremd[:20]
        })
    except Exception:
        besitzer = []
    # Fuer den chown die Kennung nehmen, die auch dann funktioniert, wenn der
    # Name nicht aufloesbar ist: chown akzeptiert numerische UIDs. Ein Befehl
    # wie `chown -R UID 1234:UID 1234` waere nicht nur nutzlos, sondern beim
    # Hineinkopieren gefaehrlich (zwei Argumente statt einem).
    uid = os.geteuid()
    kennung = me if me and not me.startswith("UID ") else str(uid)
    fix = f"sudo chown -R {kennung}:{kennung} {PROJECT_ROOT}"
    wem = "/".join(besitzer) if besitzer else "einem anderen Benutzer"
    liste = ", ".join(beispiele) + (" und weitere" if len(fremd) > len(beispiele) else "")
    hinweis = (
        f"Das Update laeuft als Benutzer '{me}', aber {len(fremd)} Pfad(e) unter "
        f"{PROJECT_ROOT} gehoeren '{wem}'. Git braucht Schreibrecht auf dem "
        f"uebergeordneten VERZEICHNIS, um eine Datei zu ersetzen oder anzulegen – "
        f"deshalb bricht der Pull ab, sobald ein Commit dort etwas aendert. "
        f"Betroffen: {liste}. Behebung auf dem Server: {fix}"
    )
    return {"ok": False, "hint": hinweis, "paths": fremd[:20], "fix": fix, "user": me}


# ─── Herkunft (BSI H1) ───────────────────────────────────────────────────────
#
# Befund H1 (BSI-Abgleich 2026-09-29): das Update zog, was auf GitHub lag – ohne
# zu pruefen, WER es dort hingelegt hat. Der Transport per SSH (Deploy Key, fester
# Host-Schluessel) belegt nur die Gegenstelle. Seit 2026-09-30 wird nur eine
# Spitze uebernommen, die mit einem Schluessel aus SIGNATUR_ANKER signiert ist.
#
# Die Pruefung sitzt IM Pull (``merge.verifySignatures``), nicht davor: ein
# eigenes verify-commit mit anschliessendem ``git pull`` holte zweimal – und
# zwischen Pruefen und Holen koennte sich die Spitze aendern.
#
# Der Anker ist root-eigen (signatur_einrichten.sh); fehlt er, bleibt es beim
# alten Verhalten (Bestand vor der Einrichtung, DEV). Der Broker-Installer
# prueft dieselbe Datei fuer seine root-eigene Kopie.
SIGNATUR_ANKER = Path(os.environ.get("JARVIS_SIGNATUR_ANKER", "/etc/jarvis/allowed_signers"))

SIGNATUR_HINWEIS = (
    "Update abgelehnt: der Stand auf GitHub ist nicht mit einem zugelassenen "
    "Schlüssel signiert. Übernommen wird nur, was der Betreiber signiert hat – "
    "bitte den Stand signiert neu veröffentlichen (signierter Commit auf master)."
)


def _signatur_optionen() -> list[str]:
    """Git-Optionen, die die Herkunftspruefung erzwingen – leer ohne Anker.

    Ausdruecklich uebergeben statt der Repo-Konfiguration zu vertrauen:
    ``.git/config`` kann jeder aendern, der im Baum schreiben darf, und ein
    geloeschter Eintrag wuerde die Pruefung still abschalten."""
    if not SIGNATUR_ANKER.exists():
        return []
    return ["-c", f"gpg.ssh.allowedSignersFile={SIGNATUR_ANKER}",
            "-c", "gpg.ssh.program=/usr/bin/ssh-keygen",
            "-c", "merge.verifySignatures=true"]


def signatur_status(ref: str) -> str:
    """'ok' / 'fehlt' (unsigniert oder fremder Schluessel) / 'ungeprueft' (kein Anker)."""
    opt = _signatur_optionen()
    if not opt:
        return "ungeprueft"
    rc, _, _ = _git(*opt, "verify-commit", ref, timeout=30)
    return "ok" if rc == 0 else "fehlt"


HISTORIE_HINWEIS = (
    "Update abgelehnt: der Stand auf GitHub setzt nicht auf dem Stand dieses "
    "Servers auf (die Versionsgeschichte wurde neu geschrieben). Ein automatisches "
    "Zusammenführen würde hier Konflikte hinterlassen – bitte den Server einmalig "
    "von Hand auf den neuen Stand umstellen (git fetch, verify-commit, reset --hard)."
)


KONFLIKT_HINWEIS = (
    "Update nicht möglich: ein früheres Update konnte lokale Änderungen nicht "
    "zurückspielen, im Arbeitsverzeichnis steht noch ein ungelöster Konflikt. "
    "Bitte einmalig von Hand auflösen (als Dienstbenutzer im Programmverzeichnis): "
    "die genannten Dateien auf den Stand der Software setzen "
    "(git checkout HEAD -- <datei>) und den gesicherten lokalen Stand prüfen "
    "(git stash list / git stash show -p) – danach läuft das Update wieder."
)


NACHARBEIT_HINWEIS = (
    "Lokale Änderungen an diesen Dateien widersprachen dem neuen Stand und wurden "
    "NICHT zurückgespielt – es gilt der neue Stand. Die lokale Fassung ist "
    "gesichert und lässt sich mit git stash show -p ansehen bzw. mit "
    "git stash drop verwerfen, wenn sie überholt ist:"
)


ZUGANG_HINWEIS = (
    "Kein Lesezugang zum Repository – es ist privat. Einmalig als root "
    "einrichten: deploy/security/deploy_key_einrichten.sh (aus der root-eigenen "
    "Broker-Kopie), dann die beiden angezeigten Schlüssel bei GitHub als "
    "Deploy Key (nur lesend) eintragen."
)


def _gitfehler_zugang(*texte: str) -> bool:
    """Scheitert Git am ZUGANG zum Remote (privates Repository, fehlender
    Deploy Key) statt an Dateirechten?

    Seit 2026-09-30 ist das Repository privat; anonym per https meldet Git
    "could not read Username", per SSH ohne eingetragenen Schluessel
    "Permission denied (publickey)". Das zweite traf vorher die Rechte-Marker
    ("permission denied") und schickte die Diagnose auf die Suche nach fremden
    Dateien – eine Fehldiagnose mit dem Anschein einer Messung."""
    heu = " ".join(t or "" for t in texte).lower()
    return any(m in heu for m in (
        "could not read username", "permission denied (publickey)",
        "repository not found", "host key verification failed",
        "authentication failed", "terminal prompts disabled",
    ))


def _mit_diagnose(fehler: str, *roh: str) -> str:
    """Haengt die Klartext-Diagnose an, wenn die Git-Ausgabe nach Rechten riecht.

    Zugangsfehler (privates Repository) kommen ZUERST und bekommen ihren
    eigenen Hinweis – die Rechte-Diagnose waere dort falsch.
    Fail-safe: Schlaegt die Diagnose selbst fehl, bleibt die Original-Meldung
    stehen. Eine kaputte Fehlerbehandlung darf die Fehlermeldung nicht ersetzen.
    """
    try:
        if _gitfehler_zugang(fehler, *roh):
            return f"{fehler}\n\n⚠ {ZUGANG_HINWEIS}"
        if not _gitfehler_riecht_nach_rechten(fehler, *roh):
            return fehler
        d = diagnose_permissions()
        if d.get("ok"):
            return fehler
        return f"{fehler}\n\n⚠ {d['hint']}"
    except Exception:
        return fehler


# ─── Image-Betrieb (Docker) ──────────────────────────────────────────────────
#
# GEMELDET 2026-10-26 von einem Docker-Anwender: das Image enthaelt weder
# /app/.git noch das git-Programm. Pruefen und Anwenden scheiterten deshalb mit
# "git fetch fehlgeschlagen: [Errno 2] No such file or directory: 'git'" – eine
# Meldung, die nach kaputter Installation klingt, obwohl der Weg dort schlicht
# ein anderer ist: neues Image ziehen, Container neu erzeugen. Die Volumes
# (data, certs, /etc/jarvis) tragen den Zustand ueber den Neuaufbau.
#
# Nur im Docker-Modus: ein Container mit eingehaengtem Checkout UND git
# aktualisiert weiter ueber git. Ausserhalb von Docker bleibt die bisherige
# Fehlermeldung – dort ist ein fehlendes git tatsaechlich ein Fehler.

IMAGE_HINWEIS = (
    "Diese Installation läuft als Docker-Container ohne Git-Checkout. "
    "Aktualisiert wird über ein neues Image: auf dem Docker-Host "
    "`docker compose pull && docker compose up -d` ausführen. "
    "Daten, Zertifikate und /etc/jarvis liegen in Volumes und bleiben erhalten."
)


def image_betrieb() -> bool:
    """Docker-Container, in dem ein git-Update nicht moeglich ist?"""
    if os.environ.get("JARVIS_DOCKER", "0") != "1":
        return False
    return not (PROJECT_ROOT / ".git").exists() or shutil.which("git") is None


# ─── Git-Hilfsfunktionen ─────────────────────────────────────────────────────

def _git(*args, timeout=20) -> tuple[int, str, str]:
    """Führt einen Git-Befehl aus und gibt (returncode, stdout, stderr) zurück."""
    try:
        r = subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "Timeout"
    except Exception as e:
        return -1, "", str(e)


# ─── Commit-Liste im Update-Popup ────────────────────────────────────────────
#
# Je ausstehendem Commit ein Satz Beschreibung fuer den Administrator. Quelle
# ist eine eigene Zeile ``Kurz: <Satz>`` im Commit-Text (darf ueber mehrere
# Zeilen umbrechen, endet an der Leerzeile); fehlt sie, der erste Satz des
# ersten Absatzes. Gelistet werden NUR die Commits, die das Update bringt
# (HEAD..origin) – bis 2026-10-30 stand hier ``log origin/<branch> -5``, also
# immer die letzten fuenf, auch bereits eingespielte, und bei mehr als fuenf
# fehlte der Rest ohne Hinweis.

MAX_COMMIT_LISTE = 30     # mehr liest im Popup niemand; der Rest wird beziffert
MAX_BESCHREIBUNG = 240    # Zeichen; ein Satz, kein Absatz

_KURZ_MARKE = "kurz:"
# Git-Trailer (Co-Authored-By, Signed-off-by …) tragen einen Bindestrich im
# Schluessel. "Gemeldet:" oder "Waechter:" sind Fliesstext und bleiben.
_TRAILER = re.compile(r"^[A-Za-z]+(?:-[A-Za-z]+)+:\s")
# Satzende: Punkt/Ausrufe-/Fragezeichen, danach Leerraum und KEIN Kleinbuchstabe
# (sonst endet "z. B. der" nach dem "z.").
_SATZENDE = re.compile(r"[.!?](?=\s+[^a-zäöüß\s]|\s*$)")
# Abkuerzungen, an deren Punkt kein Satz endet (dazu jeder Einzelbuchstabe wie
# in "z. B."). Gesehen: 'meldete nur "Katalog erreichbar" bzw.' als Satz.
_ABKUERZUNGEN = {"bzw", "ggf", "usw", "vgl", "ca", "inkl", "evtl", "nr", "etc",
                 "zzgl", "max", "min", "sog", "bspw", "eg", "ie", "vs"}


def _kuerzen(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= MAX_BESCHREIBUNG:
        return text
    schnitt = text[:MAX_BESCHREIBUNG].rsplit(" ", 1)[0]
    return schnitt.rstrip(" ,;:-") + " …"


def kurzbeschreibung(text: str) -> str:
    """Ein Satz aus dem Commit-Text (ohne Betreffzeile); leer, wenn es keinen gibt."""
    zeilen = (text or "").replace("\r", "").split("\n")
    # 1) Ausdrueckliche Zeile "Kurz: …" samt Fortsetzungszeilen bis zur Leerzeile
    for i, z in enumerate(zeilen):
        if z.strip().lower().startswith(_KURZ_MARKE):
            teile = [z.strip()[len(_KURZ_MARKE):]]
            for f in zeilen[i + 1:]:
                if not f.strip() or _TRAILER.match(f.strip()):
                    break
                teile.append(f)
            satz = _kuerzen(" ".join(teile))
            if satz:
                return satz
    # 2) Rueckfall: erster Absatz; ist er ein Trailer-Block, gibt es keinen Satz
    absatz: list[str] = []
    for z in zeilen + [""]:
        s = z.strip()
        if s.lower().startswith(_KURZ_MARKE):
            s = ""                 # leere Kurz-Zeile: ihr Absatz zaehlt nicht
        if s:
            absatz.append(s)
            continue
        if absatz:
            break
    if not absatz or all(_TRAILER.match(a) for a in absatz):
        return ""
    fliess = " ".join(absatz)
    if fliess.startswith("- "):
        fliess = fliess[2:]
    for m in _SATZENDE.finditer(fliess):
        wort = re.split(r"[\s(\"']", fliess[:m.start()])[-1]
        if len(wort) <= 1 or wort.lower() in _ABKUERZUNGEN:
            continue
        return _kuerzen(fliess[:m.end()])
    return _kuerzen(fliess)


def ausstehende_commits(branch: str) -> dict:
    """Die Commits, die ein Update bringen wuerde, neueste zuerst."""
    bereich = f"HEAD..origin/{branch}"
    # Feld- und Satztrenner als Steuerzeichen: Betreff und Text duerfen alles
    # enthalten, auch "|" (die alte Zerlegung daran brach bei einem Betreff damit).
    # NICHT \x1c-\x1f: Python zaehlt sie zum Leerraum, das strip() in _git
    # frass damit beim aeltesten Commit ohne Text die letzten Trenner weg.
    _, log_str, _ = _git(
        "log", bereich, f"-{MAX_COMMIT_LISTE}", "--no-merges",
        "--format=%H%x02%s%x02%ai%x02%an%x02%b%x03",
    )
    commits = []
    for satz in log_str.split("\x03"):
        felder = satz.lstrip("\n").split("\x02")
        if len(felder) != 5:
            continue
        h, msg, date, author, text = felder
        commits.append({
            "hash": h[:7],
            "message": msg.strip(),
            "beschreibung": kurzbeschreibung(text),
            "date": date.strip()[:16],
            "author": author.strip(),
        })
    _, anzahl, _ = _git("rev-list", "--count", "--no-merges", bereich)
    gesamt = int(anzahl) if anzahl.isdigit() else len(commits)
    return {"recent_commits": commits,
            "commits_weitere": max(0, gesamt - len(commits))}


def check_update() -> dict:
    """Prüft ob Updates verfügbar sind. Führt git fetch aus."""
    if image_betrieb():
        # Kein Fehler, sondern ein anderer Weg – die Oberflaeche zeigt den Hinweis
        # statt eines roten "git fetch fehlgeschlagen".
        return {"ok": True, "image": True, "hinweis": IMAGE_HINWEIS,
                "current_hash": "", "branch": "", "has_update": False,
                "commits_behind": 0, "recent_commits": []}
    # Aktuellen Commit
    _, current_hash, _ = _git("rev-parse", "HEAD")
    _, current_short, _ = _git("rev-parse", "--short", "HEAD")
    _, branch, _ = _git("rev-parse", "--abbrev-ref", "HEAD")
    branch = branch or "master"

    # Remote abrufen (Silent Fetch)
    #
    # ``--no-write-fetch-head``: die Pruefung braucht nur origin/<branch>.
    # ⚠ VORFALL 2026-10-26 (ECHT): der Update-Knopf meldete "Kann nicht zu
    # mehreren Branches vorspulen", der zweite Klick lief durch. git fetch
    # KUERZT FETCH_HEAD zu Beginn und HAENGT am Ende an - laufen zwei Fetches
    # gleichzeitig (Pruefung beim Oeffnen der Pill + Pull des Knopfs), stehen
    # danach zwei Merge-Zeilen darin, und ``pull --ff-only`` bricht ab. Im
    # Sandkasten nachgestellt: 199 von 200 Laeufen. Ohne FETCH_HEAD-Schreiben
    # kann die Pruefung den Pull nicht mehr stoeren - auch nicht einen
    # ``git pull`` aus einem anderen Prozess (Auto-Update per Agent-Shell).
    with _GIT_SPERRE:
        rc_fetch, _, fetch_err = _git("fetch", "--no-write-fetch-head", "origin", branch,
                                      timeout=15)
    if rc_fetch != 0:
        # Auch der Fetch kann an Rechten scheitern: er schreibt .git/FETCH_HEAD.
        return {
            "ok": False,
            "error": _mit_diagnose(f"git fetch fehlgeschlagen: {fetch_err}", fetch_err),
            "current_hash": current_short,
            "branch": branch,
            "has_update": False,
            "commits_behind": 0,
        }

    # Anzahl Commits hinter Remote
    _, behind_str, _ = _git("rev-list", f"HEAD..origin/{branch}", "--count")
    commits_behind = int(behind_str) if behind_str.isdigit() else 0

    latest_info = {}
    if commits_behind > 0:
        latest_info = ausstehende_commits(branch)

    return {
        "ok": True,
        "has_update": commits_behind > 0,
        "commits_behind": commits_behind,
        # Herkunft der Spitze, die ein Update uebernaehme (H1). "fehlt" heisst:
        # apply_update wird sie ablehnen.
        "signatur": signatur_status(f"origin/{branch}") if commits_behind > 0 else "",
        "current_hash": current_short,
        "current_hash_full": current_hash,
        "branch": branch,
        **latest_info,
    }


def _stash_count() -> int:
    """Anzahl der vorhandenen Stash-Einträge (locale-unabhängig)."""
    rc, out, _ = _git("stash", "list")
    if rc != 0 or not out:
        return 0
    return len(out.splitlines())


def _konfliktdateien() -> list[str]:
    """Pfade mit ungeloestem Konflikt im Index (locale-unabhaengig, -z gegen Quoting)."""
    rc, out, _ = _git("diff", "--name-only", "--diff-filter=U", "-z")
    if rc != 0 or not out:
        return []
    return [p for p in out.split("\0") if p.strip()]


# Dateien, die der Server SELBST erzeugt und die deshalb nicht versioniert
# sind. Vor einem Pull wird eine noch verfolgte Fassung zurueckgesetzt - siehe
# die ausfuehrliche Begruendung in apply_update().
_ERZEUGTE_DATEIEN = (
    "ai-mouse/src/AiMouse/Configuration/Vorgaben.cs",
)


def apply_update() -> dict:
    """Führt git pull aus. Lokal geänderte Dateien werden per stash/pop bewahrt.

    Unter ``_GIT_SPERRE``: zwei Updates (zwei Reiter) oder Update + Pruefung
    duerfen nicht gleichzeitig holen - siehe Vorfall in check_update()."""
    with _GIT_SPERRE:
        return _apply_update_gesperrt()


def _apply_update_gesperrt() -> dict:
    if image_betrieb():
        return {"ok": False, "image": True, "error": IMAGE_HINWEIS}
    # Aktuellen Branch ermitteln (für gezieltes Pull ohne Upstream-Tracking)
    _, branch, _ = _git("rev-parse", "--abbrev-ref", "HEAD")
    branch = branch or "master"

    # Ungeloester Konflikt aus einem frueheren Lauf? Dann scheitern stash UND
    # pull mit einer Git-Meldung, die nicht sagt, was zu tun ist ("Pullen ist
    # nicht moeglich, weil Sie nicht zusammengefuehrte Dateien haben"). Hier
    # wird NICHT selbst aufgeloest: woher der Konflikt stammt und ob der Stash
    # dazu noch existiert, weiss dieser Lauf nicht.
    vorab = _konfliktdateien()
    if vorab:
        return {"ok": False, "konflikt": vorab,
                "error": KONFLIKT_HINWEIS + "\n\n" + "\n".join(vorab[:20])}

    # 0. ERZEUGTE Dateien zuruecksetzen, BEVOR gestasht wird.
    #
    # ⚠ GEMESSEN AM 2026-09-15, und der Befund ist die Begruendung: eine Datei,
    # die hier VERFOLGT und lokal GEAENDERT ist und im eingehenden Commit aus
    # dem Index faellt, laesst `stash pop` mit einem ungelosten Konflikt
    # zurueck (`DU`, aendern/loeschen). Der Dienst startet zwar - es entstehen
    # keine Konfliktmarker -, aber **jeder weitere Pull scheitert**, bis jemand
    # den Konflikt von Hand aufloest. Genau dieser Zustand hat ECHT am
    # 2026-08-30 handlungsunfaehig gemacht, und der Betreiber kann ihn ohne
    # fremde Hilfe nicht einmal SEHEN: sein Update meldet Erfolg.
    #
    # Betroffen ist `Vorgaben.cs` (Marke, Akzent, Adresse der AI-Maus): sie
    # wird vor JEDEM Bau neu geschrieben und steht seit dem 2026-09-15 in der
    # .gitignore. Das Zuruecksetzen ist verlustfrei - die Hauswerte schreibt
    # der naechste Bau ohnehin aus dem Branding des Servers.
    #
    # Nach der Migration laeuft die Schleife ins Leere (die Datei ist dann
    # nicht mehr verfolgt, `ls-files` liefert nichts). Sie bleibt trotzdem
    # stehen: ein Server, der diesen Commit erst spaeter zieht, braucht sie -
    # und ein zweiter Eintrag kostet nichts.
    for _erzeugt in _ERZEUGTE_DATEIEN:
        rc, aus, _ = _git("ls-files", "--error-unmatch", _erzeugt)
        if rc == 0 and aus.strip():
            _git("checkout", "--", _erzeugt)

    # 1. Lokale Änderungen stashen – verhindert Merge-Konflikte bei data/-Dateien
    #    Locale-unabhängig: Stash-Anzahl vor/nach push vergleichen statt den
    #    lokalisierten Git-Text ("No local changes to save" / "Keine lokalen
    #    Änderungen zum Speichern") zu parsen.
    count_before = _stash_count()
    _git("stash", "push", "-m", "jarvis-auto-pre-update")
    stashed = _stash_count() > count_before

    # Stand VOR dem Pull merken - nur so laesst sich hinterher feststellen,
    # WAS sich geaendert hat (siehe broker_betroffen unten).
    _, vorher_hash, _ = _git("rev-parse", "HEAD")

    # 2. Pull (mit explizitem Branch – funktioniert auch ohne Upstream-Tracking)
    #    Mit Anker prueft der Pull selbst die Signatur der Spitze (H1).
    #
    #    ``--ff-only``: ein Server committet nie, ein Update ist also immer ein
    #    Vorspulen. GEMESSEN AM 2026-09-30 auf ECHT: nach dem Umschreiben der
    #    Historie (Echtwerte -> Platzhalter) stand ECHT 511 voraus / 513 hinterher;
    #    der Merge-Pull haette in ueber 30 Dateien Konflikte hinterlassen und jeder
    #    weitere Pull waere gescheitert. So wird abgelehnt, HEAD bleibt stehen.
    sig_opt = _signatur_optionen()
    rc, out, err = _git(*sig_opt, "pull", "--ff-only", "origin", branch, timeout=60)
    if rc != 0:
        # Pull fehlgeschlagen → Stash sofort zurückspielen
        if stashed:
            _git("stash", "pop")
        # Abgelehnt wegen der Herkunft? Git sagt das auf Englisch und je nach
        # Fall anders ("does not have a GPG signature", "untrusted", "No
        # principal matched") – deshalb am geholten Stand nachpruefen statt
        # Texte zu raten.
        if sig_opt and signatur_status("FETCH_HEAD") == "fehlt":
            return {"ok": False, "signatur": "fehlt",
                    "error": SIGNATUR_HINWEIS + "\n\n" + (err or out)[-400:],
                    "output": out}
        # Nicht vorspulbar: HEAD ist kein Vorfahre des geholten Stands.
        if _git("rev-parse", "-q", "--verify", "FETCH_HEAD")[0] == 0 and \
                _git("merge-base", "--is-ancestor", "HEAD", "FETCH_HEAD")[0] == 1:
            return {"ok": False, "historie": "abweichend",
                    "error": HISTORIE_HINWEIS + "\n\n" + (err or out)[-400:],
                    "output": out}
        # NIE leer zurueckgeben, sonst zeigt das Frontend nur "Unbekannter Fehler".
        roh = err or out or f"git pull fehlgeschlagen (Code {rc}, keine Ausgabe)"
        return {"ok": False, "error": _mit_diagnose(roh, err, out), "output": out}

    # 3. Stash zurückspielen
    #
    # ⚠ VORFALL 2026-10-02 (ECHT): ein Pop mit Konflikt liess den Index mit
    # einem ungeloesten Eintrag zurueck (`UU frontend/userchat.html`), das
    # Update meldete trotzdem Erfolg – und JEDER weitere Pull scheiterte, bis
    # jemand von Hand aufloeste. Bei einem Konflikt gilt deshalb der NEUE
    # Stand: `stash pop` verwirft den Stash bei Konflikt nicht, die lokale
    # Fassung bleibt also verlustfrei gesichert. Danach den Index leeren, damit
    # die sauber zurueckgespielten Dateien wie im Regelfall nur im
    # Arbeitsbaum liegen (pop staged sie bei einem Konflikt).
    pop_note = ""
    nacharbeit = None
    if stashed:
        pop_rc, pop_out, pop_err = _git("stash", "pop")
        if pop_rc != 0:
            konflikt = _konfliktdateien()
            if konflikt:
                _git("checkout", "HEAD", "--", *konflikt)
                _git("reset", "-q")
                rest = _konfliktdateien()
                nacharbeit = {"dateien": konflikt,
                              "gesichert": _stash_count() > count_before,
                              "ungeloest": rest}
                pop_note = ("\n⚠ " + NACHARBEIT_HINWEIS + "\n" + "\n".join(konflikt[:20]))
                if rest:
                    pop_note += "\n⚠ " + KONFLIKT_HINWEIS
            else:
                pop_note = ("\n⚠ Lokale Änderungen konnten nicht automatisch wiederhergestellt "
                            "werden: " + _mit_diagnose(pop_err, pop_err, pop_out))

    erg = {"ok": True, "output": out + pop_note,
           "broker_betroffen": _broker_betroffen(vorher_hash)}
    if nacharbeit:
        erg["nacharbeit"] = nacharbeit
    return erg


_BROKER_PFADE = ("backend/broker/", "start_jarvis_root.sh", "deploy/security/")


def _broker_betroffen(vorher_hash: str) -> bool:
    """Hat der Pull ``backend/broker/*`` angefasst?

    ⚠ DER FALLSTRICK, DEN DIESE FUNKTION SCHLIESST: Der Root-Broker ist ein
    EIGENER Prozess mit einer EIGENEN Kopie von ``backend/broker/*``. Die
    Update-Pille startete bisher ausschliesslich ``jarvis.service`` neu - der
    Broker lief danach mit ALTEM Code weiter, und jede neu hinzugekommene Op
    antwortete ``502 unbekannte Op``. Im Register steht das seit Langem als
    Deploy-Fallstrick; ausgerechnet der automatische Update-Weg hat es nie
    beruecksichtigt. Ein Server, der ueber die Pille aktualisiert, bekam damit
    stillschweigend einen halben Stand.

    Fail-closed in die SICHERE Richtung: laesst sich der Vergleich nicht
    fuehren (kein alter Hash, git antwortet nicht), wird der Broker
    vorsichtshalber MIT neu gestartet. Ein Neustart zu viel kostet ein paar
    Sekunden, ein vergessener kostet eine unerklaerliche Fehlfunktion.
    """
    if not vorher_hash:
        return True
    rc, out, _ = _git("diff", "--name-only", vorher_hash, "HEAD", timeout=30)
    if rc != 0:
        return True
    # ⚠ NICHT NUR backend/broker/: der Broker fuehrt beim START auch
    # start_jarvis_root.sh und deploy/security/* aus (Haertung, SSH-Erneuerung,
    # Node-Automatik) und ruft deploy/security/* in seinen Ops (Fernzugang).
    # ECHT 2026-10-06: ein Update brachte die Node-Automatik in beide Dateien,
    # der Broker lief trotzdem mit der alten Kopie weiter.
    return any(z.strip().startswith(_BROKER_PFADE) for z in out.splitlines())


def restart_service_delayed(delay_sec: float = 2.0, context: str = "Auto-Update angewendet",
                           auch_broker: bool = False):
    """Startet den Service nach delay_sec Sekunden neu (in einem Thread, via Root-Broker).

    ``auch_broker=True`` startet ZUERST den Root-Broker neu - noetig, sobald ein
    Update ``backend/broker/*`` angefasst hat (siehe ``_broker_betroffen``).

    ⚠ ZUR REIHENFOLGE: erst der Broker, dann das Backend. Andersherum liefe das
    frisch gestartete Backend gegen einen Broker mit altem Code.

    ⚠ DER SELBSTNEUSTART SIEHT WIE EIN FEHLER AUS UND IST KEINER: der Broker
    fuehrt den Befehl aus und beendet sich dabei selbst, die Antwort erreicht
    uns also oft nicht mehr. Der Auftrag liegt zu diesem Zeitpunkt bereits bei
    systemd. Deshalb wird der Rueckgabewert NICHT als Erfolgskriterium genommen
    - gewartet wird auf den neuen Socket.

    context: informativer Ausloeser fuers Broker-Audit (Standard: Auto-Update)."""
    def _do():
        time.sleep(delay_sec)
        from backend import broker_client
        if auch_broker:
            # Pfade aus _BROKER_PFADE, nicht abgetippt: ECHT 2026-10-12 nannte
            # die Zeile "backend/broker/*", geaendert war start_jarvis_root.sh.
            # "betroffen" statt "geaendert": _broker_betroffen startet auch
            # fail-closed neu, wenn sich der Vergleich nicht fuehren laesst.
            print(f"[Update] Broker-Teil betroffen ({', '.join(_BROKER_PFADE)}) – "
                  "starte den Root-Broker mit neu (sonst bleibt er auf altem "
                  "Code).", flush=True)
            try:
                broker_client.systemctl_sync("restart", "jarvis-broker.service",
                                             user="system", context=context)
            except Exception as e:                            # noqa: BLE001
                print(f"[Update] Broker-Neustart: {e} (erwartbar – er beendet "
                      f"sich dabei selbst)", flush=True)
            # Auf den neuen Socket warten. Der Bootstrap startet erst x11vnc und
            # websockify; wer sofort danach eine Op ruft, bekommt 502 und sucht
            # den Fehler im Code (Register).
            sock = getattr(broker_client, "SOCKET_PATH", "/run/jarvis-broker.sock")
            for _ in range(40):
                time.sleep(1)
                if os.path.exists(sock):
                    break
            else:
                print("[Update] ⚠ Der Broker-Socket ist nach 40 s nicht da – "
                      "der Neustart von jarvis.service laeuft trotzdem.", flush=True)
        res = broker_client.systemctl_sync("restart", "jarvis.service", user="system", context=context)
        if not res.get("ok"):
            print(f"[Update] Neustart via Broker fehlgeschlagen: {res.get('error') or res.get('stderr')}", flush=True)
    threading.Thread(target=_do, daemon=True).start()
