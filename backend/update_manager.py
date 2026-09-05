"""Jarvis Update-Manager – Git-basiertes Update-System mit Auto-Update-Cron."""

import asyncio
import os
import pwd
import subprocess
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

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


def _mit_diagnose(fehler: str, *roh: str) -> str:
    """Haengt die Klartext-Diagnose an, wenn die Git-Ausgabe nach Rechten riecht.

    Fail-safe: Schlaegt die Diagnose selbst fehl, bleibt die Original-Meldung
    stehen. Eine kaputte Fehlerbehandlung darf die Fehlermeldung nicht ersetzen.
    """
    try:
        if not _gitfehler_riecht_nach_rechten(fehler, *roh):
            return fehler
        d = diagnose_permissions()
        if d.get("ok"):
            return fehler
        return f"{fehler}\n\n⚠ {d['hint']}"
    except Exception:
        return fehler


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


def check_update() -> dict:
    """Prüft ob Updates verfügbar sind. Führt git fetch aus."""
    # Aktuellen Commit
    _, current_hash, _ = _git("rev-parse", "HEAD")
    _, current_short, _ = _git("rev-parse", "--short", "HEAD")
    _, branch, _ = _git("rev-parse", "--abbrev-ref", "HEAD")
    branch = branch or "master"

    # Remote abrufen (Silent Fetch)
    rc_fetch, _, fetch_err = _git("fetch", "origin", branch, timeout=15)
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

    # Letzte Commit-Info vom Remote
    latest_info = {}
    if commits_behind > 0:
        _, log_str, _ = _git(
            "log", f"origin/{branch}", "-5",
            "--format=%H|%s|%ai|%an", "--no-merges"
        )
        commits = []
        for line in log_str.splitlines():
            parts = line.split("|", 3)
            if len(parts) == 4:
                h, msg, date, author = parts
                commits.append({
                    "hash": h[:7],
                    "message": msg.strip(),
                    "date": date.strip()[:16],
                    "author": author.strip(),
                })
        latest_info = {"recent_commits": commits}

    return {
        "ok": True,
        "has_update": commits_behind > 0,
        "commits_behind": commits_behind,
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


def apply_update() -> dict:
    """Führt git pull aus. Lokal geänderte Dateien werden per stash/pop bewahrt."""
    # Aktuellen Branch ermitteln (für gezieltes Pull ohne Upstream-Tracking)
    _, branch, _ = _git("rev-parse", "--abbrev-ref", "HEAD")
    branch = branch or "master"

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
    rc, out, err = _git("pull", "origin", branch, timeout=60)
    if rc != 0:
        # Pull fehlgeschlagen → Stash sofort zurückspielen
        if stashed:
            _git("stash", "pop")
        # NIE leer zurueckgeben, sonst zeigt das Frontend nur "Unbekannter Fehler".
        roh = err or out or f"git pull fehlgeschlagen (Code {rc}, keine Ausgabe)"
        return {"ok": False, "error": _mit_diagnose(roh, err, out), "output": out}

    # 3. Stash zurückspielen
    pop_note = ""
    if stashed:
        pop_rc, pop_out, pop_err = _git("stash", "pop")
        if pop_rc != 0:
            pop_note = ("\n⚠ Lokale Änderungen konnten nicht automatisch wiederhergestellt "
                        "werden: " + _mit_diagnose(pop_err, pop_err, pop_out))

    return {"ok": True, "output": out + pop_note,
            "broker_betroffen": _broker_betroffen(vorher_hash)}


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
    return any(z.strip().startswith("backend/broker/") for z in out.splitlines())


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
            print("[Update] backend/broker/* geaendert – starte den Root-Broker "
                  "mit neu (sonst bleibt er auf altem Code).", flush=True)
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
