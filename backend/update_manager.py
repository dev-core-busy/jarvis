"""Jarvis Update-Manager – Git-basiertes Update-System mit Auto-Update-Cron."""

import asyncio
import subprocess
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

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
        return {
            "ok": False,
            "error": f"git fetch fehlgeschlagen: {fetch_err}",
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

    # 2. Pull (mit explizitem Branch – funktioniert auch ohne Upstream-Tracking)
    rc, out, err = _git("pull", "origin", branch, timeout=60)
    if rc != 0:
        # Pull fehlgeschlagen → Stash sofort zurückspielen
        if stashed:
            _git("stash", "pop")
        # NIE leer zurueckgeben, sonst zeigt das Frontend nur "Unbekannter Fehler".
        return {"ok": False, "error": err or out or f"git pull fehlgeschlagen (Code {rc}, keine Ausgabe)", "output": out}

    # 3. Stash zurückspielen
    pop_note = ""
    if stashed:
        pop_rc, pop_out, pop_err = _git("stash", "pop")
        if pop_rc != 0:
            pop_note = f"\n⚠ Lokale Änderungen konnten nicht automatisch wiederhergestellt werden: {pop_err}"

    return {"ok": True, "output": out + pop_note}


def restart_service_delayed(delay_sec: float = 2.0):
    """Startet den Service nach delay_sec Sekunden neu (in einem Thread)."""
    def _do():
        time.sleep(delay_sec)
        subprocess.run(["systemctl", "restart", "jarvis.service"],
                       capture_output=True, timeout=10)
    threading.Thread(target=_do, daemon=True).start()
